"""
Calling credits.

`Organization.credits_balance` is the spendable total; `CreditLot` rows record
what that total is made of (included-with-plan, purchased, granted…), what each
lot cost and when it expires. The two always agree: every change goes through
`add_lot` / `consume`, which update both and write a CreditTransaction.

Call billing (documented rounding):
  exact usage = connected seconds × credit rate ÷ 60 (in thousandths of a credit)
  Whole credits are deducted; the leftover fraction carries to the account's next
  call, so 10 calls of 6 seconds at 1 credit/min cost exactly 1 credit in total.
Balances never go below zero — anything owed beyond the balance is recorded as
the call's shortfall.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import CreditTransaction, Organization
from app.models.billing import CallUsage, CreditLot
from app.models.call_log import CallLog
from app.services.billing import catalog, settings_store

log = structlog.get_logger(__name__)

# Spend order: included credits first (they expire), then free grants, then what was bought (oldest first).
_ORDER = {"included": 0, "grant": 1, "legacy": 2, "purchased": 3, "auto_recharge": 3}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def exact_balance_milli(org: Organization) -> int:
    """The true balance in thousandths of a credit: whole credits minus the fraction already used."""
    return max(0, (org.credits_balance or 0) * 1000 - (org.credit_carry_milli or 0))


def exact(milli: int | None) -> float:
    return round((milli or 0) / 1000, 3)


# Calls that never connected (no answer, busy, failed dial) are never billed.
UNBILLED_OUTCOMES = {"no_answer", "failed"}


async def _live_lots(db: AsyncSession, org_id: uuid.UUID) -> list[CreditLot]:
    lots = (await db.execute(select(CreditLot).where(CreditLot.org_id == org_id, CreditLot.credits_remaining > 0)
                             .with_for_update())).scalars().all()
    return sorted(lots, key=lambda l: (_ORDER.get(l.source, 2), _aware(l.expires_at) or datetime.max.replace(tzinfo=timezone.utc),
                                       _aware(l.created_at)))


async def reconcile(db: AsyncSession, org: Organization) -> None:
    """Credits that predate lots (or were changed outside them) become a 'legacy' lot so the totals agree."""
    await db.flush()  # sessions don't autoflush; pending lot changes must count
    await db.refresh(org, ["credits_balance"])
    in_lots = (await db.execute(select(func.coalesce(func.sum(CreditLot.credits_remaining), 0))
                                .where(CreditLot.org_id == org.id))).scalar_one()
    diff = (org.credits_balance or 0) - int(in_lots)
    if diff > 0:
        db.add(CreditLot(org_id=org.id, source="legacy", credits_granted=diff, credits_remaining=diff))
        await db.flush()
    elif diff < 0:
        await _take_from_lots(db, org.id, -diff)


async def _take_from_lots(db: AsyncSession, org_id: uuid.UUID, amount: int) -> list[tuple[CreditLot, int]]:
    taken: list[tuple[CreditLot, int]] = []
    left = amount
    for lot in await _live_lots(db, org_id):
        if left <= 0:
            break
        n = min(left, lot.credits_remaining)
        lot.credits_remaining -= n
        left -= n
        taken.append((lot, n))
    await db.flush()
    return taken


async def _change_balance(db: AsyncSession, org: Organization, amount: int) -> int:
    await db.execute(update(Organization).where(Organization.id == org.id)
                     .values(credits_balance=Organization.credits_balance + amount))
    await db.refresh(org, ["credits_balance"])
    return org.credits_balance


async def add_lot(db: AsyncSession, org: Organization, credits: int, *, source: str, kind: str, note: str,
                  amount_paid_cents: int | None = None, purchase_id: uuid.UUID | None = None,
                  stripe_ref: str | None = None, expires_at: datetime | None = None,
                  created_by: uuid.UUID | None = None) -> CreditLot:
    """Add credits as a new lot (caller commits)."""
    await reconcile(db, org)
    lot = CreditLot(org_id=org.id, source=source, credits_granted=credits, credits_remaining=credits,
                    amount_paid_cents=amount_paid_cents, purchase_id=purchase_id, stripe_ref=stripe_ref,
                    expires_at=expires_at)
    db.add(lot)
    await db.flush()
    balance = await _change_balance(db, org, credits)
    db.add(CreditTransaction(org_id=org.id, amount=credits, balance_after=balance, kind=kind, note=note,
                             amount_milli=credits * 1000, balance_after_milli=exact_balance_milli(org),
                             purchase_id=purchase_id, lot_id=lot.id, stripe_ref=stripe_ref, created_by=created_by))
    return lot


async def consume(db: AsyncSession, org: Organization, amount: int, *, kind: str, note: str,
                  call_id: uuid.UUID | None = None, created_by: uuid.UUID | None = None,
                  stripe_ref: str | None = None, record: bool = True) -> tuple[int, int]:
    """Spend up to `amount` credits, never below zero. Returns (taken, shortfall). Caller commits.
    record=False leaves the ledger row to the caller (calls write one exact row themselves)."""
    if amount <= 0:
        return 0, 0
    await reconcile(db, org)
    taken = min(amount, max(0, org.credits_balance or 0))
    if taken:
        await _take_from_lots(db, org.id, taken)
        balance = await _change_balance(db, org, -taken)
        if record:
            db.add(CreditTransaction(org_id=org.id, amount=-taken, balance_after=balance, kind=kind, note=note,
                                     amount_milli=-taken * 1000, balance_after_milli=exact_balance_milli(org),
                                     call_id=call_id, stripe_ref=stripe_ref, created_by=created_by))
    return taken, amount - taken


async def take_from_lot(db: AsyncSession, org: Organization, lot: CreditLot, amount: int, *, kind: str,
                        note: str, stripe_ref: str | None = None) -> int:
    """Remove up to `amount` unused credits from one specific lot (refunds/disputes). Returns what was taken."""
    await reconcile(db, org)
    await db.refresh(lot, ["credits_remaining"])
    n = max(0, min(amount, lot.credits_remaining, org.credits_balance or 0))
    if n:
        lot.credits_remaining -= n
        await db.flush()
        balance = await _change_balance(db, org, -n)
        db.add(CreditTransaction(org_id=org.id, amount=-n, balance_after=balance, kind=kind, note=note,
                                 amount_milli=-n * 1000, balance_after_milli=exact_balance_milli(org),
                                 lot_id=lot.id, purchase_id=lot.purchase_id, stripe_ref=stripe_ref))
    return n


async def expire_included(db: AsyncSession, org: Organization, *, before: datetime | None = None,
                          note: str = "Included credits expired at the end of the billing cycle") -> int:
    """Remove unused included credits whose cycle has ended (or all of them, when a new cycle replaces them)."""
    await reconcile(db, org)
    q = select(CreditLot).where(CreditLot.org_id == org.id, CreditLot.source == "included",
                                CreditLot.credits_remaining > 0)
    lots = (await db.execute(q)).scalars().all()
    cutoff = before or _now()
    total = 0
    for lot in lots:
        if before is None and lot.expires_at and _aware(lot.expires_at) > cutoff:
            continue
        total += lot.credits_remaining
        lot.credits_remaining = 0
    await db.flush()
    if total:
        balance = await _change_balance(db, org, -total)
        db.add(CreditTransaction(org_id=org.id, amount=-total, balance_after=balance, kind="expired", note=note,
                                 amount_milli=-total * 1000, balance_after_milli=exact_balance_milli(org)))
    return total


async def expire_due(db: AsyncSession, org: Organization) -> None:
    """Lazy expiry — run before reading or spending a balance."""
    if await expire_included(db, org):
        await db.commit()


# ── Rates & estimates ─────────────────────────────────────────────────────────


async def rate_for_agent(db: AsyncSession, agent) -> float:
    cfg = await settings_store.get_all(db)
    return settings_store.rate_for(cfg["model_credit_rates"], float(cfg["premium_voice_surcharge"] or 0),
                                   getattr(agent, "llm_model", None), await _is_premium(agent))


async def _is_premium(agent) -> bool:
    """Premium = anything outside the curated standard voices (clones, owned or pasted voice IDs)."""
    if agent is None or not getattr(agent, "voice_id", None):
        return False
    from app.routers.settings import _premium_ids, _standard_ids

    standard = set(_standard_ids(set(_premium_ids(set()))))
    return agent.voice_id not in standard


async def cents_per_credit(db: AsyncSession, org_id: uuid.UUID) -> float:
    """Weighted average of what the account paid for its remaining paid credits (list price if none)."""
    lots = (await db.execute(select(CreditLot).where(
        CreditLot.org_id == org_id, CreditLot.credits_remaining > 0, CreditLot.amount_paid_cents.is_not(None),
        CreditLot.credits_granted > 0))).scalars().all()
    credits = sum(l.credits_remaining for l in lots)
    if not credits:
        return catalog.LIST_CENTS_PER_CREDIT
    cents = sum(l.amount_paid_cents * l.credits_remaining / l.credits_granted for l in lots)
    return cents / credits


async def breakdown(db: AsyncSession, org: Organization) -> dict:
    await expire_due(db, org)
    await reconcile(db, org)
    await db.commit()
    lots = (await db.execute(select(CreditLot).where(CreditLot.org_id == org.id, CreditLot.credits_remaining > 0)))\
        .scalars().all()
    included = [l for l in lots if l.source == "included"]
    return {
        # What's really left after per-second usage (e.g. 148.92).
        "balance": exact(exact_balance_milli(org)),
        "balance_whole": org.credits_balance or 0,
        "included": sum(l.credits_remaining for l in included),
        "included_expires_at": min((_aware(l.expires_at) for l in included if l.expires_at), default=None),
        "purchased": sum(l.credits_remaining for l in lots if l.source in ("purchased", "auto_recharge")),
        "other": sum(l.credits_remaining for l in lots if l.source in ("grant", "legacy")),
        "cents_per_credit": round(await cents_per_credit(db, org.id), 4),
        "unlimited": bool(org.unlimited_credits),
    }


# ── Calls ─────────────────────────────────────────────────────────────────────

# Credits set aside per in-flight call, so parallel calls can't spend the same balance.
RESERVE_STALE_HOURS = 2


async def reserved_in_flight(db: AsyncSession, org_id: uuid.UUID, exclude: uuid.UUID | None = None) -> int:
    from datetime import timedelta

    q = select(func.coalesce(func.sum(CallLog.credits_reserved), 0)).where(
        CallLog.org_id == org_id, CallLog.ended_at.is_(None), CallLog.credits_charged.is_(None),
        CallLog.started_at >= _now() - timedelta(hours=RESERVE_STALE_HOURS))
    if exclude:
        q = q.where(CallLog.id != exclude)
    return int((await db.execute(q)).scalar_one())


async def reserve_for_call(db: AsyncSession, org: Organization, agent, requested_seconds: int) -> tuple[int, float, int]:
    """Before dialing: (seconds allowed, rate, credits reserved). Raises InsufficientCredits."""
    from app.services.accounts import InsufficientCredits

    rate = await rate_for_agent(db, agent)
    if org.unlimited_credits:
        return requested_seconds, rate, 0
    await expire_due(db, org)
    await db.refresh(org, ["credits_balance"])
    available = (org.credits_balance or 0) - await reserved_in_flight(db, org.id)
    min_needed = max(1, math.ceil(rate))  # at least one minute of talk time
    if available < min_needed:
        raise InsufficientCredits("You're out of calling credits. Buy more under Billing & Usage.")
    allowed = min(requested_seconds, int(available / rate * 60))
    reserve = min(available, math.ceil(allowed * rate / 60))
    return max(60, allowed), rate, reserve


async def charge_call(db: AsyncSession, call: CallLog) -> CallUsage | None:
    """Bill a finished phone call exactly once (CallUsage.call_id is unique). Caller commits."""
    if call.credits_charged is not None or call.call_type != "outbound" or not call.org_id:
        return None
    existing = (await db.execute(select(CallUsage).where(CallUsage.call_id == call.id))).scalar_one_or_none()
    if existing:
        call.credits_charged = existing.credits_deducted
        return existing
    org = await db.get(Organization, call.org_id)
    if not org:
        return None
    from app.models.agent import Agent

    agent = await db.get(Agent, call.agent_id) if call.agent_id else None
    seconds = max(0, int(call.duration_seconds or 0))
    # Only connected talk time is billed: a call that rang out, was busy or failed costs nothing.
    if call.outcome in UNBILLED_OUTCOMES or (call.answered_at is None and seconds == 0):
        seconds = 0
    rate = call.credit_rate if call.credit_rate is not None else await rate_for_agent(db, agent)
    call.credit_rate = rate  # keep the rate this call was billed at
    # Per second at the model's rate, kept to a thousandth of a credit: 66s at 1.0/min = 1.100 credits.
    exact_milli = round(seconds * rate * 1000 / 60)
    usage = CallUsage(org_id=org.id, call_id=call.id, agent_id=call.agent_id,
                      model=(agent.llm_model if agent else "") or "", voice_id=(agent.voice_id if agent else "") or "",
                      connected_seconds=seconds, credit_rate=rate, credits_exact_milli=exact_milli)
    db.add(usage)
    if org.unlimited_credits or exact_milli == 0:
        call.credits_charged = 0
        await db.flush()
        return usage
    await expire_due(db, org)
    await reconcile(db, org)
    # Whole credits leave the lots as the used fraction adds up; the ledger row shows the exact amount.
    old_carry = org.credit_carry_milli or 0
    whole, carry = divmod(old_carry + exact_milli, 1000)
    mins = f"{seconds // 60}:{seconds % 60:02d}"
    note = f"Call to {call.to_phone or 'contact'} · {mins} at {rate:g} credits/min"
    taken, shortfall = await consume(db, org, int(whole), kind="usage", note=note, call_id=call.id, record=False)
    if shortfall:
        carry = 0  # the balance ran out; what it couldn't cover is recorded as the shortfall
    await db.execute(update(Organization).where(Organization.id == org.id).values(credit_carry_milli=carry))
    org.credit_carry_milli = carry
    billed_milli = taken * 1000 + carry - old_carry  # = exact_milli unless the balance ran out
    db.add(CreditTransaction(org_id=org.id, amount=-taken, balance_after=org.credits_balance or 0, kind="usage", note=note,
                             amount_milli=-max(0, billed_milli), balance_after_milli=exact_balance_milli(org),
                             call_id=call.id))
    usage.credits_deducted, usage.shortfall = taken, shortfall
    call.credits_charged = taken
    await db.flush()
    if shortfall:
        log.warning("call_credit_shortfall", org_id=str(org.id), call_id=str(call.id), shortfall=shortfall)
    return usage
