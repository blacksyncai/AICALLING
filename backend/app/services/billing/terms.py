"""Terms of Service versions and acceptance records.

TERMS_VERSION is the text at /terms; bump it with every published edit. Starting a paid plan requires agreeing
to the current version (checked on the server before any checkout session is created).

Existing subscribers are never stopped by an edit. Only when a change is material and renewed consent is
legally needed, set REACCEPT_FROM to that version: subscribers whose last acceptance is older then see a
(non-blocking) prompt in Billing until they agree.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.terms import TermsAcceptance

TERMS_VERSION = "2026-10-28"
TERMS_URL = "/terms"
REACCEPT_FROM: str | None = None  # e.g. "2027-03-01" after a material change; None = no renewed consent needed


async def record(db: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID | None, plan_key: str, interval: str,
                 amount_cents: int | None, context: str = "checkout", ip: str = "", user_agent: str = "") -> TermsAcceptance:
    row = TermsAcceptance(org_id=org_id, user_id=user_id, terms_version=TERMS_VERSION, plan_key=plan_key,
                          billing_interval=interval, amount_cents=amount_cents, context=context,
                          ip=(ip or "")[:64], user_agent=(user_agent or "")[:500])
    db.add(row)
    await db.flush()
    return row


async def latest(db: AsyncSession, org_id: uuid.UUID) -> TermsAcceptance | None:
    return (await db.execute(select(TermsAcceptance).where(TermsAcceptance.org_id == org_id)
                             .order_by(TermsAcceptance.accepted_at.desc()).limit(1))).scalar_one_or_none()


async def needs_renewal(db: AsyncSession, org_id: uuid.UUID, subscribed: bool) -> bool:
    """A live subscriber asked to agree again, only after a material change (REACCEPT_FROM)."""
    if not subscribed or not REACCEPT_FROM:
        return False
    last = await latest(db, org_id)
    return last is None or last.terms_version < REACCEPT_FROM
