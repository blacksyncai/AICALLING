"""
Admin portal (super-admins only) — every sub-account on the platform:
create accounts, add calling credits, manage logins, and open an account
to work inside it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.models.account import CreditTransaction, Membership, Organization, User
from app.models.agent import Agent
from app.models.call_log import CallLog
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.routers.account import create_invite, credit_tx_to_dict, team_payload
from app.routers.auth import org_to_dict, user_to_dict
from app.services.accounts import adjust_credits, create_organization
from app.services.auth import DbDep, SuperadminDep, generate_password, hash_password, normalize_email

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


class OrgCreate(BaseModel):
    name: str
    owner_first_name: str = ""
    owner_last_name: str = ""
    owner_email: str
    owner_phone: str = ""
    # Leave empty to generate one (shown once) — or send an invite link instead.
    password: str = ""
    send_invite: bool = False
    credits: int = Field(default=0, ge=0, le=1_000_000)


class OrgPatch(BaseModel):
    name: str | None = None
    status: str | None = None
    unlimited_credits: bool | None = None


class CreditGrant(BaseModel):
    amount: int = Field(ge=-1_000_000, le=1_000_000)
    note: str = ""


class AdminInvite(BaseModel):
    email: str
    role: str = "member"


async def _org_or_404(db, org_id: uuid.UUID) -> Organization:
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Account not found")
    return org


async def _usage_by_org(db, since: datetime) -> dict:
    rows = (await db.execute(
        select(CallLog.org_id, func.count(), func.coalesce(func.sum(CallLog.duration_seconds), 0),
               func.coalesce(func.sum(CallLog.credits_charged), 0))
        .where(CallLog.started_at >= since).group_by(CallLog.org_id)
    )).all()
    return {r[0]: {"calls": r[1], "minutes": round(int(r[2] or 0) / 60, 1), "credits_used": int(r[3] or 0)}
            for r in rows}


async def _counts(db, column) -> dict:
    rows = (await db.execute(select(column, func.count()).group_by(column))).all()
    return {r[0]: r[1] for r in rows}


@router.get("/overview")
async def platform_overview(_: SuperadminDep, db: DbDep):
    since = datetime.now(timezone.utc) - timedelta(days=30)
    orgs = (await db.execute(select(func.count()).select_from(Organization))).scalar_one()
    users = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    calls, seconds = (await db.execute(
        select(func.count(), func.coalesce(func.sum(CallLog.duration_seconds), 0)).where(CallLog.started_at >= since)
    )).one()
    used = (await db.execute(select(func.coalesce(func.sum(-CreditTransaction.amount), 0)).where(
        CreditTransaction.kind == "usage", CreditTransaction.created_at >= since))).scalar_one()
    outstanding = (await db.execute(select(func.coalesce(func.sum(Organization.credits_balance), 0)).where(
        Organization.unlimited_credits.is_(False)))).scalar_one()
    return {"accounts": orgs, "users": users, "calls_30d": calls, "minutes_30d": round(int(seconds or 0) / 60, 1),
            "credits_used_30d": int(used or 0), "credits_outstanding": int(outstanding or 0)}


@router.get("/orgs")
async def list_orgs(_: SuperadminDep, db: DbDep, q: str = ""):
    stmt = select(Organization).order_by(Organization.created_at.desc())
    if q.strip():
        stmt = stmt.where(Organization.name.ilike(f"%{q.strip()}%"))
    orgs = (await db.execute(stmt)).scalars().all()
    usage = await _usage_by_org(db, datetime.now(timezone.utc) - timedelta(days=30))
    members = await _counts(db, Membership.org_id)
    agents = await _counts(db, Agent.org_id)
    leads = await _counts(db, Lead.org_id)
    owners = {
        m.org_id: u for m, u in (await db.execute(
            select(Membership, User).join(User, User.id == Membership.user_id)
            .where(Membership.role == "owner").order_by(Membership.created_at.desc())
        )).all()
    }
    out = []
    for o in orgs:
        owner = owners.get(o.id)
        out.append({
            **org_to_dict(o),
            "owner": {"name": owner.full_name, "email": owner.email} if owner else None,
            "members": members.get(o.id, 0),
            "agents": agents.get(o.id, 0),
            "contacts": leads.get(o.id, 0),
            "usage_30d": usage.get(o.id, {"calls": 0, "minutes": 0, "credits_used": 0}),
        })
    return {"orgs": out}


@router.post("/orgs", status_code=201)
async def create_org(body: OrgCreate, request: Request, admin: SuperadminDep, db: DbDep):
    """New sub-account with its owner login. The owner either gets a password (generated
    if not given, returned once) or an invite link to set their own."""
    email = normalize_email(body.owner_email)
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid owner email.")
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Enter the company name.")
    if body.password and len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    org = await create_organization(db, body.name, credits=body.credits, created_by=admin.id)
    result: dict = {}
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing:
        db.add(Membership(user_id=existing.id, org_id=org.id, role="owner"))
        await db.commit()
        result["owner_status"] = "existing_user_added"
    elif body.send_invite:
        await db.commit()
        invite = await create_invite(db, request, org, admin, email, "owner")
        result.update(owner_status="invited", invite_url=invite["invite_url"], emailed=invite["emailed"])
    else:
        password = body.password or generate_password()
        owner = User(
            id=uuid.uuid4(), email=email, first_name=body.owner_first_name.strip(),
            last_name=body.owner_last_name.strip(), phone=body.owner_phone.strip(),
            password_hash=hash_password(password), active_org_id=org.id,
        )
        db.add(owner)
        await db.flush()
        db.add(Membership(user_id=owner.id, org_id=org.id, role="owner"))
        await db.commit()
        result.update(owner_status="created", temporary_password=None if body.password else password)
    log.info("admin_created_org", org_id=str(org.id), by=str(admin.id))
    await db.refresh(org)
    return {**org_to_dict(org), **result, "login_email": email}


@router.get("/orgs/{org_id}")
async def get_org(org_id: uuid.UUID, _: SuperadminDep, db: DbDep):
    org = await _org_or_404(db, org_id)
    since = datetime.now(timezone.utc) - timedelta(days=30)
    usage = (await _usage_by_org(db, since)).get(org.id, {"calls": 0, "minutes": 0, "credits_used": 0})
    all_time = (await db.execute(select(func.count(), func.coalesce(func.sum(CallLog.duration_seconds), 0))
                                 .where(CallLog.org_id == org.id))).one()
    ledger = (await db.execute(
        select(CreditTransaction).where(CreditTransaction.org_id == org.id)
        .order_by(CreditTransaction.created_at.desc()).limit(100)
    )).scalars().all()
    count = lambda model: select(func.count()).select_from(model).where(model.org_id == org.id)  # noqa: E731
    return {
        **org_to_dict(org),
        **(await team_payload(db, org.id)),
        "usage_30d": usage,
        "all_time": {"calls": all_time[0], "minutes": round(int(all_time[1] or 0) / 60, 1)},
        "agents": (await db.execute(count(Agent))).scalar_one(),
        "campaigns": (await db.execute(count(Campaign))).scalar_one(),
        "contacts": (await db.execute(count(Lead))).scalar_one(),
        "transactions": [credit_tx_to_dict(t) for t in ledger],
    }


@router.patch("/orgs/{org_id}")
async def update_org(org_id: uuid.UUID, body: OrgPatch, _: SuperadminDep, db: DbDep):
    org = await _org_or_404(db, org_id)
    if body.name is not None and body.name.strip():
        org.name = body.name.strip()[:255]
    if body.status is not None:
        if body.status not in ("active", "suspended"):
            raise HTTPException(status_code=400, detail="Status must be active or suspended.")
        org.status = body.status
    if body.unlimited_credits is not None:
        org.unlimited_credits = body.unlimited_credits
    await db.commit()
    return org_to_dict(org)


@router.post("/orgs/{org_id}/credits")
async def grant_credits(org_id: uuid.UUID, body: CreditGrant, admin: SuperadminDep, db: DbDep):
    """Add (or with a negative amount, remove) calling credits."""
    if body.amount == 0:
        raise HTTPException(status_code=400, detail="Enter a non-zero amount.")
    org = await _org_or_404(db, org_id)
    tx = await adjust_credits(db, org, body.amount, kind="grant" if body.amount > 0 else "adjustment",
                              note=body.note.strip() or ("Credits added" if body.amount > 0 else "Credits removed"),
                              created_by=admin.id)
    await db.commit()
    log.info("admin_credits", org_id=str(org.id), amount=body.amount, by=str(admin.id))
    return {"balance": org.credits_balance, "transaction": credit_tx_to_dict(tx)}


@router.post("/orgs/{org_id}/invites", status_code=201)
async def invite_to_org(org_id: uuid.UUID, body: AdminInvite, request: Request, admin: SuperadminDep, db: DbDep):
    org = await _org_or_404(db, org_id)
    return await create_invite(db, request, org, admin, body.email, body.role)


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: uuid.UUID, admin: SuperadminDep, db: DbDep):
    """Set a new random password (returned once) and sign the user out everywhere."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    password = generate_password()
    user.password_hash = hash_password(password)
    user.session_version += 1
    await db.commit()
    log.info("admin_reset_password", user_id=str(user.id), by=str(admin.id))
    return {"email": user.email, "temporary_password": password}


@router.get("/users")
async def list_users(_: SuperadminDep, db: DbDep):
    rows = (await db.execute(
        select(User, Membership, Organization)
        .outerjoin(Membership, Membership.user_id == User.id)
        .outerjoin(Organization, Organization.id == Membership.org_id)
        .order_by(User.created_at.desc())
    )).all()
    users: dict = {}
    for u, m, o in rows:
        entry = users.setdefault(u.id, {**user_to_dict(u), "last_login_at": u.last_login_at.isoformat()
                                        if u.last_login_at else None, "accounts": []})
        if m and o:
            entry["accounts"].append({"org_id": str(o.id), "org_name": o.name, "role": m.role})
    return {"users": list(users.values())}
