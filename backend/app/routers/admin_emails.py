"""
Admin → Emails: send our customer emails by hand — e.g. to people who signed up before email was set up.

Each kind is tracked per user (welcome_email_at, catchup_email_at, followup_email_at), so the page shows
who already got it and a send skips them unless the admin explicitly chooses to resend.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.models.account import Membership, Organization, User
from app.services.auth import AdminDep, DbDep

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/admin/emails", tags=["admin"])

KINDS = {
    "welcome": {"name": "Welcome", "field": "welcome_email_at",
                "description": "Workspace ready, three steps to get going, and the setup-call link. Normally sent at sign-up."},
    "catchup": {"name": "Workspace waiting", "field": "catchup_email_at",
                "description": "For people who signed up a while ago: pick up where you left off, plus the setup-call link."},
    "walkthrough": {"name": "Walkthrough offer", "field": "followup_email_at",
                    "description": "Offer of a free walkthrough call. Normally sent a day after the welcome email."},
}


async def _org_for(db, user: User) -> Organization | None:
    if user.active_org_id:
        org = await db.get(Organization, user.active_org_id)
        if org:
            return org
    m = (await db.execute(select(Membership).where(Membership.user_id == user.id).limit(1))).scalar_one_or_none()
    return await db.get(Organization, m.org_id) if m else None


async def _render(db, kind: str, user: User) -> tuple[str, str]:
    from app.agent import catalog
    from app.services import onboarding_emails as oe
    from app.services.billing import settings_store

    org = await _org_for(db, user)
    org_name = org.name if org else "your business"
    industry = (catalog.industry_label(org.industry or "") or None) if org else None
    if kind == "welcome":
        return oe.welcome_email(user, org_name, industry, await settings_store.get(db, "expert_booking_url"))
    if kind == "catchup":
        return oe.catchup_email(user, org_name, industry, await settings_store.get(db, "expert_booking_url"))
    booking = (await settings_store.get(db, "onboarding_booking_url")) or (await settings_store.get(db, "expert_booking_url"))
    return oe.followup_email(user, booking or "")


def _iso(d: datetime | None) -> str | None:
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()


@router.get("")
async def overview(_: AdminDep, db: DbDep):
    from app.services.email import email_enabled

    users = (await db.execute(select(User).order_by(User.created_at.desc()).limit(1000))).scalars().all()
    orgs = {o.id: o.name for o in (await db.execute(select(Organization))).scalars().all()}
    first_org = {}
    for m in (await db.execute(select(Membership))).scalars().all():
        first_org.setdefault(m.user_id, m.org_id)
    return {
        "email_enabled": email_enabled(),
        "kinds": [{"key": k, "name": v["name"], "description": v["description"]} for k, v in KINDS.items()],
        "users": [{
            "id": str(u.id), "email": u.email, "name": f"{u.first_name} {u.last_name}".strip(),
            "account": orgs.get(u.active_org_id or first_org.get(u.id)), "signed_up": _iso(u.created_at),
            "last_login": _iso(u.last_login_at), "superadmin": bool(u.is_superadmin),
            "sent": {k: _iso(getattr(u, v["field"])) for k, v in KINDS.items()},
        } for u in users],
    }


@router.get("/preview")
async def preview(kind: str, user_id: uuid.UUID, _: AdminDep, db: DbDep):
    if kind not in KINDS:
        raise HTTPException(status_code=404, detail="Unknown email")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    subject, html = await _render(db, kind, user)
    return {"subject": subject, "html": html, "to": user.email}


class SendBody(BaseModel):
    kind: str
    user_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    resend: bool = False  # also send to people who already got this one


@router.post("/send")
async def send(body: SendBody, admin: AdminDep, db: DbDep):
    from app.services.email import email_enabled, send_email

    if body.kind not in KINDS:
        raise HTTPException(status_code=404, detail="Unknown email")
    if not email_enabled():
        raise HTTPException(status_code=409, detail="Email isn't set up (RESEND_API_KEY).")
    field = KINDS[body.kind]["field"]
    sent, skipped, failed = [], [], []
    for uid in dict.fromkeys(body.user_ids):
        user = await db.get(User, uid)
        if not user:
            continue
        if getattr(user, field) and not body.resend:
            skipped.append(user.email)
            continue
        subject, html = await _render(db, body.kind, user)
        if await send_email(user.email, subject, html):
            setattr(user, field, datetime.now(timezone.utc))
            await db.commit()
            sent.append(user.email)
        else:
            failed.append(user.email)
    log.info("admin_emails_sent", kind=body.kind, by=str(admin.id), sent=len(sent), skipped=len(skipped),
             failed=len(failed))
    return {"sent": sent, "skipped": skipped, "failed": failed}
