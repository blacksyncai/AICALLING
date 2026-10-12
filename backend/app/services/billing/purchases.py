"""
Purchases: Stripe customers, Checkout for credit packs / lookup funds / plans,
and fulfilment. Credits and funds are granted only from server-verified payment
events (webhooks, or the synchronous result of an off-session charge) — never
from the browser returning from Checkout.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.account import Membership, Organization, User
from app.models.billing import BillingCustomer, LookupBalanceTransaction, Purchase
from app.services.billing import catalog, credits, stripe_api

log = structlog.get_logger(__name__)


class BillingError(Exception):
    """A problem with a message safe to show the customer."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def app_url(path: str) -> str:
    base = (settings.app_url or "https://blacksync.si").rstrip("/")
    return f"{base}{path}"


async def customer_id(db: AsyncSession, org_id: uuid.UUID) -> str | None:
    row = await db.get(BillingCustomer, org_id)
    return row.stripe_customer_id if row else None


async def ensure_customer(db: AsyncSession, org: Organization) -> str:
    existing = await customer_id(db, org.id)
    if existing:
        return existing
    owner = (await db.execute(
        select(User.email).join(Membership, Membership.user_id == User.id)
        .where(Membership.org_id == org.id, Membership.role == "owner").limit(1)
    )).scalar_one_or_none()
    cid = await stripe_api.create_customer(org_id=str(org.id), name=org.name, email=owner)
    db.add(BillingCustomer(org_id=org.id, stripe_customer_id=cid))
    await db.commit()
    return cid


async def org_for_customer(db: AsyncSession, stripe_customer: str | None) -> uuid.UUID | None:
    if not stripe_customer:
        return None
    return (await db.execute(select(BillingCustomer.org_id).where(
        BillingCustomer.stripe_customer_id == stripe_customer))).scalar_one_or_none()


# ── Checkout ──────────────────────────────────────────────────────────────────


async def _checkout(db: AsyncSession, org: Organization, user_id: uuid.UUID, *, kind: str, item: dict,
                    price_id: str, credits_n: int, return_path: str) -> str:
    cid = await ensure_customer(db, org)
    purchase = Purchase(org_id=org.id, kind=kind, pack_key=item["key"], amount_cents=item["amount_cents"],
                        credits=credits_n, status="pending", created_by=user_id)
    db.add(purchase)
    await db.flush()
    meta = {"org_id": str(org.id), "purchase_id": str(purchase.id), "purchase_type": kind, "pack": item["key"]}
    session = await stripe_api.create_checkout_session(
        mode="payment", customer=cid, line_items=[{"price": price_id, "quantity": 1}],
        metadata=meta, client_reference_id=str(org.id),
        # Saving the card lets the customer turn on auto-recharge later; Checkout shows the consent text.
        payment_intent_data={"metadata": meta, "setup_future_usage": "off_session"},
        success_url=app_url(f"{return_path}?checkout=success&purchase={purchase.id}"),
        cancel_url=app_url(f"{return_path}?checkout=canceled"),
        idempotency_key=f"bs-checkout-{purchase.id}",
    )
    purchase.stripe_checkout_session_id = session["id"]
    await db.commit()
    log.info("checkout_created", org_id=str(org.id), kind=kind, item=item["key"], purchase_id=str(purchase.id))
    return session["url"]


async def checkout_credit_pack(db: AsyncSession, org: Organization, user_id: uuid.UUID, pack_key: str) -> str:
    pack = catalog.CREDIT_PACKS.get(pack_key)
    if not pack:
        raise BillingError("Unknown credit pack.")
    try:
        price = await catalog.sellable_price(pack_key)
    except catalog.NotSellable as exc:
        raise BillingError(str(exc), 409)
    return await _checkout(db, org, user_id, kind="credit_pack", item=pack, price_id=price,
                           credits_n=pack["credits"], return_path="/billing")


async def checkout_lookup_funds(db: AsyncSession, org: Organization, user_id: uuid.UUID, key: str) -> str:
    item = catalog.LOOKUP_FUNDS.get(key)
    if not item:
        raise BillingError("Unknown amount.")
    try:
        price = await catalog.sellable_price(key)
    except catalog.NotSellable as exc:
        raise BillingError(str(exc), 409)
    # The balance this pack adds is fixed when it's bought (kept on the purchase for refunds).
    grant = catalog.lookup_grant_cents(item)
    return await _checkout(db, org, user_id, kind="lookup_funds", item=item, price_id=price, credits_n=grant,
                           return_path="/billing")


