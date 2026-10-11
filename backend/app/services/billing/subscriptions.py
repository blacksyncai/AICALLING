"""
Subscriptions: mirror Stripe's subscription, grant included credits when a
cycle is paid, change plans with a proration preview, cancel/resume, and keep
the additional-phone-number add-on quantity in step with assigned numbers.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.account import Organization
from app.models.billing import BillingSubscription, CreditLot
from app.services.billing import catalog, credits, settings_store, stripe_api
from app.services.billing.purchases import BillingError, customer_id, org_for_customer

log = structlog.get_logger(__name__)

LIVE = ("active", "trialing", "past_due")


def _ts(v) -> datetime | None:
    return datetime.fromtimestamp(int(v), tz=timezone.utc) if v else None


def _items(sub: dict) -> list[dict]:
    return ((sub.get("items") or {}).get("data")) or []


def _is_phone_item(item: dict) -> bool:
    price = item.get("price") or {}
    return price.get("lookup_key") == catalog.PHONE_ADDON["lookup_key"]


def _plan_item(sub: dict) -> dict | None:
    return next((i for i in _items(sub) if not _is_phone_item(i)), None)


def _period_end(sub: dict, item: dict | None = None) -> datetime | None:
    # Newer API versions moved the period onto subscription items.
    return _ts(sub.get("current_period_end") or (item or {}).get("current_period_end"))


async def sync_from_stripe(db: AsyncSession, sub: dict, org_id: uuid.UUID) -> BillingSubscription:
    """Write Stripe's view of the subscription onto our mirror row. Caller commits."""
    prices = await catalog.resolve_prices()
    item = _plan_item(sub)
    price_id = ((item or {}).get("price") or {}).get("id")
    phone = next((i for i in _items(sub) if _is_phone_item(i)), None)
    row = await db.get(BillingSubscription, org_id)
    if row is None:
        row = BillingSubscription(org_id=org_id, stripe_subscription_id=sub["id"])
        db.add(row)
    elif row.stripe_subscription_id != sub["id"] and row.status in LIVE and sub.get("status") not in LIVE:
        return row  # an old, ended subscription mustn't overwrite the live one
    row.stripe_subscription_id = sub["id"]
    row.price_id = price_id
    row.plan_key = catalog.plan_for_price(price_id, prices)
    row.status = sub.get("status") or "incomplete"
    row.current_period_end = _period_end(sub, item)
    row.cancel_at_period_end = bool(sub.get("cancel_at_period_end"))
    row.phone_item_id = phone["id"] if phone else None
    row.phone_quantity = int(phone.get("quantity") or 0) if phone else 0
    await db.flush()
    return row


async def grant_included(db: AsyncSession, org: Organization, *, plan_key: str, invoice_id: str,
                         period_end: datetime | None, credits_n: int | None = None, note: str | None = None) -> bool:
    """Included credits for one paid cycle (idempotent per invoice). Previous cycle's leftovers expire."""
    exists = (await db.execute(select(CreditLot.id).where(CreditLot.org_id == org.id, CreditLot.stripe_ref == invoice_id)))\
        .first()
    if exists:
        return False
    plan = catalog.PLANS[plan_key]
    if not settings.included_credits_rollover:
        await credits.expire_included(db, org, before=datetime.max.replace(tzinfo=timezone.utc),
                                      note="Unused included credits replaced by the new billing cycle")
    n = credits_n if credits_n is not None else plan["included_credits"]
    await credits.add_lot(db, org, n, source="included", kind="included",
                          note=note or f"{plan['name']} plan — {n:,} included credits",
                          stripe_ref=invoice_id, expires_at=None if settings.included_credits_rollover else period_end)
    log.info("included_credits_granted", org_id=str(org.id), plan=plan_key, credits=n, invoice=invoice_id)
    return True


def _invoice_subscription(inv: dict) -> str | None:
    sub = inv.get("subscription")
    if isinstance(sub, dict):
        sub = sub.get("id")
    if not sub:
        parent = (inv.get("parent") or {}).get("subscription_details") or {}
        sub = parent.get("subscription")
    return sub


async def on_invoice_paid(db: AsyncSession, inv: dict) -> uuid.UUID | None:
    org_id = await org_for_customer(db, inv.get("customer"))
    sub_id = _invoice_subscription(inv)
    if not org_id or not sub_id:
        return org_id
    if inv.get("billing_reason") not in ("subscription_create", "subscription_cycle"):
        return org_id
    sub = await stripe_api.retrieve_subscription(sub_id)
    row = await sync_from_stripe(db, sub, org_id)
    if row.plan_key:
        org = await db.get(Organization, org_id)
        await grant_included(db, org, plan_key=row.plan_key, invoice_id=inv["id"],
                             period_end=row.current_period_end)
    return org_id


# ── Customer actions ──────────────────────────────────────────────────────────


async def _live_sub(db: AsyncSession, org_id: uuid.UUID) -> tuple[BillingSubscription, dict]:
    row = await db.get(BillingSubscription, org_id)
    if row is None or row.status not in LIVE:
        raise BillingError("There's no active subscription on this account.", 409)
    sub = await stripe_api.retrieve_subscription(row.stripe_subscription_id)
    return row, sub


