"""
Auto-recharge (off by default). When the calling-credit balance drops below
the customer's threshold, buy their chosen pack with the saved card — at most
one pending recharge per account, never past the monthly spending limit, and
switched off after 3 failed charges in a row.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Organization
from app.models.billing import AutoRecharge, Purchase
from app.services.billing import catalog, settings_store, stripe_api
from app.services.billing.purchases import BillingError, customer_id, fulfill, mark_failed

log = structlog.get_logger(__name__)

MAX_FAILURES = 3
_locks: dict = {}
_BACKGROUND: set = set()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _month_start() -> datetime:
    n = _now()
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def month_to_date_cents(db: AsyncSession, org_id: uuid.UUID) -> int:
    return int((await db.execute(select(func.coalesce(func.sum(Purchase.amount_cents), 0)).where(
        Purchase.org_id == org_id, Purchase.kind == "auto_recharge",
        Purchase.status.in_(("paid", "pending", "partially_refunded")), Purchase.created_at >= _month_start(),
    ))).scalar_one())


async def get_config(db: AsyncSession, org_id: uuid.UUID) -> AutoRecharge:
    row = await db.get(AutoRecharge, org_id)
    if row is None:
        row = AutoRecharge(org_id=org_id, enabled=False, pack_key="credits_500", threshold=50, monthly_limit_cents=50000,
                           consecutive_failures=0)
    return row


def config_to_dict(row: AutoRecharge, mtd: int, card: dict | None) -> dict:
    return {
        "enabled": bool(row.enabled), "pack_key": row.pack_key, "threshold": row.threshold,
        "monthly_limit_cents": row.monthly_limit_cents, "month_to_date_cents": mtd,
        "authorized_at": row.authorized_at.isoformat() if row.authorized_at else None,
        "last_error": row.last_error, "consecutive_failures": row.consecutive_failures or 0,
        "pending": bool(row.pending_purchase_id), "card": card,
    }


async def update_config(db: AsyncSession, org: Organization, user_id: uuid.UUID, *, enabled: bool, pack_key: str,
                        threshold: int, monthly_limit_cents: int, consent: bool) -> AutoRecharge:
    pack = catalog.CREDIT_PACKS.get(pack_key)
    if not pack:
        raise BillingError("Choose a credit pack.")
    if threshold < 1 or threshold > 100000:
        raise BillingError("The threshold must be at least 1 credit.")
    cap = int(await settings_store.get(db, "auto_recharge_max_monthly_cents") or 0)
    if monthly_limit_cents < pack["amount_cents"]:
        raise BillingError("The monthly limit must cover at least one pack.")
    if cap and monthly_limit_cents > cap:
        raise BillingError(f"The monthly limit can't be more than ${cap / 100:,.0f}.")
    row = await db.get(AutoRecharge, org.id)
    if row is None:
        row = AutoRecharge(org_id=org.id, consecutive_failures=0)
        db.add(row)
    if enabled:
        from app.services.billing.purchases import pack_access

        access = await pack_access(db, org)
        if not access["on_plan"]:
            raise BillingError("Auto-recharge is available on BlackSync AI plans. Choose a plan to turn it on.", 402)
        if not consent:
            raise BillingError("Please confirm you authorize automatic charges.")
        cid = await customer_id(db, org.id)
        if not cid or not await stripe_api.default_payment_method(cid):
            raise BillingError("Add a card first — buy any credit pack once and it's saved for auto-recharge.", 409)
        row.authorized_by, row.authorized_at = user_id, _now()
        row.consecutive_failures, row.last_error = 0, None
    row.enabled, row.pack_key, row.threshold, row.monthly_limit_cents = enabled, pack_key, threshold, monthly_limit_cents
    await db.commit()
    log.info("auto_recharge_updated", org_id=str(org.id), enabled=enabled, pack=pack_key, threshold=threshold,
             limit=monthly_limit_cents, by=str(user_id))
    return row


def schedule_check(org_id: uuid.UUID) -> None:
    """Fire-and-forget check after a balance drop (never blocks or fails the caller)."""
    try:
        task = asyncio.get_running_loop().create_task(_check_in_new_session(org_id))
    except RuntimeError:
        return
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


async def _check_in_new_session(org_id: uuid.UUID) -> None:
    from app.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            await maybe_recharge(db, org_id)
    except Exception as exc:
        log.error("auto_recharge_check_failed", org_id=str(org_id), error=str(exc))


async def maybe_recharge(db: AsyncSession, org_id: uuid.UUID) -> Purchase | None:
    async with _locks.setdefault(org_id, asyncio.Lock()):
        cfg = (await db.execute(select(AutoRecharge).where(AutoRecharge.org_id == org_id).with_for_update()))\
            .scalar_one_or_none()
        if cfg is None or not cfg.enabled or not cfg.authorized_at:
            return None
        org = await db.get(Organization, org_id)
        await db.refresh(org, ["credits_balance"])
        if org.unlimited_credits or (org.credits_balance or 0) >= cfg.threshold:
            return None
        if cfg.pending_purchase_id:
            pending = await db.get(Purchase, cfg.pending_purchase_id)
            if pending and pending.status == "pending":
                return None
            cfg.pending_purchase_id = None
        pack = catalog.CREDIT_PACKS.get(cfg.pack_key)
        if not pack:
            return None
        from app.services.billing.purchases import pack_access

        access = await pack_access(db, org)
        if not access["allowed"]:  # trial account that already bought its one pack
            if cfg.last_error != access["reason"]:
                cfg.last_error = access["reason"]
                await db.commit()
            return None
        if await month_to_date_cents(db, org_id) + pack["amount_cents"] > cfg.monthly_limit_cents:
            cfg.last_error = "Monthly auto-recharge limit reached."
            await db.commit()
            return None
        cid = await customer_id(db, org_id)
        card = await stripe_api.default_payment_method(cid) if cid else None
        if not card:
            await _record_failure(db, cfg, "No saved card to charge.")
            await db.commit()
            return None
        p = Purchase(org_id=org_id, kind="auto_recharge", pack_key=pack["key"], amount_cents=pack["amount_cents"],
                     credits=pack["credits"], status="pending")
        db.add(p)
        await db.flush()
        cfg.pending_purchase_id, cfg.last_attempt_at = p.id, _now()
        await db.commit()

    meta = {"org_id": str(org_id), "purchase_id": str(p.id), "purchase_type": "auto_recharge", "pack": pack["key"]}
    result = await stripe_api.charge_off_session(
        customer=cid, payment_method=card["id"], amount_cents=pack["amount_cents"], idempotency_key=f"bs-recharge-{p.id}",
        metadata=meta, description=f"BlackSync auto-recharge — {pack['credits']:,} calling credits")
    if result.get("id"):
        p = await db.get(Purchase, p.id)
        p.stripe_payment_intent_id = p.stripe_payment_intent_id or result["id"]
    if result.get("status") == "succeeded":
        await fulfill(db, p.id, payment_intent=result["id"], org_id=org_id)
        await on_result(db, p, ok=True)
    elif result.get("status") in ("processing", "requires_capture"):
        pass  # the payment_intent.succeeded webhook finishes it
    else:
        err = result.get("error") or f"Payment {result.get('status') or 'failed'}"
        await mark_failed(db, p.id, err)
        await on_result(db, p, ok=False, error=err)
    await db.commit()
    log.info("auto_recharge_attempt", org_id=str(org_id), purchase_id=str(p.id), status=result.get("status"))
    return p


async def _record_failure(db: AsyncSession, cfg: AutoRecharge, error: str) -> None:
    cfg.consecutive_failures = (cfg.consecutive_failures or 0) + 1
    cfg.last_error = error[:500]
    if cfg.consecutive_failures >= MAX_FAILURES:
        cfg.enabled = False
        cfg.last_error = f"Turned off after {MAX_FAILURES} failed charges: {error}"[:500]
    from app.services.accounts import emit_event

    asyncio.get_running_loop().create_task(emit_event(cfg.org_id, "billing.auto_recharge_failed",
                                                      {"error": cfg.last_error, "disabled": not cfg.enabled}))
    log.warning("auto_recharge_failed", org_id=str(cfg.org_id), error=error, failures=cfg.consecutive_failures)


async def on_result(db: AsyncSession, p: Purchase, *, ok: bool, error: str | None = None) -> None:
    cfg = await db.get(AutoRecharge, p.org_id)
    if cfg is None:
        return
    if cfg.pending_purchase_id == p.id:
        cfg.pending_purchase_id = None
    if ok:
        cfg.consecutive_failures, cfg.last_error = 0, None
    else:
        await _record_failure(db, cfg, error or "Payment failed")
