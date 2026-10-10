"""
Clerk — verifies Clerk session tokens and talks to Clerk's Backend API.

The browser sends its short-lived Clerk session token (Authorization: Bearer,
or the `__session` cookie). We verify it against Clerk's JWKS, then map the
Clerk user to a BlackSync user by Clerk ID — or, the first time, by email —
so accounts, roles and credits keep living in BlackSync.
"""

from __future__ import annotations

import asyncio

import httpx
import jwt
import structlog

from app.config import settings

log = structlog.get_logger(__name__)

API = "https://api.clerk.com/v1"
_jwks: jwt.PyJWKClient | None = None


class ClerkError(Exception):
    pass


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.clerk_secret_key}"}


def _jwks_client() -> jwt.PyJWKClient:
    global _jwks
    if _jwks is None:
        _jwks = jwt.PyJWKClient(f"{API}/jwks", headers=_headers(), cache_keys=True, lifespan=3600)
    return _jwks


def _verify(token: str) -> dict:
    key = _jwks_client().get_signing_key_from_jwt(token)
    return jwt.decode(token, key.key, algorithms=["RS256"], leeway=10, options={"verify_aud": False})


async def verify_session_token(token: str) -> str | None:
    """The Clerk user id (sub) for a valid session token, else None."""
    try:
        claims = await asyncio.to_thread(_verify, token)
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
    emails = user.get("email_addresses") or []
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
