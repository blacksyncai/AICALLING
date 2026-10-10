"""
Authentication and tenancy.

• Passwords: scrypt (stdlib), stored as "scrypt$<salt hex>$<hash hex>".
• Sessions: an HMAC-signed cookie "<b64 payload>.<b64 sig>", payload
  "<user_id>:<session_version>:<expires unix>". Changing a password bumps
  session_version, which signs every other device out.
• Every /api route resolves a Context — the signed-in user plus the
  organization (sub-account) they're working in — and scopes its queries
  to ctx.org.id. Super-admins may work in any organization.
• The public /api/v1 routes authenticate with an org API key instead.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.account import ApiKey, AppSecret, Membership, Organization, User

COOKIE_NAME = "bs_session"
SESSION_TTL_S = 60 * 60 * 24 * 14  # 14 days
MIN_PASSWORD = 8


# ── Passwords ─────────────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(digest.hex(), hash_hex)
    except Exception:
        return False


def check_password_strength(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD} characters.")


def generate_password() -> str:
    return secrets.token_urlsafe(12)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


# ── Signing key ───────────────────────────────────────────────────────────────

_signing_key: bytes | None = None


async def load_signing_key(db: AsyncSession) -> None:
    """SECRET_KEY when it's been set; otherwise a random key persisted in the database
    so sessions survive restarts and redeploys."""
    global _signing_key
    if settings.secret_key and settings.secret_key != "dev-secret-change-me":
        _signing_key = settings.secret_key.encode()
        return
    row = await db.get(AppSecret, "session_key")
    if row is None:
        row = AppSecret(key="session_key", value=secrets.token_hex(32))
        db.add(row)
        await db.commit()
    _signing_key = row.value.encode()


def _key() -> bytes:
    if _signing_key is None:
        raise RuntimeError("signing key not loaded")
    return _signing_key


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def create_session_token(user: User) -> str:
    payload = f"{user.id}:{user.session_version}:{int(time.time()) + SESSION_TTL_S}"
    sig = hmac.new(_key(), payload.encode(), hashlib.sha256).digest()
    return f"{_b64(payload.encode())}.{_b64(sig)}"


def parse_session_token(token: str) -> tuple[uuid.UUID, int] | None:
    try:
        p64, s64 = token.split(".")
        payload = _unb64(p64)
        if not hmac.compare_digest(hmac.new(_key(), payload, hashlib.sha256).digest(), _unb64(s64)):
            return None
        uid, version, exp = payload.decode().split(":")
        if int(exp) < time.time():
            return None
        return uuid.UUID(uid), int(version)
    except Exception:
        return None


def set_session_cookie(response: Response, request: Request, user: User) -> None:
    https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(
        COOKIE_NAME, create_session_token(user), max_age=SESSION_TTL_S,
        httponly=True, samesite="lax", secure=https, path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


# ── Request context ───────────────────────────────────────────────────────────


@dataclass
class Context:
    user: User
    org: Organization
    role: str  # owner | admin | member | superadmin (super-admin viewing an org they aren't in)

    @property
    def can_manage(self) -> bool:
        return self.role in ("owner", "admin", "superadmin") or self.user.is_superadmin

    @property
    def impersonating(self) -> bool:
        return self.role == "superadmin"


async def get_current_user(request: Request, db: Annotated[AsyncSession, Depends(get_db)]) -> User:
    token = request.cookies.get(COOKIE_NAME)
    parsed = parse_session_token(token) if token else None
    if not parsed:
        raise HTTPException(status_code=401, detail="Not signed in")
    user = await db.get(User, parsed[0])
    if not user or user.session_version != parsed[1]:
        raise HTTPException(status_code=401, detail="Session expired — sign in again")
    return user


async def resolve_org(db: AsyncSession, user: User) -> tuple[Organization | None, str]:
    """The user's active org (falling back to their first membership) and their role in it."""
    memberships = (await db.execute(
        select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at)
    )).scalars().all()
    by_org = {m.org_id: m for m in memberships}
    if user.active_org_id:
        if user.active_org_id in by_org:
            org = await db.get(Organization, user.active_org_id)
            if org:
                return org, by_org[user.active_org_id].role
        elif user.is_superadmin:
            org = await db.get(Organization, user.active_org_id)
            if org:
                return org, "superadmin"
    for m in memberships:
        org = await db.get(Organization, m.org_id)
        if org:
            return org, m.role
    return None, "member"


async def get_ctx(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Context:
    org, role = await resolve_org(db, user)
    if org is None:
        raise HTTPException(status_code=403, detail="Your login isn't part of an account yet.")
    return Context(user=user, org=org, role=role)


async def require_manager(ctx: Annotated[Context, Depends(get_ctx)]) -> Context:
    if not ctx.can_manage:
        raise HTTPException(status_code=403, detail="Only account owners and admins can do that.")
    return ctx


async def require_superadmin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_superadmin:
        raise HTTPException(status_code=403, detail="Admins only")
    return user


DbDep = Annotated[AsyncSession, Depends(get_db)]
CtxDep = Annotated[Context, Depends(get_ctx)]
ManagerDep = Annotated[Context, Depends(require_manager)]
SuperadminDep = Annotated[User, Depends(require_superadmin)]


# ── API keys (public /api/v1) ─────────────────────────────────────────────────

API_KEY_PREFIX = "bsk_"


def generate_api_key() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


async def get_api_org(request: Request, db: Annotated[AsyncSession, Depends(get_db)]) -> Organization:
    auth = request.headers.get("authorization", "")
    raw = auth[7:].strip() if auth.lower().startswith("bearer ") else request.headers.get("x-api-key", "").strip()
    if not raw:
        raise HTTPException(status_code=401, detail="Missing API key (Authorization: Bearer bsk_…)")
    key = (await db.execute(
        select(ApiKey).where(ApiKey.key_hash == sha256(raw), ApiKey.revoked_at.is_(None))
    )).scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    org = await db.get(Organization, key.org_id)
    if not org:
        raise HTTPException(status_code=401, detail="Invalid API key")
    key.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    return org


ApiOrgDep = Annotated[Organization, Depends(get_api_org)]
