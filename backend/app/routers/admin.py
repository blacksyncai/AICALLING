"""
Admin portal (super-admins only) — every sub-account on the platform:
create accounts, add calling credits, manage logins, and open an account
to work inside it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.models.account import CreditTransaction, Membership, Organization, User
from app.models.agent import Agent
from app.models.call_log import CallLog
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.routers.account import create_invite, credit_tx_to_dict, team_payload
from app.routers.auth import org_to_dict, user_to_dict
from app.config import settings
from app.services import clerk
from app.services.accounts import adjust_credits, create_organization
from app.services.auth import (
    ADMIN_COOKIE, ADMIN_TTL_S, AdminDep, DbDep, SuperadminDep, admin_unlocked, check_admin_password,
    create_admin_token, generate_password, hash_password, normalize_email,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


class UnlockBody(BaseModel):
    password: str


@router.get("/lock")
async def lock_status(request: Request, user: SuperadminDep):
    return {"unlocked": admin_unlocked(request, user)}


@router.post("/unlock")
async def unlock(body: UnlockBody, request: Request, response: Response, user: SuperadminDep):
    """Platform admins enter the admin password to open the portal on this browser."""
    check_admin_password(user, body.password)
    https = (request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
             or request.headers.get("origin", "").startswith("https://"))
    response.set_cookie(ADMIN_COOKIE, create_admin_token(user), max_age=ADMIN_TTL_S, httponly=True,
                        samesite="strict", secure=https, path="/")
    log.info("admin_unlocked", user_id=str(user.id))
    return {"unlocked": True}


@router.post("/lock")
async def lock(response: Response):
    response.delete_cookie(ADMIN_COOKIE, path="/")
    return {"unlocked": False}


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
    # Lead Finder: daily lookups for this account (-1 = back to the platform default) and on/off.
    lead_finder_daily_limit: int | None = Field(default=None, ge=-1, le=10000)
    lead_finder_enabled: bool | None = None


class CreditGrant(BaseModel):
    amount: int = Field(ge=-1_000_000, le=1_000_000)
    note: str = ""


class AdminInvite(BaseModel):
    email: str
    role: str = "member"


async def _clerk_login(email: str, password: str, first: str, last: str,
                       reset_existing: bool = False) -> tuple[str, bool]:
    """A Clerk login for this email: created with the password, or the existing one (whose
    password is only replaced when resetting). Returns (clerk user id, created)."""
    try:
        existing = await clerk.find_user_by_email(email)
        if existing:
            if reset_existing:
                await clerk.set_password(existing["id"], password)
            return existing["id"], reset_existing
        created = await clerk.create_user(email, password, first, last)
        return created["id"], True
    except clerk.ClerkError as exc:
        raise HTTPException(status_code=502, detail=f"Clerk: {exc}")


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
async def platform_overview(_: AdminDep, db: DbDep):
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
async def list_orgs(_: AdminDep, db: DbDep, q: str = ""):
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
async def create_org(body: OrgCreate, request: Request, admin: AdminDep, db: DbDep):
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
        clerk_id, clerk_created = None, True
        if settings.clerk_enabled:
            # The owner signs in through Clerk, so their login (and password) lives there.
            clerk_id, clerk_created = await _clerk_login(email, password, body.owner_first_name.strip(),
                                                         body.owner_last_name.strip())
        owner = User(
            id=uuid.uuid4(), email=email, first_name=body.owner_first_name.strip(),
            last_name=body.owner_last_name.strip(), phone=body.owner_phone.strip(),
            password_hash="" if settings.clerk_enabled else hash_password(password),
            clerk_user_id=clerk_id, active_org_id=org.id,
        )
        db.add(owner)
        await db.flush()
        db.add(Membership(user_id=owner.id, org_id=org.id, role="owner"))
        await db.commit()
        if clerk_created:
            result.update(owner_status="created", temporary_password=None if body.password else password)
        else:
            result["owner_status"] = "existing_user_added"
    log.info("admin_created_org", org_id=str(org.id), by=str(admin.id))
    await db.refresh(org)
    return {**org_to_dict(org), **result, "login_email": email}


@router.get("/orgs/{org_id}")
async def get_org(org_id: uuid.UUID, _: AdminDep, db: DbDep):
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
async def update_org(org_id: uuid.UUID, body: OrgPatch, _: AdminDep, db: DbDep):
    org = await _org_or_404(db, org_id)
    if body.name is not None and body.name.strip():
        org.name = body.name.strip()[:255]
    if body.status is not None:
        if body.status not in ("active", "suspended"):
            raise HTTPException(status_code=400, detail="Status must be active or suspended.")
        org.status = body.status
    if body.unlimited_credits is not None:
        org.unlimited_credits = body.unlimited_credits
    if body.lead_finder_daily_limit is not None:
        org.lead_finder_daily_limit = None if body.lead_finder_daily_limit < 0 else body.lead_finder_daily_limit
    if body.lead_finder_enabled is not None:
        org.lead_finder_enabled = body.lead_finder_enabled
    await db.commit()
    return org_to_dict(org)


@router.post("/orgs/{org_id}/credits")
async def grant_credits(org_id: uuid.UUID, body: CreditGrant, admin: AdminDep, db: DbDep):
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
async def invite_to_org(org_id: uuid.UUID, body: AdminInvite, request: Request, admin: AdminDep, db: DbDep):
    org = await _org_or_404(db, org_id)
    return await create_invite(db, request, org, admin, body.email, body.role)


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: uuid.UUID, admin: AdminDep, db: DbDep):
    """Set a new random password (returned once) and sign the user out everywhere."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    password = generate_password()
    if settings.clerk_enabled:
        if user.clerk_user_id:
            try:
                await clerk.set_password(user.clerk_user_id, password)
            except clerk.ClerkError as exc:
                raise HTTPException(status_code=502, detail=f"Clerk: {exc}")
        else:
            user.clerk_user_id, _ = await _clerk_login(user.email, password, user.first_name, user.last_name,
                                                       reset_existing=True)
    else:
        user.password_hash = hash_password(password)
    user.session_version += 1
    await db.commit()
    log.info("admin_reset_password", user_id=str(user.id), by=str(admin.id))
    return {"email": user.email, "temporary_password": password}


