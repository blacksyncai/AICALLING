"""
Auth router — sign in/out, the current session, switching organizations,
and accepting team invites.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.account import Invite, Membership, Organization, User
from app.services.reporting import DEFAULT_TIMEZONE
from app.services.auth import (
    check_password_strength, clear_session_cookie, get_current_user, hash_password, normalize_email,
    resolve_org, set_session_cookie, sha256, verify_password,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    email: str
    password: str


class SwitchOrgBody(BaseModel):
    org_id: uuid.UUID | None = None


class AcceptInviteBody(BaseModel):
    first_name: str = ""
    last_name: str = ""
    password: str = ""


def user_to_dict(u: User) -> dict:
    return {
        "id": str(u.id),
        "email": u.email,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "phone": u.phone,
        "is_superadmin": u.is_superadmin,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def org_to_dict(o: Organization) -> dict:
    return {
        "id": str(o.id),
        "name": o.name,
        "status": o.status,
        "credits_balance": o.credits_balance,
        "unlimited_credits": o.unlimited_credits,
        "timezone": o.timezone or DEFAULT_TIMEZONE,
        "lead_finder_enabled": o.lead_finder_enabled is not False,
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }


async def session_payload(db: AsyncSession, user: User) -> dict:
    org, role = await resolve_org(db, user)
    rows = (await db.execute(
        select(Membership, Organization).join(Organization, Organization.id == Membership.org_id)
        .where(Membership.user_id == user.id).order_by(Organization.name)
    )).all()
    return {
        "user": user_to_dict(user),
        "org": org_to_dict(org) if org else None,
        "role": role,
        "impersonating": role == "superadmin",
        "memberships": [{"org_id": str(o.id), "org_name": o.name, "role": m.role} for m, o in rows],
        "auth_provider": "clerk" if settings.clerk_enabled else "password",
    }


async def _find_invite(db: AsyncSession, token: str) -> Invite:
    invite = (await db.execute(select(Invite).where(Invite.token_hash == sha256(token)))).scalar_one_or_none()
    if not invite or invite.accepted_at:
        raise HTTPException(status_code=404, detail="This invite link is invalid or was already used.")
    expires = invite.expires_at if invite.expires_at.tzinfo else invite.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="This invite has expired — ask for a new one.")
    return invite


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response,
                db: Annotated[AsyncSession, Depends(get_db)]):
    if settings.clerk_enabled:
        raise HTTPException(status_code=400, detail="Sign in with Clerk on the sign-in page.")
    user = (await db.execute(select(User).where(User.email == normalize_email(body.email)))).scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong email or password")
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    set_session_cookie(response, request, user)
    log.info("user_login", user_id=str(user.id))
    return await session_payload(db, user)


@router.post("/logout")
async def logout(response: Response):
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
async def me(user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]):
    return await session_payload(db, user)


@router.post("/switch-org")
async def switch_org(body: SwitchOrgBody, user: Annotated[User, Depends(get_current_user)],
                     db: Annotated[AsyncSession, Depends(get_db)]):
    """Work in another organization: one you belong to, or any org for super-admins.
    org_id=null returns a super-admin to their own account."""
    if body.org_id is None:
        user.active_org_id = None
    else:
        member = (await db.execute(select(Membership).where(
            Membership.user_id == user.id, Membership.org_id == body.org_id))).scalar_one_or_none()
        if not member and not user.is_superadmin:
            raise HTTPException(status_code=403, detail="You're not a member of that account.")
        if not await db.get(Organization, body.org_id):
            raise HTTPException(status_code=404, detail="Account not found")
        user.active_org_id = body.org_id
    await db.commit()
    return await session_payload(db, user)


@router.get("/invites/{token}")
async def get_invite(token: str, db: Annotated[AsyncSession, Depends(get_db)]):
    invite = await _find_invite(db, token)
    org = await db.get(Organization, invite.org_id)
    existing = (await db.execute(select(User.id).where(User.email == invite.email))).scalar_one_or_none()
    return {"email": invite.email, "org_name": org.name if org else "", "role": invite.role,
            "existing_user": existing is not None}


@router.post("/invites/{token}/accept")
async def accept_invite(token: str, body: AcceptInviteBody, request: Request, response: Response,
                        db: Annotated[AsyncSession, Depends(get_db)]):
    """New users set their name and password; existing users confirm with their password."""
    invite = await _find_invite(db, token)
    user = (await db.execute(select(User).where(User.email == invite.email))).scalar_one_or_none()
    if user:
        if not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Enter your existing BlackSync password to join.")
    else:
        check_password_strength(body.password)
        if not body.first_name.strip():
            raise HTTPException(status_code=400, detail="Enter your first name.")
        user = User(
            id=uuid.uuid4(), email=invite.email, first_name=body.first_name.strip(),
            last_name=body.last_name.strip(), password_hash=hash_password(body.password),
        )
        db.add(user)
        await db.flush()
    already = (await db.execute(select(Membership).where(
        Membership.user_id == user.id, Membership.org_id == invite.org_id))).scalar_one_or_none()
    if not already:
        db.add(Membership(user_id=user.id, org_id=invite.org_id, role=invite.role))
    user.active_org_id = invite.org_id
    user.last_login_at = datetime.now(timezone.utc)
    invite.accepted_at = datetime.now(timezone.utc)
    await db.commit()
    set_session_cookie(response, request, user)
    log.info("invite_accepted", user_id=str(user.id), org_id=str(invite.org_id))
    return await session_payload(db, user)


@router.post("/invites/{token}/join")
async def join_invite(token: str, user: Annotated[User, Depends(get_current_user)],
                      db: Annotated[AsyncSession, Depends(get_db)]):
    """Signed-in users (e.g. via Clerk) join the invite's account with their current login."""
    invite = await _find_invite(db, token)
    already = (await db.execute(select(Membership).where(
        Membership.user_id == user.id, Membership.org_id == invite.org_id))).scalar_one_or_none()
    if not already:
        db.add(Membership(user_id=user.id, org_id=invite.org_id, role=invite.role))
    user.active_org_id = invite.org_id
    invite.accepted_at = datetime.now(timezone.utc)
    await db.commit()
    log.info("invite_joined", user_id=str(user.id), org_id=str(invite.org_id))
    return await session_payload(db, user)
