"""
Paying for property-owner lookups.

Order for a new single address (repeat views of a saved result are always free):
  1. unlimited accounts           → free
  2. the free daily allowance     → free (default 5 single lookups per account per UTC day)
  3. prepaid lookup credits       → 1 credit (credits an admin granted before the USD balance existed)
  4. the lookup balance (USD)     → the admin-set price, confirmed by the customer first
Bulk files skip the free allowance and use credits (if they cover the whole file) or the balance.

Every paid lookup is reserved before DataSkip is called, then settled: with the
"match" policy only lookups that find an owner are charged; with "completed"
every lookup that completes is charged. Failures are always released.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Organization
from app.models.billing import LookupBalanceTransaction
from app.models.lead_finder import PropertyLookup
from app.services.billing import catalog, settings_store

_locks: dict = {}


_choice_locks: dict = {}


def _lock(org_id) -> asyncio.Lock:
    return _locks.setdefault(org_id, asyncio.Lock())


def choice_lock(org_id) -> asyncio.Lock:
    return _choice_locks.setdefault(org_id, asyncio.Lock())


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class PaymentNeeded(Exception):
    """402-style refusal with a machine code the UI acts on."""

    def __init__(self, code: str, message: str, **extra):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra


async def free_used_today(db: AsyncSession, org_id) -> int:
    return int((await db.execute(select(func.count()).select_from(PropertyLookup).where(
        PropertyLookup.org_id == org_id, PropertyLookup.lookup_date == today_utc(),
        PropertyLookup.batch_id.is_(None), PropertyLookup.pay_source == "free",
        PropertyLookup.status.in_(("reserved", "completed"))))).scalar_one())


async def status(db: AsyncSession, org: Organization) -> dict:
    cfg = await settings_store.get_all(db)
    await db.refresh(org, ["lookup_balance_cents", "lead_credits_balance", "lead_credits_unlimited"])
    free_daily = int(cfg["lookup_free_daily"] or 0)
    used = await free_used_today(db, org.id)
    price = cfg["property_lookup_price_cents"]
    return {
        "balance_cents": org.lookup_balance_cents or 0,
        "prepaid_credits": org.lead_credits_balance or 0,
        "unlimited": org.lead_credits_unlimited is True,
        "free_daily": free_daily, "free_used_today": min(used, free_daily),
        "free_remaining": max(0, free_daily - used),
        "price_cents": price, "paid_enabled": price is not None,
        "policy": cfg["lookup_charge_policy"],
        "funds_options": [{"key": k, "amount_cents": catalog.LOOKUP_FUNDS[k]["amount_cents"]} for k in catalog.FUNDS_ORDER],
    }


def charged(policy: str, found: bool) -> bool:
    return found or policy == "completed"


# ── Holds ─────────────────────────────────────────────────────────────────────


async def hold_cents(db: AsyncSession, org: Organization, cents: int) -> None:
    """Atomically set aside `cents` of the lookup balance. Commits. Raises PaymentNeeded."""
    async with _lock(org.id):
        have = (await db.execute(select(Organization.lookup_balance_cents).where(Organization.id == org.id)
                                 .with_for_update())).scalar_one() or 0
        if have < cents:
            await db.commit()
            raise PaymentNeeded("insufficient_balance", "Your lookup balance is too low. Add funds under Billing & Usage.",
                                balance_cents=have, needed_cents=cents)
        await db.execute(update(Organization).where(Organization.id == org.id)
                         .values(lookup_balance_cents=Organization.lookup_balance_cents - cents))
        await db.commit()
    await db.refresh(org, ["lookup_balance_cents"])


async def release_cents(db: AsyncSession, org: Organization, cents: int) -> None:
    """Give back held cents (caller commits)."""
    if cents > 0:
        await db.execute(update(Organization).where(Organization.id == org.id).values(
            lookup_balance_cents=func.coalesce(Organization.lookup_balance_cents, 0) + cents))


async def record_charge(db: AsyncSession, org: Organization, cents: int, note: str, *, user_id=None,
                        lookup_id=None, batch_id=None) -> None:
    """Ledger entry for held cents that were actually spent (caller commits)."""
    if cents <= 0:
        return
    await db.flush()
    bal = (await db.execute(select(Organization.lookup_balance_cents).where(Organization.id == org.id))).scalar_one() or 0
    db.add(LookupBalanceTransaction(org_id=org.id, amount_cents=-cents, balance_after_cents=bal, kind="lookup",
                                    note=note[:500], lookup_id=lookup_id, batch_id=batch_id, created_by=user_id))


# ── Choosing how to pay ───────────────────────────────────────────────────────


async def choose_single(db: AsyncSession, org: Organization, expected_price_cents: int | None) -> tuple[str, int]:
    """(pay_source, unit_cents) for one new single lookup, with the hold already taken. Raises PaymentNeeded."""
    from app.services import lead_finder as lf

    if org.lead_credits_unlimited is True:
        return "unlimited", 0
    st = await status(db, org)
    if st["free_remaining"] > 0:
        return "free", 0
    if (org.lead_credits_balance or 0) > 0:
        try:
            await lf.hold_credits(db, org, 1)
            return "credit", 0
        except lf.NotEnoughCredits:
            pass
    return "balance", await _hold_paid(db, org, 1, expected_price_cents, st)


async def choose_bulk(db: AsyncSession, org: Organization, n: int, expected_price_cents: int | None) -> tuple[str, int]:
    from app.services import lead_finder as lf

    if n <= 0 or org.lead_credits_unlimited is True:
        return "unlimited", 0
    have = org.lead_credits_balance or 0
    if have >= n:
        try:
            await lf.hold_credits(db, org, n)
            return "credit", 0
        except lf.NotEnoughCredits:
            pass
    st = await status(db, org)
    if st["price_cents"] is None and have > 0:
        raise PaymentNeeded("insufficient_credits", f"This file needs up to {n:,} lookup credits and you have {have:,}. "
                                                    "Upload fewer addresses or ask your BlackSync admin for more.",
                            needed=n, available=have)
    return "balance", await _hold_paid(db, org, n, expected_price_cents, st)


async def _hold_paid(db: AsyncSession, org: Organization, n: int, expected: int | None, st: dict) -> int:
    price = st["price_cents"]
    if price is None:
        raise PaymentNeeded("paid_disabled", "You've used today's free lookups. Paid lookups aren't available yet — "
                                             "try again tomorrow.", free_daily=st["free_daily"])
    if expected != price:
        # The customer must see and accept the current price before anything is charged.
        raise PaymentNeeded("confirm_price", "Confirm the price to continue.", price_cents=price, count=n,
                            total_cents=price * n, balance_cents=st["balance_cents"], policy=st["policy"])
    await hold_cents(db, org, price * n)
    return price


async def release(db: AsyncSession, org: Organization, source: str, n: int, unit_cents: int) -> None:
    from app.services import lead_finder as lf

    if n <= 0:
        return
    if source == "credit":
        await lf.release_credits(db, org, n)
    elif source == "balance":
        await release_cents(db, org, n * unit_cents)


async def settle(db: AsyncSession, org: Organization, source: str, unit_cents: int, *, held: int, charge_n: int,
                 note: str, user_id=None, lookup_id=None, batch_id=None) -> int:
    """Keep `charge_n` of `held` reserved lookups, give the rest back. Returns cents charged. Caller commits."""
    from app.services import lead_finder as lf

    charge_n = max(0, min(charge_n, held))
    await release(db, org, source, held - charge_n, unit_cents)
    if source == "credit":
        await lf.record_usage(db, org, charge_n, note, user_id, lookup_id=lookup_id, batch_id=batch_id)
        return 0
    if source == "balance":
        await record_charge(db, org, charge_n * unit_cents, note, user_id=user_id, lookup_id=lookup_id, batch_id=batch_id)
        return charge_n * unit_cents
    return 0
