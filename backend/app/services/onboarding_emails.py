"""
Sign-up emails: a welcome email when a new account is created, then — a day later — an offer of a
free walkthrough call. Sent through Resend (app/services/email.py); nothing is sent without it.

Each email is claimed with an atomic update before sending, so it goes out once even with several
API replicas. Only users who got the welcome email get the follow-up (no emails to older accounts).
"""

from __future__ import annotations

import asyncio
import html
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, update

from app.config import settings
from app.models.account import Organization, User
from app.services import email_templates as t
from app.services.email import email_enabled, send_email

log = structlog.get_logger(__name__)

# The walkthrough offer goes out the next day: by then they've either tried it or got stuck.
FOLLOWUP_DELAY = timedelta(hours=24)
# Don't send a stale offer (e.g. after an outage) to someone who signed up long ago.
FOLLOWUP_MAX_AGE = timedelta(days=4)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _app_url() -> str:
    return (settings.app_url or "https://blacksync.si").rstrip("/")


def _first(user: User) -> str:
    return html.escape((user.first_name or "").strip())


def welcome_email(user: User, org_name: str) -> tuple[str, str]:
    first, company = _first(user), html.escape(org_name)
    href = f"{_app_url()}/dashboard"
    steps = "".join(
        t.p(f"<strong style=\"color:{t.INK};\">{n}.</strong> {s}", margin="0 0 10px 0")
        for n, s in enumerate([
            "<strong style=\"color:#1C1917;\">Talk to your welcome agent</strong> — she's ready to test right in your browser.",
            "<strong style=\"color:#1C1917;\">Build your agent</strong> — tell us about your business and BlackSync writes the script.",
            "<strong style=\"color:#1C1917;\">Make your first call</strong> — have it call your own phone to hear what your leads will hear.",
        ], start=1)
    )
    body = t.layout(
        title="Welcome to BlackSync",
        preheader="Your AI calling workspace is ready — here's how to hear it in action.",
        heading=f"Welcome to BlackSync{', ' + first if first else ''}",
        body_html=t.p(f"Your workspace for <strong style=\"color:{t.INK};\">{company}</strong> is ready. "
                      "Here's the fastest way to see it work:")
        + steps + t.button(href, "Open BlackSync") + t.divider()
        + t.p("Questions? Use the chat in the corner of the app and we'll help.", size=12, margin="0"),
    )
    return "Welcome to BlackSync — your workspace is ready", body


def followup_email(user: User, booking_url: str) -> tuple[str, str]:
    first = _first(user)
    dash = f"{_app_url()}/dashboard"
    book = html.escape(booking_url, quote=True)
    body = t.layout(
        title="Want a hand setting up?",
        preheader="Book a free walkthrough and we'll set up your first AI agent with you.",
        heading="Want us to set it up with you?",
        body_html=t.p(f"Hi{' ' + first if first else ''}, we'd love to help you get your first AI agent calling. "
                      "Book a free walkthrough and we'll build it with you live — your script, your voice "
                      "and your calendar.")
        + t.button(book, "Book a free walkthrough")
        + t.p(f'Rather do it yourself? <a href="{dash}" style="color:{t.ORANGE};">Pick up where you left off</a>.',
              size=13, margin="0"),
    )
    return "Want a hand setting up your AI agent?", body


async def send_welcome(db, user_id: uuid.UUID, org_id: uuid.UUID) -> bool:
    """Send the welcome email once (no-op without Resend)."""
    if not email_enabled():
        return False
    claimed = await db.execute(update(User).where(User.id == user_id, User.welcome_email_at.is_(None))
                               .values(welcome_email_at=_now()))
    await db.commit()
    if claimed.rowcount != 1:
        return False
    user, org = await db.get(User, user_id), await db.get(Organization, org_id)
    if not user or not org:
        return False
    subject, body = welcome_email(user, org.name)
    ok = await send_email(user.email, subject, body)
    log.info("welcome_email", user_id=str(user_id), sent=ok)
    return ok


def send_welcome_soon(user_id: uuid.UUID, org_id: uuid.UUID) -> None:
    """Fire-and-forget welcome email, so sign-up doesn't wait on the email provider."""
    from app.database import AsyncSessionLocal

    async def go() -> None:
        try:
            async with AsyncSessionLocal() as db:
                await send_welcome(db, user_id, org_id)
        except Exception as exc:
            log.warning("welcome_email_failed", error=str(exc)[:200])

    asyncio.create_task(go())


async def send_due_followups(db, now: datetime | None = None) -> int:
    """Walkthrough offers for users whose welcome email went out at least FOLLOWUP_DELAY ago."""
    if not email_enabled():
        return 0
    from app.services.billing import settings_store

    now = now or _now()
    booking = (await settings_store.get(db, "onboarding_booking_url")) or (await settings_store.get(db, "sales_booking_url"))
    if not booking:
        return 0
    due = (await db.execute(select(User.id).where(
        User.welcome_email_at.is_not(None), User.followup_email_at.is_(None),
        User.welcome_email_at <= now - FOLLOWUP_DELAY, User.welcome_email_at > now - FOLLOWUP_MAX_AGE,
    ).limit(50))).scalars().all()
    sent = 0
    for uid in due:
        claimed = await db.execute(update(User).where(User.id == uid, User.followup_email_at.is_(None))
                                   .values(followup_email_at=now))
        await db.commit()
        if claimed.rowcount != 1:
            continue
        user = await db.get(User, uid)
        if not user:
            continue
        subject, body = followup_email(user, booking)
        if await send_email(user.email, subject, body):
            sent += 1
        log.info("followup_email", user_id=str(uid))
    return sent


def start_sweeper(interval: float = 600.0):
    """Every 10 minutes, send the walkthrough offers that are due."""
    from app.database import AsyncSessionLocal

    async def _loop() -> None:
        while True:
            try:
                async with AsyncSessionLocal() as db:
                    await send_due_followups(db)
            except Exception as exc:  # never let the loop die
                log.warning("followup_sweep_failed", error=str(exc)[:200])
            await asyncio.sleep(interval)

    return asyncio.create_task(_loop())
