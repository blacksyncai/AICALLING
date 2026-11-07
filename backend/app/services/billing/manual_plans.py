"""
Plans an admin sets by hand: the customer paid outside the app (a Stripe payment link, an invoice, a bank
transfer...) and an admin records the plan and the date it starts.

Stored like any subscription (BillingSubscription) so limits, the Billing page and plan checks all see it, with
stripe_subscription_id "manual:<org id>:<start date>" (nothing to look up in Stripe). The plan's included credits
are granted on the start date and then every month on that same day (the 31st becomes the month's last day),
exactly like a paid billing cycle: the previous cycle's unused included credits are replaced. Cancelling ends the
plan at the end of the current cycle.
"""

from __future__ import annotations

import asyncio
import calendar
from datetime import date, datetime, time, timezone

import structlog
from sqlalchemy import select

from app.models.account import Organization
from app.models.billing import BillingSubscription
from app.services.billing import catalog

log = structlog.get_logger(__name__)
PREFIX = "manual:"
LIVE = ("active", "trialing", "past_due")


def is_manual(row: BillingSubscription | None) -> bool:
    return bool(row and (row.stripe_subscription_id or "").startswith(PREFIX))


def start_of(row: BillingSubscription) -> date | None:
    try:
        return date.fromisoformat((row.stripe_subscription_id or "").rsplit(":", 1)[-1])
    except ValueError:
        return None


def _at(day: date) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=timezone.utc)


def add_months(anchor: date, months: int) -> date:
    """The anchor's day of the month, `months` later (clamped to the month's last day)."""
    y, m = divmod(anchor.month - 1 + months, 12)
    year, month = anchor.year + y, m + 1
    return date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))


def cycle(anchor: date, today: date) -> tuple[date, date]:
    """(start, end) of the billing cycle containing `today` for a plan that started on `anchor`."""
    n = 0
    while add_months(anchor, n + 1) <= today:
        n += 1
    return add_months(anchor, n), add_months(anchor, n + 1)


def _months_between(anchor: date, day: date) -> int:
    n = 0
    while add_months(anchor, n) < day:
        n += 1
    return n


async def _grant(db, org: Organization, row: BillingSubscription, start: date, end: date) -> None:
    from app.services.billing.subscriptions import grant_included

    await grant_included(db, org, plan_key=row.plan_key, invoice_id=f"{PREFIX}{org.id}:{start.isoformat()}",
                         period_end=_at(end), credits_n=row.custom_credits,
                         note=f"{catalog.PLANS[row.plan_key]['name']} plan — included credits for "
                              f"{start.strftime('%b %-d')} to {end.strftime('%b %-d, %Y')}")


async def set_plan(db, org: Organization, plan_key: str, start: date, *, credits_per_month: int | None = None,
                   today: date | None = None) -> BillingSubscription:
    """Put the account on `plan_key` from `start`. Credits for the current cycle are granted now when the start
    date has passed; otherwise on the start date. Caller commits."""
    if plan_key not in catalog.PLANS or catalog.PLANS[plan_key].get("legacy"):
        raise ValueError("Pick one of the plans.")
    today = today or datetime.now(timezone.utc).date()
    row = await db.get(BillingSubscription, org.id)
    if row is not None and row.status in LIVE and not is_manual(row):
        raise ValueError("This account already pays through a subscription in the app. Cancel that one first.")
    if row is None:
        row = BillingSubscription(org_id=org.id, stripe_subscription_id=f"{PREFIX}{org.id}:{start.isoformat()}")
        db.add(row)
    row.stripe_subscription_id = f"{PREFIX}{org.id}:{start.isoformat()}"
    row.plan_key, row.price_id, row.status, row.cancel_at_period_end = plan_key, None, "active", False
    row.custom_credits = credits_per_month
    if start <= today:
        begin, end = cycle(start, today)
        row.current_period_end = _at(end)
        await db.flush()
        await _grant(db, org, row, begin, end)
    else:
        row.current_period_end = _at(start)  # the first cycle's credits arrive on the start date
    await db.flush()
    log.info("manual_plan_set", org_id=str(org.id), plan=plan_key, start=start.isoformat())
    return row


async def end_plan(db, org: Organization, *, now: bool = False) -> BillingSubscription | None:
    """Stop a manual plan: at the end of the current cycle, or right away."""
    row = await db.get(BillingSubscription, org.id)
    if not is_manual(row) or row.status not in LIVE:
        return None
    if now:
        row.status = "canceled"
    else:
        row.cancel_at_period_end = True
    await db.flush()
    return row


async def renew_due(db, now: datetime | None = None) -> int:
    """Start every manual plan's new cycle that's due: grant its credits and move the renewal date on a month."""
    now = now or datetime.now(timezone.utc)
    rows = (await db.execute(select(BillingSubscription).where(
        BillingSubscription.stripe_subscription_id.like(f"{PREFIX}%"), BillingSubscription.status.in_(LIVE),
        BillingSubscription.current_period_end <= now))).scalars().all()
    renewed = 0
    for row in rows:
        anchor = start_of(row)
        org = await db.get(Organization, row.org_id)
        if anchor is None or org is None or row.plan_key not in catalog.PLANS:
            continue
        due = row.current_period_end
        due = (due if due.tzinfo else due.replace(tzinfo=timezone.utc)).date()
        if row.cancel_at_period_end and due > anchor:
            row.status = "canceled"  # cancelled: the plan ends with the cycle that was paid for
            await db.commit()
            log.info("manual_plan_ended", org_id=str(org.id))
            continue
        # Catch up to the current cycle if the worker was down: only the current cycle is granted.
        begin, end = cycle(anchor, now.date())
        if begin < due:
            begin, end = due, add_months(anchor, _months_between(anchor, due) + 1)
        row.current_period_end = _at(end)
        await _grant(db, org, row, begin, end)
        await db.commit()
        renewed += 1
        log.info("manual_plan_renewed", org_id=str(org.id), plan=row.plan_key, cycle_start=begin.isoformat())
    return renewed


def start_worker() -> asyncio.Task:
    async def loop() -> None:
        from app.database import AsyncSessionLocal

        while True:
            try:
                async with AsyncSessionLocal() as db:
                    await renew_due(db)
            except Exception as exc:
                log.warning("manual_plan_worker_failed", error=str(exc)[:200])
            await asyncio.sleep(900)

    return asyncio.create_task(loop())


__all__ = ["add_months", "cycle", "end_plan", "is_manual", "renew_due", "set_plan", "start_of", "start_worker"]
