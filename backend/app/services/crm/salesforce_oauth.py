"""
Native Salesforce OAuth (web-server flow with PKCE) through our own Salesforce Connected App.

start() → the Salesforce login URL; the browser comes back to /api/integrations/crm/salesforce/oauth/callback
with a code, which finish() swaps for an access + refresh token and the org's instance URL.
"""

from __future__ import annotations

import base64
import re
import hashlib
import secrets
import time
import uuid
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.services.crm.http import CrmError

CALLBACK_PATH = "/api/integrations/crm/salesforce/oauth/callback"
_PENDING: dict[str, dict] = {}  # state → who started it (one API process; a sign-in takes minutes at most)
_TTL = 15 * 60


def enabled() -> bool:
    return bool(settings.salesforce_client_id and settings.salesforce_client_secret)


def redirect_uri(base_url: str) -> str:
    return (settings.app_url or base_url).rstrip("/") + CALLBACK_PATH


def start(org_id: uuid.UUID, user_id: uuid.UUID, base_url: str, sandbox: bool = False) -> str:
    now = time.time()
    for k in [k for k, v in _PENDING.items() if v["at"] < now - _TTL]:
        _PENDING.pop(k, None)
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    host = "test.salesforce.com" if sandbox else "login.salesforce.com"
    _PENDING[state] = {"org_id": org_id, "user_id": user_id, "verifier": verifier, "host": host, "at": now,
                       "redirect_uri": redirect_uri(base_url)}
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return f"https://{host}/services/oauth2/authorize?" + urlencode({
        "response_type": "code", "client_id": settings.salesforce_client_id,
        "redirect_uri": _PENDING[state]["redirect_uri"], "state": state, "scope": "api refresh_token",
        "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "login consent"})


def take(state: str) -> dict | None:
    pending = _PENDING.pop(state or "", None)
    if not pending or pending["at"] < time.time() - _TTL:
        return None
    return pending


async def _token(host: str, data: dict) -> dict:
    """POST to the token endpoint. Our Connected App's id/secret unless the data brings the customer's own."""
    data = {"client_id": settings.salesforce_client_id, "client_secret": settings.salesforce_client_secret, **data}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(f"https://{host}/services/oauth2/token", data=data)
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code >= 400:
        raise CrmError(body.get("error_description") or body.get("error") or f"Sign-in failed ({resp.status_code}).",
                       resp.status_code)
    return body


async def finish(pending: dict, code: str) -> dict:
    """{access_token, refresh_token, instance_url, login_host}"""
    body = await _token(pending["host"], {"grant_type": "authorization_code", "code": code,
                                          "redirect_uri": pending["redirect_uri"], "code_verifier": pending["verifier"]})
    if not body.get("refresh_token"):
        raise CrmError("Salesforce didn't grant offline access — add the refresh_token scope to the Connected App.")
    return {"access_token": body.get("access_token", ""), "refresh_token": body["refresh_token"],
            "instance_url": body.get("instance_url", ""), "login_host": pending["host"]}


async def refresh_access_token(refresh_token: str, host: str) -> str:
    body = await _token(host, {"grant_type": "refresh_token", "refresh_token": refresh_token})
    if not body.get("access_token"):
        raise CrmError("Salesforce didn't return an access token. Reconnect Salesforce.", 401)
    return body["access_token"]


_ORG_DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.(my\.salesforce\.com|my\.salesforce-setup\.com)$")


def org_host(url: str) -> str:
    """The org's My Domain host from what the customer pasted ("https://acme.my.salesforce.com/…")."""
    host = (url or "").strip().lower()
    host = re.sub(r"^https?://", "", host).split("/")[0]
    host = host.replace(".lightning.force.com", ".my.salesforce.com")  # they often copy the Lightning address
    if not _ORG_DOMAIN.match(host):
        raise CrmError("Use your Salesforce domain, like acme.my.salesforce.com (Setup → My Domain).")
    return host


async def client_credentials_token(instance_url: str, client_id: str, client_secret: str) -> str:
    """An access token from the customer's own Connected App (Client Credentials Flow with a run-as user)."""
    host = org_host(instance_url)
    try:
        body = await _token(host, {"grant_type": "client_credentials", "client_id": client_id,
                                   "client_secret": client_secret})
    except CrmError as exc:
        if "client credentials" in str(exc).lower() or "not enabled" in str(exc).lower():
            raise CrmError("Turn on 'Enable Client Credentials Flow' (with a Run As user) in your Salesforce Connected App.",
                           exc.status) from exc
        raise
    return body.get("access_token") or ""
