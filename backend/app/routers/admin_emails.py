"""
Admin → Emails: send our customer emails by hand — e.g. to people who signed up before email was set up.

Each kind is tracked per user (welcome_email_at, catchup_email_at, followup_email_at), so the page shows
who already got it and a send skips them unless the admin explicitly chooses to resend.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

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


def _track(m) -> dict:
    """What happened to one sent email (from Resend's webhook events)."""
    return {"status": m.status, "sent_at": _iso(m.sent_at), "delivered_at": _iso(m.delivered_at),
            "opened_at": _iso(m.opened_at), "open_count": m.open_count, "clicked_at": _iso(m.clicked_at),
            "click_count": m.click_count, "bounced_at": _iso(m.bounced_at), "complained_at": _iso(m.complained_at)}


async def _latest_status(db, emails: list[str], kinds: list[str]) -> dict:
    """{(email, kind): tracking} for the most recent message of each kind to each address."""
    from app.models.email_message import EmailMessage

    emails = [e.lower() for e in emails if e]
    if not emails:
        return {}
    rows = (await db.execute(select(EmailMessage).where(EmailMessage.to_email.in_(emails), EmailMessage.kind.in_(kinds))
                             .order_by(EmailMessage.sent_at))).scalars().all()
    return {(m.to_email, m.kind): _track(m) for m in rows}  # later rows overwrite earlier ones


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
    tracked = await _latest_status(db, [u.email for u in users], list(KINDS))
    return {
        "email_enabled": email_enabled(),
        "kinds": [{"key": k, "name": v["name"], "description": v["description"]} for k, v in KINDS.items()],
        "users": [{
            "id": str(u.id), "email": u.email, "name": f"{u.first_name} {u.last_name}".strip(),
            "account": orgs.get(u.active_org_id or first_org.get(u.id)), "signed_up": _iso(u.created_at),
            "last_login": _iso(u.last_login_at), "superadmin": bool(u.is_superadmin),
            "sent": {k: _iso(getattr(u, v["field"])) for k, v in KINDS.items()},
            "tracking": {k: tracked[(u.email.lower(), k)] for k in KINDS if (u.email.lower(), k) in tracked},
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
        if await send_email(user.email, subject, html, kind=body.kind):
            setattr(user, field, datetime.now(timezone.utc))
            await db.commit()
            sent.append(user.email)
        else:
            failed.append(user.email)
    log.info("admin_emails_sent", kind=body.kind, by=str(admin.id), sent=len(sent), skipped=len(skipped),
             failed=len(failed))
    return {"sent": sent, "skipped": skipped, "failed": failed}


# ── Invites: email people who don't have an account yet ─────────────────────────


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Invitee(BaseModel):
    first_name: str = Field(default="", max_length=100)
    email: str = Field(max_length=320)


class InviteBody(BaseModel):
    people: list[Invitee] = Field(min_length=1, max_length=200)
    inviter: str = Field(default="", max_length=100)
    note: str = Field(default="", max_length=1000)
    resend: bool = False  # also email people who were already invited


def _inviter(admin: User, name: str) -> str:
    return name.strip() or (admin.first_name or "").strip() or "The BlackSync team"


@router.get("/invites")
async def invites(admin: AdminDep, db: DbDep):
    from app.models.invite import PlatformInvite

    rows = (await db.execute(select(PlatformInvite).order_by(PlatformInvite.sent_at.desc()).limit(500))).scalars().all()
    emails = [r.email for r in rows]
    tracked = await _latest_status(db, emails, ["platform_invite"])
    joined = {}
    if emails:
        for u in (await db.execute(select(User).where(func.lower(User.email).in_(emails)))).scalars().all():
            joined[u.email.lower()] = _iso(u.created_at)
    return {
        "default_inviter": _inviter(admin, ""),
        "items": [{"id": str(r.id), "email": r.email, "first_name": r.first_name, "inviter": r.inviter_name,
                   "sent_at": _iso(r.sent_at), "send_count": r.send_count, "joined_at": joined.get(r.email),
                   "tracking": tracked.get((r.email, "platform_invite"))}
                  for r in rows],
    }


@router.get("/invites/preview")
async def invite_preview(admin: AdminDep, first_name: str = "", email: str = "", inviter: str = "", note: str = ""):
    from app.services.onboarding_emails import platform_invite_email

    subject, html = platform_invite_email(first_name[:100] or "Alex", email[:320] or "alex@example.com",
                                          _inviter(admin, inviter[:100]), note[:1000])
    return {"subject": subject, "html": html, "to": email or "alex@example.com"}


@router.post("/invites")
async def send_invites(body: InviteBody, admin: AdminDep, db: DbDep):
    from app.models.invite import PlatformInvite
    from app.services.email import email_enabled, send_email
    from app.services.onboarding_emails import platform_invite_email

    if not email_enabled():
        raise HTTPException(status_code=409, detail="Email isn't set up on the server.")
    inviter = _inviter(admin, body.inviter)
    sent, skipped, failed, invalid = [], [], [], []
    seen = set()
    for p in body.people:
        email = p.email.strip().lower()
        if email in seen:
            continue
        seen.add(email)
        if not _EMAIL.match(email):
            invalid.append(p.email)
            continue
        if (await db.execute(select(User.id).where(func.lower(User.email) == email))).first():
            skipped.append({"email": email, "reason": "already has an account"})
            continue
        row = (await db.execute(select(PlatformInvite).where(PlatformInvite.email == email))).scalar_one_or_none()
        if row and not body.resend:
            skipped.append({"email": email, "reason": "already invited"})
            continue
        first = p.first_name.strip() or (row.first_name if row else "")
        subject, html = platform_invite_email(first, email, inviter, body.note)
        if not await send_email(email, subject, html, kind="platform_invite"):
            failed.append(email)
            continue
        now = datetime.now(timezone.utc)
        if row:
            row.first_name, row.inviter_name, row.note = first, inviter, body.note
            row.sent_at, row.send_count, row.invited_by = now, row.send_count + 1, admin.id
        else:
            db.add(PlatformInvite(email=email, first_name=first, inviter_name=inviter, note=body.note,
                                  invited_by=admin.id, sent_at=now))
        await db.commit()
        sent.append(email)
    log.info("platform_invites_sent", by=str(admin.id), sent=len(sent), skipped=len(skipped), failed=len(failed))
    return {"sent": sent, "skipped": skipped, "failed": failed, "invalid": invalid}


# ── Open / click tracking (Resend webhook) ───────────────────────────────────


@router.get("/tracking")
async def tracking(_: AdminDep, db: DbDep):
    from datetime import timedelta

    from app.config import settings
    from app.models.email_message import EmailMessage
    from app.routers.resend_hooks import webhook_secret

    since = datetime.now(timezone.utc) - timedelta(days=30)
    rows = (await db.execute(select(EmailMessage).where(EmailMessage.sent_at >= since))).scalars().all()
    last_event = max((m.updated_at for m in rows if m.status != "sent" or m.delivered_at), default=None)
    return {
        "configured": bool(webhook_secret()),
        "webhook_url": f"{(settings.app_url or '').rstrip('/')}/api/webhooks/resend",
        "events": ["email.delivered", "email.opened", "email.clicked", "email.bounced", "email.complained"],
        "last_event_at": _iso(last_event),
        "last_30_days": {
            "sent": len(rows),
            "delivered": sum(1 for m in rows if m.delivered_at),
            "opened": sum(1 for m in rows if m.opened_at),
            "clicked": sum(1 for m in rows if m.clicked_at),
            "bounced": sum(1 for m in rows if m.bounced_at),
        },
    }


class TrackingSecret(BaseModel):
    secret: str = Field(min_length=10, max_length=200)


@router.put("/tracking")
async def save_tracking_secret(body: TrackingSecret, admin: AdminDep, db: DbDep):
    from app.services import secret_store

    secret = body.secret.strip()
    if not secret.startswith("whsec_"):
        raise HTTPException(status_code=400, detail="That doesn't look like a Resend signing secret (it starts with whsec_).")
    if not secret_store.available():
        raise HTTPException(status_code=409, detail="Secret storage isn't available on the server.")
    await secret_store.put(db, "resend_webhook_secret", secret)
    await db.commit()
    log.info("resend_webhook_secret_saved", by=str(admin.id))
    return await tracking(admin, db)


@router.get("/activity")
async def activity(_: AdminDep, db: DbDep, limit: int = 100):
    from app.models.email_message import EmailMessage

    rows = (await db.execute(select(EmailMessage).order_by(EmailMessage.sent_at.desc()).limit(min(max(limit, 1), 300)))).scalars().all()
    return {"items": [{"id": str(m.id), "to": m.to_email, "subject": m.subject, "kind": m.kind, **_track(m)} for m in rows]}