async def preview_change(db: AsyncSession, org_id: uuid.UUID, plan_key: str) -> dict:
    row, sub = await _live_sub(db, org_id)
    if row.plan_key == plan_key:
        raise BillingError("You're already on this plan.")
    try:
        price = await catalog.sellable_price(plan_key)
    except catalog.NotSellable as exc:
        raise BillingError(str(exc), 409)
    item = _plan_item(sub)
    inv = await stripe_api.preview_plan_change(customer=sub["customer"], subscription=sub, item_id=item["id"],
                                               new_price=price)
    proration = sum(l.get("amount", 0) for l in (inv.get("lines") or {}).get("data", [])
                    if l.get("proration") or (l.get("parent") or {}).get("subscription_item_details", {}).get("proration"))
    new_plan, old_plan = catalog.PLANS[plan_key], catalog.PLANS.get(row.plan_key or "")
    upgrade = old_plan is None or new_plan["amount_cents"] > old_plan["amount_cents"]
    return {
        "plan": plan_key, "upgrade": upgrade, "amount_due_now_cents": max(0, proration) if upgrade else 0,
        "proration_cents": proration, "next_invoice_total_cents": inv.get("total"),
        "next_period_end": row.current_period_end.isoformat() if row.current_period_end else None,
        "new_monthly_cents": new_plan["amount_cents"],
        "included_credits_now": max(0, new_plan["included_credits"] - (old_plan or {}).get("included_credits", 0))
        if upgrade else 0,
    }


async def change_plan(db: AsyncSession, org_id: uuid.UUID, plan_key: str, user_id: uuid.UUID) -> BillingSubscription:
    row, sub = await _live_sub(db, org_id)
    if row.plan_key == plan_key:
        raise BillingError("You're already on this plan.")
    price = await catalog.sellable_price(plan_key)
    old_plan = catalog.PLANS.get(row.plan_key or "")
    item = _plan_item(sub)
    updated = await stripe_api.change_plan(subscription_id=sub["id"], item_id=item["id"], new_price=price,
                                           idempotency_key=f"bs-plan-{sub['id']}-{plan_key}-{uuid.uuid4().hex[:8]}")
    row = await sync_from_stripe(db, updated, org_id)
    new_plan = catalog.PLANS[plan_key]
    if old_plan and new_plan["included_credits"] > old_plan["included_credits"]:
        # Upgrade: top the cycle's included credits up to the new plan's amount.
        org = await db.get(Organization, org_id)
        diff = new_plan["included_credits"] - old_plan["included_credits"]
        await grant_included_extra(db, org, diff, ref=f"upgrade:{sub['id']}:{int(row.current_period_end.timestamp()) if row.current_period_end else 0}",
                                   period_end=row.current_period_end, note=f"Upgraded to {new_plan['name']} — {diff:,} more included credits")
    await db.commit()
    log.info("plan_changed", org_id=str(org_id), plan=plan_key, by=str(user_id))
    return row


async def grant_included_extra(db: AsyncSession, org: Organization, n: int, *, ref: str, period_end, note: str) -> None:
    exists = (await db.execute(select(CreditLot.id).where(CreditLot.org_id == org.id, CreditLot.stripe_ref == ref))).first()
    if exists or n <= 0:
        return
    await credits.add_lot(db, org, n, source="included", kind="included", note=note, stripe_ref=ref,
                          expires_at=None if settings.included_credits_rollover else period_end)


async def set_cancel(db: AsyncSession, org_id: uuid.UUID, cancel: bool) -> BillingSubscription:
    row, sub = await _live_sub(db, org_id)
    updated = await stripe_api.set_cancel_at_period_end(sub["id"], cancel)
    row = await sync_from_stripe(db, updated, org_id)
    await db.commit()
    return row


# ── Phone number add-on ───────────────────────────────────────────────────────


async def phone_summary(db: AsyncSession, org_id: uuid.UUID) -> dict:
    from app.services.telephony import active_numbers

    included = int(await settings_store.get(db, "included_phone_numbers") or 0)
    active = len(await active_numbers(db, org_id))
    row = await db.get(BillingSubscription, org_id)
    subscribed = bool(row and row.status in LIVE)
    return {"active": active, "included": included if subscribed else 0,
            "billable": max(0, active - included) if subscribed else 0,
            "billed_quantity": row.phone_quantity if row else 0,
            "unit_cents": catalog.PHONE_ADDON["amount_cents"], "subscribed": subscribed}


async def sync_phone_quantity(db: AsyncSession, org_id: uuid.UUID) -> None:
    """Bill max(0, active numbers − included) on the subscription. No subscription = nothing billed."""
    row = await db.get(BillingSubscription, org_id)
    if row is None or row.status not in LIVE or not settings.stripe_secret_key:
        return
    summary = await phone_summary(db, org_id)
    if summary["billable"] == row.phone_quantity:
        return
    try:
        price = await catalog.sellable_price(catalog.PHONE_ADDON["key"])
    except catalog.NotSellable:
        log.warning("phone_addon_price_missing", org_id=str(org_id))
        return
    sub = await stripe_api.set_phone_quantity(
        subscription_id=row.stripe_subscription_id, item_id=row.phone_item_id, price_id=price,
        quantity=summary["billable"], idempotency_key=f"bs-phones-{org_id}-{summary['billable']}-{uuid.uuid4().hex[:6]}")
    await sync_from_stripe(db, sub, org_id)
    await db.commit()
    log.info("phone_quantity_synced", org_id=str(org_id), quantity=summary["billable"])


async def portal_url(db: AsyncSession, org_id: uuid.UUID) -> str:
    from app.services.billing.purchases import app_url

    cid = await customer_id(db, org_id)
    if not cid:
        raise BillingError("Add a payment first — there's no billing profile yet.", 409)
    return await stripe_api.create_portal_session(customer=cid, return_url=app_url("/billing?tab=invoices"))
