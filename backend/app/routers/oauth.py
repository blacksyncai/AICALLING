"""
OAuth 2.1 for the BlackSync connector: lets ChatGPT, Claude and other MCP clients act for a signed-in user.

  /.well-known/oauth-protected-resource[/api/mcp]  where the MCP server's tokens come from (RFC 9728)
  /.well-known/oauth-authorization-server         endpoints and capabilities (RFC 8414)
  POST /api/oauth/register                        dynamic client registration (RFC 7591)
  GET  /api/oauth/authorize                       checks the request, sends the browser to /connect to approve
  GET  /api/oauth/request, POST /api/oauth/approve  the approval page's API (signed-in user)
  POST /api/oauth/token                           authorization_code (PKCE S256) and refresh_token grants
  POST /api/oauth/revoke                          token revocation (RFC 7009)
  /api/oauth/connections                          the user's connected assistants (list, disconnect)

Clients may also identify themselves with a client metadata document (an https client_id URL); those are only
fetched from known assistant hosts. Authorization responses carry `iss` (RFC 9207).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import settings
from app.models.account import Membership, Organization, User
from app.models.oauth import OAuthClient, OAuthCode, OAuthToken
from app.services.auth import DbDep, UserDep

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/oauth", tags=["oauth"])
well_known = APIRouter(tags=["oauth"])

SCOPE = "blacksync"
ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=90)
CODE_TTL = timedelta(minutes=10)
REQUEST_TTL_S = 30 * 60
REFRESH_GRACE = timedelta(seconds=60)
# Client metadata documents are only fetched from these hosts (no fetching arbitrary URLs).
CIMD_HOSTS = {"chatgpt.com", "claude.ai", "claude.com", "openai.com"}
CIMD_REFRESH = timedelta(days=1)


def base_url() -> str:
    return (settings.app_url or "https://blacksync.si").rstrip("/")


def issuer() -> str:
    return base_url()


def resource_url() -> str:
    return f"{base_url()}/api/mcp"


def resource_metadata_url() -> str:
    return f"{base_url()}/.well-known/oauth-protected-resource/api/mcp"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: datetime | None) -> datetime | None:
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _iso(d: datetime | None) -> str | None:
    return _aware(d).isoformat() if d else None


# ── Discovery ────────────────────────────────────────────────────────────────


def _protected_resource() -> dict:
    return {
        "resource": resource_url(),
        "authorization_servers": [issuer()],
        "scopes_supported": [SCOPE],
        "bearer_methods_supported": ["header"],
        "resource_name": "BlackSync AI",
        "resource_documentation": f"{base_url()}/connect/help",
    }


@well_known.get("/.well-known/oauth-protected-resource")
@well_known.get("/.well-known/oauth-protected-resource/api/mcp")
async def protected_resource():
    return _protected_resource()


def _server_metadata() -> dict:
    api = f"{base_url()}/api/oauth"
    return {
        "issuer": issuer(),
        "authorization_endpoint": f"{api}/authorize",
        "token_endpoint": f"{api}/token",
        "registration_endpoint": f"{api}/register",
        "revocation_endpoint": f"{api}/revoke",
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "revocation_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "scopes_supported": [SCOPE],
        "client_id_metadata_document_supported": True,
        "authorization_response_iss_parameter_supported": True,
        "service_documentation": f"{base_url()}/connect/help",
    }


@well_known.get("/.well-known/oauth-authorization-server")
@well_known.get("/.well-known/oauth-authorization-server/api/mcp")
async def authorization_server():
    return _server_metadata()


# ── Clients ──────────────────────────────────────────────────────────────────


def _oauth_error(error: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": error, "error_description": description}, status_code=status,
                        headers={"Cache-Control": "no-store"})


def _valid_redirect(uri: str) -> bool:
    try:
        u = urlparse(uri)
    except ValueError:
        return False
    if u.fragment or not u.netloc:
        return False
    if u.scheme == "https":
        return True
    # Local tools (MCP Inspector, desktop apps) use loopback redirects.
    return u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1", "::1")


class Registration(BaseModel):
    redirect_uris: list[str] = Field(min_length=1, max_length=10)
    client_name: str = Field(default="", max_length=200)
    token_endpoint_auth_method: str = "none"
    grant_types: list[str] | None = None
    response_types: list[str] | None = None
    scope: str | None = None

    model_config = {"extra": "allow"}


@router.post("/register", status_code=201)
async def register(body: Registration, db: DbDep):
    bad = [u for u in body.redirect_uris if not _valid_redirect(u) or len(u) > 1000]
    if bad:
        return _oauth_error("invalid_redirect_uri", "Redirect URIs must be https (or loopback http).")
    method = body.token_endpoint_auth_method or "none"
    if method not in ("none", "client_secret_post", "client_secret_basic"):
        return _oauth_error("invalid_client_metadata", f"Unsupported token_endpoint_auth_method: {method}")
    client = OAuthClient(client_id=f"bsc_{secrets.token_urlsafe(18)}", client_name=body.client_name.strip()[:120],
                         redirect_uris=body.redirect_uris, auth_method=method, source="dcr")
    secret = None
    if method != "none":
        secret = f"bss_{secrets.token_urlsafe(32)}"
        client.secret_hash = _hash(secret)
    db.add(client)
    await db.commit()
    log.info("oauth_client_registered", client_id=client.client_id, name=client.client_name)
    out = {"client_id": client.client_id, "client_name": client.client_name, "redirect_uris": client.redirect_uris,
           "token_endpoint_auth_method": method, "grant_types": ["authorization_code", "refresh_token"],
           "response_types": ["code"], "scope": SCOPE, "client_id_issued_at": int(time.time())}
    if secret:
        out.update(client_secret=secret, client_secret_expires_at=0)
    return JSONResponse(out, status_code=201, headers={"Cache-Control": "no-store"})


async def _fetch_metadata_document(client_id: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as http:
            r = await http.get(client_id, headers={"Accept": "application/json"})
        if r.status_code != 200 or len(r.content) > 20_000:
            return None
        doc = r.json()
    except Exception as exc:
        log.warning("oauth_cimd_fetch_failed", client_id=client_id, error=str(exc)[:200])
        return None
    return doc if isinstance(doc, dict) and doc.get("client_id") == client_id else None


def is_metadata_client_id(client_id: str) -> bool:
    try:
        u = urlparse(client_id)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return u.scheme == "https" and bool(u.path.strip("/")) and any(host == h or host.endswith("." + h) for h in CIMD_HOSTS)


async def get_client(db, client_id: str) -> OAuthClient | None:
    if not client_id or len(client_id) > 300:
        return None
    client = await db.get(OAuthClient, client_id)
    if not is_metadata_client_id(client_id):
        return client if client and client.source == "dcr" else None
    if client and _now() - _aware(client.refreshed_at) < CIMD_REFRESH:
        return client
    doc = await _fetch_metadata_document(client_id)
    if not doc:
        return client  # keep using the last good copy if the host is briefly down
    uris = [u for u in (doc.get("redirect_uris") or []) if isinstance(u, str) and _valid_redirect(u)][:20]
    method = doc.get("token_endpoint_auth_method") or "none"
    if method != "none":  # only public clients with PKCE are accepted this way
        return None
    if client is None:
        client = OAuthClient(client_id=client_id, source="cimd")
        db.add(client)
    client.client_name = str(doc.get("client_name") or urlparse(client_id).hostname or "")[:120]
    client.redirect_uris, client.auth_method, client.refreshed_at = uris, "none", _now()
    await db.commit()
    return client


# ── Authorization ────────────────────────────────────────────────────────────


def _sign(payload: dict) -> str:
    from app.services.auth import _key

    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(hmac.new(_key(), b"oauth:" + raw.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return f"{raw}.{sig}"


def _unsign(token: str) -> dict | None:
    from app.services.auth import _key

    try:
        raw, sig = token.split(".", 1)
        want = base64.urlsafe_b64encode(hmac.new(_key(), b"oauth:" + raw.encode(), hashlib.sha256).digest()).decode().rstrip("=")
        if not hmac.compare_digest(want, sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) and payload.get("exp", 0) > time.time() else None


def _redirect_with(uri: str, params: dict) -> str:
    params = {k: v for k, v in params.items() if v not in (None, "")}
    return uri + ("&" if "?" in uri else "?") + urlencode({**params, "iss": issuer()})


def _resource_ok(resource: str) -> bool:
    return not resource or resource.rstrip("/") in (resource_url(), base_url())


@router.get("/authorize")
async def authorize(request: Request, db: DbDep):
    q = request.query_params
    client = await get_client(db, q.get("client_id", ""))
    redirect_uri = q.get("redirect_uri", "")
    if client is None:
        raise HTTPException(status_code=400, detail="Unknown app. Remove the BlackSync connector and add it again.")
    if not redirect_uri and len(client.redirect_uris) == 1:
        redirect_uri = client.redirect_uris[0]
    if redirect_uri not in client.redirect_uris:
        raise HTTPException(status_code=400, detail="This app's redirect address isn't registered.")
    state = q.get("state", "")

    def fail(error: str, description: str):
        return RedirectResponse(_redirect_with(redirect_uri, {"error": error, "error_description": description,
                                                              "state": state}), status_code=302)

    if q.get("response_type") != "code":
        return fail("unsupported_response_type", "Only the authorization code flow is supported.")
    challenge = q.get("code_challenge", "")
    if q.get("code_challenge_method") != "S256" or not (43 <= len(challenge) <= 128):
        return fail("invalid_request", "PKCE with S256 is required.")
    scopes = [s for s in (q.get("scope") or SCOPE).split() if s]
    unknown = [s for s in scopes if s not in (SCOPE, "offline_access")]
    if unknown:
        return fail("invalid_scope", f"Unknown scope: {' '.join(unknown)}")
    resource = q.get("resource", "")
    if not _resource_ok(resource):
        return fail("invalid_target", "This server only issues tokens for the BlackSync connector.")
    req = _sign({"c": client.client_id, "r": redirect_uri, "s": state[:500], "cc": challenge, "sc": SCOPE,
                 "rs": resource or resource_url(), "exp": int(time.time()) + REQUEST_TTL_S})
    return RedirectResponse(f"{base_url()}/connect?{urlencode({'req': req})}", status_code=302)


async def _accounts(db, user: User) -> list[dict]:
    rows = (await db.execute(select(Membership, Organization).join(Organization, Organization.id == Membership.org_id)
                             .where(Membership.user_id == user.id).order_by(Membership.created_at))).all()
    return [{"id": str(o.id), "name": o.name, "role": m.role} for m, o in rows]


@router.get("/request")
async def request_info(req: str, user: UserDep, db: DbDep):
    """What the approval page shows: which app is asking and which accounts the user can connect."""
    p = _unsign(req)
    if not p:
        raise HTTPException(status_code=400, detail="This connection request expired. Start again from the app.")
    client = await get_client(db, p["c"])
    if client is None:
        raise HTTPException(status_code=400, detail="Unknown app. Remove the BlackSync connector and add it again.")
    accounts = await _accounts(db, user)
    host = (urlparse(p["r"]).hostname or "").lower()
    return {"client_name": client.client_name or "An AI assistant", "redirect_host": host,
            # The name is whatever the app registered with; only these hosts are known assistants.
            "verified": any(host == h or host.endswith("." + h) for h in CIMD_HOSTS),
            "email": user.email, "accounts": accounts,
            "default_account": str(user.active_org_id) if any(a["id"] == str(user.active_org_id) for a in accounts)
            else (accounts[0]["id"] if accounts else None)}


class Approval(BaseModel):
    req: str
    approve: bool = True
    org_id: uuid.UUID | None = None


@router.post("/approve")
async def approve(body: Approval, user: UserDep, db: DbDep):
    p = _unsign(body.req)
    if not p:
        raise HTTPException(status_code=400, detail="This connection request expired. Start again from the app.")
    client = await get_client(db, p["c"])
    if client is None or p["r"] not in client.redirect_uris:
        raise HTTPException(status_code=400, detail="Unknown app. Remove the BlackSync connector and add it again.")
    if not body.approve:
        return {"redirect": _redirect_with(p["r"], {"error": "access_denied",
                                                    "error_description": "The user declined.", "state": p["s"]})}
    org_id = None
    if body.org_id:
        if str(body.org_id) not in {a["id"] for a in await _accounts(db, user)}:
            raise HTTPException(status_code=403, detail="You aren't a member of that account.")
        org_id = body.org_id
    code = secrets.token_urlsafe(32)
    db.add(OAuthCode(code_hash=_hash(code), client_id=client.client_id, user_id=user.id, org_id=org_id,
                     redirect_uri=p["r"], code_challenge=p["cc"], scope=p["sc"], resource=p["rs"],
                     expires_at=_now() + CODE_TTL))
    await db.commit()
    log.info("oauth_approved", client=client.client_name, user_id=str(user.id), org_id=str(org_id) if org_id else None)
    return {"redirect": _redirect_with(p["r"], {"code": code, "state": p["s"]})}


# ── Tokens ───────────────────────────────────────────────────────────────────


async def _form(request: Request) -> dict:
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        try:
            data = await request.json()
        except ValueError:
            return {}
        return {k: str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    form = await request.form()
    return {k: str(v) for k, v in form.items()}


def _client_credentials(request: Request, form: dict) -> tuple[str, str]:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("basic "):
        try:
            from urllib.parse import unquote

            cid, _, secret = base64.b64decode(auth[6:].strip()).decode().partition(":")
            return unquote(cid), unquote(secret)
        except (ValueError, UnicodeDecodeError):
            return "", ""
    return form.get("client_id", ""), form.get("client_secret", "")


async def _authenticate_client(db, request: Request, form: dict) -> OAuthClient | None:
    client_id, secret = _client_credentials(request, form)
    client = await get_client(db, client_id)
    if client is None:
        return None
    if client.auth_method != "none":
        if not secret or not client.secret_hash or not hmac.compare_digest(client.secret_hash, _hash(secret)):
            return None
    return client


def _pkce_ok(verifier: str, challenge: str) -> bool:
    if not (43 <= len(verifier) <= 128):
        return False
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return hmac.compare_digest(digest, challenge)


def _token_response(access: str, refresh: str, scope: str) -> JSONResponse:
    return JSONResponse({"access_token": access, "token_type": "Bearer", "expires_in": int(ACCESS_TTL.total_seconds()),
                         "refresh_token": refresh, "scope": scope},
                        headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


def _new_pair(t: OAuthToken) -> tuple[str, str]:
    access, refresh = f"bsa_{secrets.token_urlsafe(32)}", f"bsr_{secrets.token_urlsafe(40)}"
    now = _now()
    t.access_hash, t.access_expires_at = _hash(access), now + ACCESS_TTL
    t.refresh_hash, t.refresh_expires_at = _hash(refresh), now + REFRESH_TTL
    return access, refresh


@router.post("/token")
async def token(request: Request, db: DbDep):
    form = await _form(request)
    client = await _authenticate_client(db, request, form)
    if client is None:
        return _oauth_error("invalid_client", "Unknown client or bad client credentials.", 401)
    grant = form.get("grant_type", "")
    if grant == "authorization_code":
        code = (await db.execute(select(OAuthCode).where(OAuthCode.code_hash == _hash(form.get("code", ""))))).scalar_one_or_none()
        if (code is None or code.client_id != client.client_id or code.used_at or _aware(code.expires_at) < _now()):
            if code is not None and code.used_at:  # a replayed code: cut off whatever it was exchanged for
                for t in (await db.execute(select(OAuthToken).where(OAuthToken.client_id == code.client_id,
                                                                    OAuthToken.user_id == code.user_id,
                                                                    OAuthToken.created_at >= code.used_at))).scalars():
                    t.revoked_at = _now()
                await db.commit()
            return _oauth_error("invalid_grant", "The authorization code is invalid or expired.")
        if form.get("redirect_uri") and form["redirect_uri"] != code.redirect_uri:
            return _oauth_error("invalid_grant", "redirect_uri doesn't match the authorization request.")
        if not _pkce_ok(form.get("code_verifier", ""), code.code_challenge):
            return _oauth_error("invalid_grant", "PKCE verification failed.")
        if not _resource_ok(form.get("resource", "")):
            return _oauth_error("invalid_target", "This server only issues tokens for the BlackSync connector.")
        code.used_at = _now()
        t = OAuthToken(client_id=client.client_id, client_name=client.client_name, user_id=code.user_id,
                       org_id=code.org_id, scope=code.scope, resource=code.resource)
        access, refresh = _new_pair(t)
        db.add(t)
        await db.commit()
        log.info("oauth_token_issued", client=client.client_name, user_id=str(code.user_id))
        return _token_response(access, refresh, t.scope)

    if grant == "refresh_token":
        h = _hash(form.get("refresh_token", ""))
        t = (await db.execute(select(OAuthToken).where(OAuthToken.refresh_hash == h))).scalar_one_or_none()
        if t is None:
            # The previous refresh token, retried right after rotation (the client lost our reply): allow once briefly.
            t = (await db.execute(select(OAuthToken).where(OAuthToken.prev_refresh_hash == h))).scalar_one_or_none()
            if t is None or not t.rotated_at or _now() - _aware(t.rotated_at) > REFRESH_GRACE:
                return _oauth_error("invalid_grant", "The refresh token is invalid or expired.")
        if (t.client_id != client.client_id or t.revoked_at
                or (t.refresh_expires_at and _aware(t.refresh_expires_at) < _now())):
            return _oauth_error("invalid_grant", "The refresh token is invalid or expired.")
        user = await db.get(User, t.user_id)
        if user is None:
            return _oauth_error("invalid_grant", "The account no longer exists.")
        if t.refresh_hash == h:  # a normal refresh; a retry of the previous token keeps the original grace window
            t.prev_refresh_hash, t.rotated_at = h, _now()
        access, refresh = _new_pair(t)
        await db.commit()
        return _token_response(access, refresh, t.scope)

    return _oauth_error("unsupported_grant_type", "Use authorization_code or refresh_token.")


@router.post("/revoke")
async def revoke(request: Request, db: DbDep):
    form = await _form(request)
    client = await _authenticate_client(db, request, form)
    if client is None:
        return _oauth_error("invalid_client", "Unknown client or bad client credentials.", 401)
    h = _hash(form.get("token", ""))
    t = (await db.execute(select(OAuthToken).where((OAuthToken.access_hash == h) | (OAuthToken.refresh_hash == h))))\
        .scalar_one_or_none()
    if t is not None and t.client_id == client.client_id and not t.revoked_at:
        t.revoked_at = _now()
        await db.commit()
    return JSONResponse({}, headers={"Cache-Control": "no-store"})


async def token_for(db, raw: str) -> OAuthToken | None:
    """The live connection behind an access token, or None."""
    if not raw:
        return None
    t = (await db.execute(select(OAuthToken).where(OAuthToken.access_hash == _hash(raw)))).scalar_one_or_none()
    if t is None or t.revoked_at or _aware(t.access_expires_at) < _now():
        return None
    if t.resource and t.resource.rstrip("/") not in (resource_url(), base_url()):
        return None
    return t


# ── Connected assistants (settings page) ─────────────────────────────────────


@router.get("/connections")
async def connections(user: UserDep, db: DbDep):
    rows = (await db.execute(select(OAuthToken).where(OAuthToken.user_id == user.id, OAuthToken.revoked_at.is_(None))
                             .order_by(OAuthToken.created_at.desc()))).scalars().all()
    names = {str(o.id): o.name for o in (await db.execute(select(Organization).where(
        Organization.id.in_([r.org_id for r in rows if r.org_id])))).scalars()} if rows else {}
    live = [r for r in rows if r.refresh_expires_at is None or _aware(r.refresh_expires_at) > _now()]
    return {"connections": [{"id": str(r.id), "app": r.client_name or "AI assistant",
                             "account": names.get(str(r.org_id)) if r.org_id else None,
                             "connected_at": _iso(r.created_at), "last_used_at": _iso(r.last_used_at)} for r in live],
            "server_url": resource_url()}


@router.delete("/connections/{connection_id}", status_code=204)
async def disconnect(connection_id: uuid.UUID, user: UserDep, db: DbDep):
    t = await db.get(OAuthToken, connection_id)
    if t is None or t.user_id != user.id:
        raise HTTPException(status_code=404, detail="Connection not found")
    t.revoked_at = _now()
    await db.commit()
    log.info("oauth_disconnected", user_id=str(user.id), app=t.client_name)