async def checkout_plan(db: AsyncSession, org: Organization, user_id: uuid.UUID, plan_key: str) -> str:
    from app.models.billing import BillingSubscription

    if plan_key not in catalog.PLANS:
        raise BillingError("Unknown plan.")
    sub = await db.get(BillingSubscription, org.id)
    if sub and sub.status in ("active", "trialing", "past_due", "incomplete"):
        raise BillingError("This account already has a subscription — change plans instead.", 409)
    try:
        price = await catalog.sellable_price(plan_key)
    except catalog.NotSellable as exc:
        raise BillingError(str(exc), 409)
    cid = await ensure_customer(db, org)
    meta = {"org_id": str(org.id), "purchase_type": "plan", "plan": plan_key}
    session = await stripe_api.create_checkout_session(
        mode="subscription", customer=cid, line_items=[{"price": price, "quantity": 1}],
        metadata=meta, client_reference_id=str(org.id), subscription_data={"metadata": meta},
        success_url=app_url("/billing?tab=plans&checkout=success"), cancel_url=app_url("/billing?tab=plans&checkout=canceled"),
        idempotency_key=f"bs-sub-{org.id}-{plan_key}-{int(_now().timestamp() // 600)}",
    )
    return session["url"]


# ── Fulfilment (idempotent) ───────────────────────────────────────────────────


async def _lock_purchase(db: AsyncSession, purchase_id: uuid.UUID) -> Purchase | None:
    return (await db.execute(select(Purchase).where(Purchase.id == purchase_id).with_for_update())).scalar_one_or_none()


async def fulfill(db: AsyncSession, purchase_id: uuid.UUID, *, payment_intent: str | None, org_id: uuid.UUID) -> bool:
    """Grant what a paid purchase bought. Safe to call any number of times. Caller commits."""
    p = await _lock_purchase(db, purchase_id)
    if p is None or p.org_id != org_id:
        log.error("fulfill_purchase_mismatch", purchase_id=str(purchase_id), org_id=str(org_id))
        return False
    if p.status != "pending" and p.status != "failed":
        return False  # already paid (or refunded) — nothing to do
    # Claim it first: a concurrent duplicate sees "paid" and stops.
    res = await db.execute(update(Purchase).where(Purchase.id == p.id, Purchase.status.in_(("pending", "failed")))
                           .values(status="paid", fulfilled_at=_now(),
                                   stripe_payment_intent_id=payment_intent or p.stripe_payment_intent_id))
    if res.rowcount != 1:
        return False
    org = await db.get(Organization, p.org_id)
    if p.kind in ("credit_pack", "auto_recharge"):
        pack = catalog.CREDIT_PACKS.get(p.pack_key or "", {})
        label = pack.get("name", "Credit pack")
        await credits.add_lot(db, org, p.credits, source="purchased" if p.kind == "credit_pack" else "auto_recharge",
                              kind="purchase", note=f"{label} — {p.credits:,} credits" +
                              (" (auto-recharge)" if p.kind == "auto_recharge" else ""),
                              amount_paid_cents=p.amount_cents, purchase_id=p.id, stripe_ref=payment_intent)
    elif p.kind == "lookup_funds":
        grant = p.credits or p.amount_cents
        bonus = f" (${p.amount_cents / 100:,.2f} paid)" if grant > p.amount_cents else ""
        await add_lookup_funds(db, org, grant, kind="funding", note=f"Added ${grant / 100:,.2f}{bonus}",
                               purchase_id=p.id, stripe_ref=payment_intent)
    log.info("purchase_fulfilled", purchase_id=str(p.id), kind=p.kind, org_id=str(org.id))
    return True


async def mark_failed(db: AsyncSession, purchase_id: uuid.UUID, error: str) -> Purchase | None:
    p = await _lock_purchase(db, purchase_id)
    if p and p.status == "pending":
        p.status, p.error = "failed", error[:500]
    return p


# ── Lookup balance ledger (cents) ─────────────────────────────────────────────


async def add_lookup_funds(db: AsyncSession, org: Organization, amount_cents: int, *, kind: str, note: str,
                           purchase_id: uuid.UUID | None = None, stripe_ref: str | None = None,
                           created_by: uuid.UUID | None = None, lookup_id=None, batch_id=None) -> int:
    """Change the lookup balance (never below zero) and record it. Returns the amount actually applied. Caller commits."""
    cur = (await db.execute(select(Organization.lookup_balance_cents).where(Organization.id == org.id)
                            .with_for_update())).scalar_one() or 0
    new = max(0, cur + amount_cents)
    await db.execute(update(Organization).where(Organization.id == org.id).values(lookup_balance_cents=new))
    await db.refresh(org, ["lookup_balance_cents"])
    if new != cur or amount_cents == 0:
        db.add(LookupBalanceTransaction(org_id=org.id, amount_cents=new - cur, balance_after_cents=new, kind=kind,
                                        note=note[:500], stripe_ref=stripe_ref, purchase_id=purchase_id,
                                        created_by=created_by, lookup_id=lookup_id, batch_id=batch_id))
    return new - cur
