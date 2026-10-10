"""
Account router — the signed-in user's profile and password, and their
organization: name, team members, invites and credit history.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select

from app.config import settings
from app.models.account import ROLES, CreditTransaction, Invite, Membership, User
from app.routers.auth import org_to_dict, user_to_dict
from app.services.auth import (
    CtxDep, DbDep, ManagerDep, check_password_strength, hash_password, normalize_email, set_session_cookie, sha256,
    verify_password,
)
from app.services.email import email_enabled, send_invite_email

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/account", tags=["account"])

INVITE_TTL = timedelta(days=7)


class ProfileUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class OrgUpdate(BaseModel):
    name: str


class InviteCreate(BaseModel):
    email: str
    role: str = "member"


class MemberUpdate(BaseModel):
    role: str


def app_base_url(request: Request) -> str:
    if settings.app_url:
        return settings.app_url.rstrip("/")
    origin = request.headers.get("origin")
    if origin:
        return origin.rstrip("/")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost:3000")
    proto = request.headers.get("x-forwarded-proto", "http")
    return f"{proto}://{host}"


def _iso(d: datetime | None) -> str | None:
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()


async def create_invite(db, request: Request, org, inviter: User, email: str, role: str) -> dict:
    """Shared by the team page and the admin portal. Returns the invite with its link."""
    email = normalize_email(email)
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if role not in ROLES:
        raise HTTPException(status_code=400, detail=f"Role must be one of {', '.join(ROLES)}.")
    member = (await db.execute(
        select(Membership).join(User, User.id == Membership.user_id)
        .where(Membership.org_id == org.id, User.email == email)
    )).scalar_one_or_none()
    if member:
        raise HTTPException(status_code=409, detail=f"{email} is already on this team.")
    # One open invite per email — re-inviting replaces the old link.
    for old in (await db.execute(select(Invite).where(
            Invite.org_id == org.id, Invite.email == email, Invite.accepted_at.is_(None)))).scalars():
        await db.delete(old)
    token = secrets.token_urlsafe(24)
    invite = Invite(
        id=uuid.uuid4(), org_id=org.id, email=email, role=role, token_hash=sha256(token),
        invited_by=inviter.id, expires_at=datetime.now(timezone.utc) + INVITE_TTL,
    )
    db.add(invite)
    await db.commit()
    link = f"{app_base_url(request)}/invite/{token}"
    emailed = await send_invite_email(email, org.name, inviter.full_name or inviter.email, link)
    log.info("invite_created", org_id=str(org.id), emailed=emailed)
    return {**_invite_to_dict(invite), "invite_url": link, "emailed": emailed}


def _invite_to_dict(i: Invite) -> dict:
    return {"id": str(i.id), "email": i.email, "role": i.role, "expires_at": _iso(i.expires_at),
            "created_at": _iso(i.created_at)}


async def team_payload(db, org_id: uuid.UUID) -> dict:
    members = (await db.execute(
        select(Membership, User).join(User, User.id == Membership.user_id)
        .where(Membership.org_id == org_id).order_by(Membership.created_at)
    )).all()
    invites = (await db.execute(
        select(Invite).where(Invite.org_id == org_id, Invite.accepted_at.is_(None)).order_by(Invite.created_at.desc())
    )).scalars().all()
    return {
        "members": [{**user_to_dict(u), "membership_id": str(m.id), "role": m.role,
                     "last_login_at": _iso(u.last_login_at), "joined_at": _iso(m.created_at)} for m, u in members],
        "invites": [_invite_to_dict(i) for i in invites],
        "email_enabled": email_enabled(),
    }


# ── Profile ───────────────────────────────────────────────────────────────────


@router.patch("/profile")
async def update_profile(body: ProfileUpdate, ctx: CtxDep, db: DbDep):
    user = ctx.user
    data = body.model_dump(exclude_unset=True)
    if settings.clerk_enabled and data.get("email") and normalize_email(data["email"]) != user.email:
        raise HTTPException(status_code=400, detail="Change your sign-in email under Security (managed by Clerk).")
    if "email" in data and data["email"] is not None:
        email = normalize_email(data["email"])
        if "@" not in email:
            raise HTTPException(status_code=400, detail="Enter a valid email address.")
        taken = (await db.execute(select(User.id).where(User.email == email, User.id != user.id))).first()
        if taken:
            raise HTTPException(status_code=409, detail="That email is already used by another login.")
        user.email = email
    for key in ("first_name", "last_name", "phone"):
        if data.get(key) is not None:
            setattr(user, key, data[key].strip())
    await db.commit()
    return user_to_dict(user)


@router.post("/password")
async def change_password(body: PasswordChange, request: Request, response: Response, ctx: CtxDep, db: DbDep):
    if settings.clerk_enabled:
        raise HTTPException(status_code=400, detail="Passwords are managed by Clerk — use Security to change yours.")
    if not verify_password(body.current_password, ctx.user.password_hash):
        raise HTTPException(status_code=400, detail="Your current password is incorrect.")
    check_password_strength(body.new_password)
    user = ctx.user
    user.password_hash = hash_password(body.new_password)
    user.session_version += 1  # signs out every other device
    await db.commit()
    set_session_cookie(response, request, user)
    return {"ok": True}


# ── Organization & team ───────────────────────────────────────────────────────


@router.get("/org")
async def get_org(ctx: CtxDep, db: DbDep):
    return {**org_to_dict(ctx.org), "role": ctx.role, "can_manage": ctx.can_manage,
            **(await team_payload(db, ctx.org.id))}


@router.patch("/org")
async def rename_org(body: OrgUpdate, ctx: ManagerDep, db: DbDep):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Company name can't be empty.")
    org = ctx.org
    org.name = name[:255]
    await db.commit()
    return org_to_dict(org)


@router.post("/org/invites", status_code=201)
async def invite_member(body: InviteCreate, request: Request, ctx: ManagerDep, db: DbDep):
    if body.role == "owner" and ctx.role not in ("owner", "superadmin"):
        raise HTTPException(status_code=403, detail="Only owners can invite another owner.")
    return await create_invite(db, request, ctx.org, ctx.user, body.email, body.role)


@router.delete("/org/invites/{invite_id}", status_code=204)
async def revoke_invite(invite_id: uuid.UUID, ctx: ManagerDep, db: DbDep):
    invite = await db.get(Invite, invite_id)
    if not invite or invite.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Invite not found")
    await db.delete(invite)
    await db.commit()


async def _owner_count(db, org_id) -> int:
    return (await db.execute(select(func.count()).select_from(Membership).where(
        Membership.org_id == org_id, Membership.role == "owner"))).scalar_one()


@router.patch("/org/members/{membership_id}")
async def change_member_role(membership_id: uuid.UUID, body: MemberUpdate, ctx: ManagerDep, db: DbDep):
    if body.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"Role must be one of {', '.join(ROLES)}.")
    m = await db.get(Membership, membership_id)
    if not m or m.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Member not found")
    if (m.role == "owner" or body.role == "owner") and ctx.role not in ("owner", "superadmin"):
        raise HTTPException(status_code=403, detail="Only owners can change who owns the account.")
    if m.role == "owner" and body.role != "owner" and await _owner_count(db, ctx.org.id) <= 1:
        raise HTTPException(status_code=400, detail="An account needs at least one owner.")
    m.role = body.role
    await db.commit()
    return {"ok": True}


@router.delete("/org/members/{membership_id}", status_code=204)
async def remove_member(membership_id: uuid.UUID, ctx: ManagerDep, db: DbDep):
    m = await db.get(Membership, membership_id)
    if not m or m.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Member not found")
    if m.role == "owner" and ctx.role not in ("owner", "superadmin"):
        raise HTTPException(status_code=403, detail="Only owners can remove an owner.")
    if m.role == "owner" and await _owner_count(db, ctx.org.id) <= 1:
        raise HTTPException(status_code=400, detail="An account needs at least one owner.")
    await db.delete(m)
    await db.commit()


# ── Credits ───────────────────────────────────────────────────────────────────


@router.get("/credits")
async def credit_history(ctx: CtxDep, db: DbDep, limit: int = 50):
    rows = (await db.execute(
        select(CreditTransaction).where(CreditTransaction.org_id == ctx.org.id)
        .order_by(CreditTransaction.created_at.desc()).limit(min(limit, 200))
    )).scalars().all()
    return {
        "balance": ctx.org.credits_balance,
        "unlimited": ctx.org.unlimited_credits,
        "transactions": [credit_tx_to_dict(t) for t in rows],
    }


def credit_tx_to_dict(t: CreditTransaction) -> dict:
    return {"id": str(t.id), "amount": t.amount, "balance_after": t.balance_after, "kind": t.kind,
            "note": t.note, "call_id": str(t.call_id) if t.call_id else None, "created_at": _iso(t.created_at)}
