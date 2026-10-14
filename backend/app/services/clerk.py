"""
Clerk — verifies Clerk session tokens and talks to Clerk's Backend API.

The browser sends its short-lived Clerk session token (Authorization: Bearer,
or the `__session` cookie). We verify it against Clerk's JWKS, then map the
Clerk user to a BlackSync user by Clerk ID — or, the first time, by email —
so accounts, roles and credits keep living in BlackSync.
"""

from __future__ import annotations

import time

import httpx
import jwt
import structlog

from app.config import settings

log = structlog.get_logger(__name__)

API = "https://api.clerk.com/v1"
# Clerk's signing keys, by key id. (Fetched with httpx: Clerk's API refuses urllib,
# which PyJWT's own JWKS client uses.)
_keys: dict[str, jwt.PyJWK] = {}
_keys_fetched_at = 0.0


class ClerkError(Exception):
    pass


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.clerk_secret_key}"}


async def _signing_key(kid: str) -> jwt.PyJWK:
    global _keys_fetched_at
    # Refetch on an unknown key id (Clerk rotated keys), at most once a minute.
    if kid not in _keys and time.time() - _keys_fetched_at > 60:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{API}/jwks", headers=_headers())
        resp.raise_for_status()
        _keys.clear()
        for k in jwt.PyJWKSet.from_dict(resp.json()).keys:
            _keys[k.key_id] = k
        _keys_fetched_at = time.time()
    if kid not in _keys:
        raise jwt.InvalidKeyError(f"unknown signing key {kid}")
    return _keys[kid]


async def _verify(token: str) -> dict:
    kid = jwt.get_unverified_header(token).get("kid", "")
    key = await _signing_key(kid)
    return jwt.decode(token, key.key, algorithms=["RS256"], leeway=10, options={"verify_aud": False})


async def verify_session_token(token: str) -> str | None:
    """The Clerk user id (sub) for a valid session token, else None."""
    try:
        claims = await _verify(token)
    except Exception as exc:
        log.debug("clerk_token_invalid", error=str(exc))
        return None
    return claims.get("sub")


async def _request(method: str, path: str, **kwargs) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.request(method, f"{API}{path}", headers=_headers(), **kwargs)
    if resp.status_code >= 400:
        try:
            errors = resp.json().get("errors") or []
            message = errors[0].get("long_message") or errors[0].get("message")
            code = errors[0].get("code", "")
        except Exception:
            message, code = resp.text[:200], ""
        raise ClerkError(f"{message} ({code or resp.status_code})")
    return resp.json()


def primary_email(user: dict) -> str:
    """The user's verified primary email ("" if it isn't verified). Accounts — and platform-admin rights — are
    matched by this address, so an unverified one must never count."""
    emails = [e for e in user.get("email_addresses") or []
              if ((e.get("verification") or {}).get("status") == "verified")]
    primary = next((e for e in emails if e.get("id") == user.get("primary_email_address_id")), None)
    chosen = primary or (emails[0] if emails else None)
    return (chosen or {}).get("email_address", "").strip().lower()


async def get_user(clerk_user_id: str) -> dict:
    return await _request("GET", f"/users/{clerk_user_id}")


async def find_user_by_email(email: str) -> dict | None:
    users = await _request("GET", "/users", params={"email_address": email, "limit": 1})
    return users[0] if isinstance(users, list) and users else None


async def create_user(email: str, password: str, first_name: str = "", last_name: str = "") -> dict:
    body = {"email_address": [email], "password": password, "skip_password_checks": True}
    if first_name:
        body["first_name"] = first_name
    if last_name:
        body["last_name"] = last_name
    return await _request("POST", "/users", json=body)


async def set_password(clerk_user_id: str, password: str) -> None:
    await _request("PATCH", f"/users/{clerk_user_id}",
                   json={"password": password, "skip_password_checks": True, "sign_out_of_other_sessions": True})