@router.get("/users")
async def list_users(_: AdminDep, db: DbDep):
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


# ── Internal Agent Playbook Library ───────────────────────────────────────────
# Reference scripts that teach the agent generator what "production quality" means.
# Admin-only: customers never see them, and the generator only reads the pattern card.


class PlaybookPatch(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    tags: dict | None = None
    active: bool | None = None
    # Roll back (or forward) to an existing version.
    current_version: int | None = Field(default=None, ge=1)


class PlaybookVersionCreate(BaseModel):
    patterns: str = Field(min_length=50, max_length=30000)
    private_terms: list[str] = Field(default_factory=list, max_length=100)
    # Defaults to the current version's original script.
    original_text: str | None = Field(default=None, max_length=200000)
    note: str = Field(default="", max_length=500)


class PlaybookCreate(PlaybookVersionCreate):
    slug: str = Field(pattern=r"^[a-z][a-z0-9_]{2,79}$")
    title: str = Field(min_length=2, max_length=255)
    tags: dict = Field(default_factory=dict)


_TAG_KEYS = ("verticals", "directions", "goals", "styles")


def _clean_tags(tags: dict) -> dict:
    out = {}
    for k in _TAG_KEYS:
        vals = tags.get(k) or []
        if not isinstance(vals, list):
            raise HTTPException(status_code=400, detail=f"tags.{k} must be a list")
        out[k] = sorted({str(v).strip().lower()[:40] for v in vals if str(v).strip()})[:30]
    return out


def _version_dict(v, full: bool = False) -> dict:
    d = {"version": v.version, "note": v.note, "private_terms": v.private_terms or [],
         "created_at": v.created_at.isoformat() if v.created_at else None,
         "original_chars": len(v.original_text or ""), "pattern_chars": len(v.patterns or "")}
    if full:
        d.update(original_text=v.original_text, patterns=v.patterns)
    return d


async def _playbook(db, playbook_id: uuid.UUID):
    from app.models.playbook import Playbook

    pb = await db.get(Playbook, playbook_id)
    if not pb:
        raise HTTPException(status_code=404, detail="Playbook not found")
    return pb


async def _playbook_payload(db, pb) -> dict:
    from app.models.playbook import PlaybookVersion

    versions = (await db.execute(select(PlaybookVersion).where(PlaybookVersion.playbook_id == pb.id)
                                 .order_by(PlaybookVersion.version.desc()))).scalars().all()
    current = next((v for v in versions if v.version == pb.current_version), None)
    return {"id": str(pb.id), "slug": pb.slug, "title": pb.title, "tags": pb.tags or {}, "active": pb.active,
            "current_version": pb.current_version, "updated_at": pb.updated_at.isoformat() if pb.updated_at else None,
            "current": _version_dict(current, full=True) if current else None,
            "versions": [_version_dict(v) for v in versions]}


@router.get("/playbooks")
async def list_playbooks(_: AdminDep, db: DbDep):
    from app.models.playbook import Playbook

    rows = (await db.execute(select(Playbook).order_by(Playbook.title))).scalars().all()
    return {"playbooks": [{"id": str(p.id), "slug": p.slug, "title": p.title, "tags": p.tags or {},
                           "active": p.active, "current_version": p.current_version} for p in rows]}


@router.get("/playbooks/{playbook_id}")
async def get_playbook(playbook_id: uuid.UUID, _: AdminDep, db: DbDep):
    return await _playbook_payload(db, await _playbook(db, playbook_id))


@router.get("/playbooks/{playbook_id}/versions/{version}")
async def get_playbook_version(playbook_id: uuid.UUID, version: int, _: AdminDep, db: DbDep):
    from app.models.playbook import PlaybookVersion

    pb = await _playbook(db, playbook_id)
    v = (await db.execute(select(PlaybookVersion).where(PlaybookVersion.playbook_id == pb.id,
                                                        PlaybookVersion.version == version))).scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    return _version_dict(v, full=True)


@router.patch("/playbooks/{playbook_id}")
async def update_playbook(playbook_id: uuid.UUID, body: PlaybookPatch, admin: AdminDep, db: DbDep):
    from app.models.playbook import PlaybookVersion

    pb = await _playbook(db, playbook_id)
    if body.title is not None:
        pb.title = body.title.strip() or pb.title
    if body.tags is not None:
        pb.tags = _clean_tags(body.tags)
    if body.active is not None:
        pb.active = body.active
    if body.current_version is not None:
        exists = (await db.execute(select(PlaybookVersion.id).where(
            PlaybookVersion.playbook_id == pb.id, PlaybookVersion.version == body.current_version))).first()
        if not exists:
            raise HTTPException(status_code=404, detail="Version not found")
        pb.current_version = body.current_version
    await db.commit()
    log.info("playbook_updated", playbook=pb.slug, by=str(admin.id))
    return await _playbook_payload(db, pb)


async def _add_version(db, pb, body: PlaybookVersionCreate, user_id, original_fallback: str) -> None:
    from app.models.playbook import PlaybookVersion

    last = (await db.execute(select(func.max(PlaybookVersion.version)).where(
        PlaybookVersion.playbook_id == pb.id))).scalar_one() or 0
    terms = sorted({t.strip() for t in body.private_terms if t and t.strip()})
    db.add(PlaybookVersion(playbook_id=pb.id, version=last + 1, original_text=body.original_text or original_fallback,
                           patterns=body.patterns.strip(), private_terms=terms, note=body.note.strip(),
                           created_by=user_id))
    pb.current_version = last + 1


@router.post("/playbooks/{playbook_id}/versions", status_code=201)
async def add_playbook_version(playbook_id: uuid.UUID, body: PlaybookVersionCreate, admin: AdminDep, db: DbDep):
    """Save edited patterns / private terms as a new version (older versions stay in the history)."""
    from app.models.playbook import PlaybookVersion

    pb = await _playbook(db, playbook_id)
    current = (await db.execute(select(PlaybookVersion).where(
        PlaybookVersion.playbook_id == pb.id, PlaybookVersion.version == pb.current_version))).scalar_one_or_none()
    await _add_version(db, pb, body, admin.id, current.original_text if current else "")
    await db.commit()
    log.info("playbook_version_added", playbook=pb.slug, version=pb.current_version, by=str(admin.id))
    return await _playbook_payload(db, pb)


@router.post("/playbooks", status_code=201)
async def create_playbook(body: PlaybookCreate, admin: AdminDep, db: DbDep):
    from app.models.playbook import Playbook

    if (await db.execute(select(Playbook.id).where(Playbook.slug == body.slug))).first():
        raise HTTPException(status_code=409, detail="A playbook with that slug already exists.")
    if not (body.original_text or "").strip():
        raise HTTPException(status_code=400, detail="Paste the original script.")
    pb = Playbook(slug=body.slug, title=body.title.strip(), tags=_clean_tags(body.tags), active=True, current_version=0)
    db.add(pb)
    await db.flush()
    await _add_version(db, pb, body, admin.id, "")
    await db.commit()
    log.info("playbook_created", playbook=pb.slug, by=str(admin.id))
    return await _playbook_payload(db, pb)



# ── Lead Finder usage ─────────────────────────────────────────────────────────


@router.get("/orgs/{org_id}/lead-finder")
async def org_lead_finder(org_id: uuid.UUID, _: AdminDep, db: DbDep):
    """Usage, matches, provider cost and recent errors for one account. No contact details."""
    from app.models.lead_finder import PropertyLookup
    from app.services import lead_finder as lf

    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Account not found")
    since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    rows = (await db.execute(select(PropertyLookup.status, PropertyLookup.found, PropertyLookup.charged,
                                    PropertyLookup.lookup_date).where(
        PropertyLookup.org_id == org.id, PropertyLookup.lookup_date >= since))).all()
    done = [r for r in rows if r.status == "completed"]
    errors = (await db.execute(select(PropertyLookup.error_code, PropertyLookup.error, PropertyLookup.created_at).where(
        PropertyLookup.org_id == org.id, PropertyLookup.status == "failed",
    ).order_by(PropertyLookup.created_at.desc()).limit(10))).all()
    return {
        "enabled": lf.enabled(org),
        "daily_limit": lf.daily_limit(org),
        "limit_is_default": org.lead_finder_daily_limit is None,
        "default_limit": settings.lead_finder_daily_limit,
        "used_today": await lf.used_today(db, org.id),
        "last_30_days": {"lookups": len(done), "matches": sum(1 for r in done if r.found),
                         "cost": round(sum(r.charged or 0 for r in done), 2),
                         "failed": sum(1 for r in rows if r.status == "failed")},
        "recent_errors": [{"code": e.error_code, "message": e.error,
                           "at": e.created_at.isoformat() if e.created_at else None} for e in errors],
    }
