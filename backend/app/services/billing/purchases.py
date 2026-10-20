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
from app.services.billing import catalog, credits, helcim_api, stripe_api

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


# ── Helcim (Canadian/other customers) ─────────────────────────────────────────
# One-time purchases only; subscriptions stay on Stripe. The purchase row is
# created up front (status pending) and fulfilled only when Helcim confirms the
# payment server-side — never from the browser returning from the hosted page.

def uses_helcim(org: Organization) -> bool:
    """Canadian/other accounts pay through Helcim when it's configured."""
    return bool(getattr(org, "billing_country", None) in ("CA", "OTHER")) and helcim_api.ready()


async def _helcim_checkout(db: AsyncSession, org: Organization, user_id: uuid.UUID, *, kind: str, item: dict,
                           credits_n: int, return_path: str) -> str:
    """Create a pending purchase and a Helcim hosted checkout for it. Returns the checkout URL."""
    purchase = Purchase(org_id=org.id, kind=kind, pack_key=item["key"], amount_cents=item["amount_cents"],
                        currency="cad", credits=credits_n, status="pending", created_by=user_id)
    db.add(purchase)
    await db.flush()
    owner = (await db.execute(
        select(User.email).join(Membership, Membership.user_id == User.id)
        .where(Membership.org_id == org.id, Membership.role == "owner").limit(1)
    )).scalar_one_or_none()
    meta = {"org_id": str(org.id), "purchase_id": str(purchase.id), "purchase_type": kind, "pack": item["key"]}
    checkout = await helcim_api.create_invoice_checkouts(
        amount_cents=item["amount_cents"], currency="cad",
        order_number=f"BS-{purchase.id.hex[:12].upper()}",
        customer_name=org.name, customer_email=owner,
        checkout_return_url=app_url(f"{return_path}?checkout=success&purchase={purchase.id}"),
        checkout_cancel_url=app_url(f"{return_path}?checkout=canceled"),
        metadata=meta,
    )
    url = (checkout.get("checkoutUrl") or (checkout.get("data") or {}).get("checkoutUrl")
           or (checkout.get("invoiceCheckout") or {}).get("checkoutUrl"))
    if not url:
        raise BillingError("Helcim didn't return a checkout URL.")
    purchase.stripe_checkout_session_id = f"helcim:{(checkout.get('id') or (checkout.get('data') or {}).get('id') or '')}"
    await db.commit()
    log.info("helcim_checkout_created", org_id=str(org.id), kind=kind, item=item["key"], purchase_id=str(purchase.id))
    return url


async def _helcim_plan_checkout(db: AsyncSession, org: Organization, user_id: uuid.UUID, *, plan_key: str) -> str:
    """Start a plan subscription through Helcim recurring payments (CA/OTHER accounts, USD)."""
    plan = catalog.PLANS[plan_key]
    from datetime import date
    owner = (await db.execute(
        select(User.email).join(Membership, Membership.user_id == User.id)
        .where(Membership.org_id == org.id, Membership.role == "owner").limit(1)
    )).scalar_one_or_none()
    checkout = await helcim_api.create_recurring_payment(
        amount_cents=plan["amount_cents"], currency="usd",
        order_number=f"BS-PLAN-{org.id.hex[:10].upper()}",
        customer_name=org.name, customer_email=owner,
        frequency="monthly", billing_date=date.today().strftime("%Y-%m-%d"),
        checkout_return_url=app_url(f"/billing?tab=plans&checkout=success&helcim_plan={plan_key}"),
        checkout_cancel_url=app_url("/billing?tab=plans&checkout=canceled"),
        metadata={"org_id": str(org.id), "purchase_type": "plan", "plan": plan_key},
    )
    url = (checkout.get("checkoutUrl") or (checkout.get("data") or {}).get("checkoutUrl")
           or (checkout.get("recurringPayment") or {}).get("checkoutUrl"))
    if not url:
        raise BillingError("Helcim didn't return a checkout URL.")
    log.info("helcim_plan_checkout_created", org_id=str(org.id), plan=plan_key)
    return url


async def fulfill_helcim_purchase(db: AsyncSession, purchase_id: uuid.UUID, *, org_id: uuid.UUID,
                                  helcim_ref: str | None = None) -> bool:
    """Grant a Helcim-paid purchase. Same safety rules as Stripe's fulfill(): idempotent, org-checked."""
    p = await _lock_purchase(db, purchase_id)
    if p is None or p.org_id != org_id:
        log.error("helcim_fulfill_mismatch", purchase_id=str(purchase_id), org_id=str(org_id))
        return False
    if p.status not in ("pending", "failed"):
        return False
    res = await db.execute(update(Purchase).where(Purchase.id == p.id, Purchase.status.in_(("pending", "failed")))
                           .values(status="paid", fulfilled_at=_now(),
                                   stripe_payment_intent_id=helcim_ref or p.stripe_payment_intent_id))
    if res.rowcount != 1:
        return False
    org = await db.get(Organization, p.org_id)
    if p.kind in ("credit_pack", "auto_recharge"):
        pack = catalog.CREDIT_PACKS.get(p.pack_key or "", {})
        label = pack.get("name", "Credit pack")
        await credits.add_lot(db, org, p.credits, source="purchased", kind="purchase",
                              note=f"{label} — {p.credits:,} credits (Helcim)",
                              amount_paid_cents=p.amount_cents, purchase_id=p.id, stripe_ref=helcim_ref)
    elif p.kind == "lookup_funds":
        grant = p.credits or p.amount_cents
        await add_lookup_funds(db, org, grant, kind="funding",
                               note=f"Added ${grant / 100:,.2f} (Helcim)",
                               purchase_id=p.id, stripe_ref=helcim_ref)
    log.info("helcim_purchase_fulfilled", purchase_id=str(p.id), kind=p.kind, org_id=str(org.id))
    return True


TRIAL_PACK_LIMIT = 1  # credit packs an account may buy before it's on a plan
TRIAL_PACK_USED = "You've used the one credit pack available before choosing a plan. Choose a BlackSync AI plan to buy more credits."


async def pack_access(db: AsyncSession, org: Organization) -> dict:
    """Can this account buy a credit pack? On a plan (paid or admin-assigned): always. Without one (trial):
    once — counting packs bought by hand or by auto-recharge. {allowed, on_plan, trial_packs_left, reason}."""
    from sqlalchemy import func

    from app.services import entitlements

    eff = await entitlements.effective(db, org)
    if org.unlimited_credits or eff["source"] != "no_plan":
        return {"allowed": True, "on_plan": True, "trial_packs_left": None, "reason": None}
    bought = (await db.execute(select(func.count()).select_from(Purchase).where(
        Purchase.org_id == org.id, Purchase.kind.in_(("credit_pack", "auto_recharge")),
        Purchase.fulfilled_at.is_not(None)))).scalar_one()
    left = max(0, TRIAL_PACK_LIMIT - int(bought))
    return {"allowed": left > 0, "on_plan": False, "trial_packs_left": left,
            "reason": None if left else TRIAL_PACK_USED}


async def checkout_credit_pack(db: AsyncSession, org: Organization, user_id: uuid.UUID, pack_key: str) -> str:
    pack = catalog.CREDIT_PACKS.get(pack_key)
    if not pack:
        raise BillingError("Unknown credit pack.")
    access = await pack_access(db, org)
    if not access["allowed"]:
        raise BillingError(access["reason"], 402)
    if uses_helcim(org):
        return await _helcim_checkout(db, org, user_id, kind="credit_pack", item=pack,
                                      credits_n=pack["credits"], return_path="/billing")
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
    if uses_helcim(org):
        return await _helcim_checkout(db, org, user_id, kind="lookup_funds", item=item,
                                      credits_n=catalog.lookup_grant_cents(item), return_path="/billing")
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
    if plan_key == "managed":
        raise BillingError("Managed is set up with our team — book a call with sales and we'll send your link.", 409)
    if not catalog.self_serve(plan_key):
        raise BillingError("That plan isn't offered any more.", 409)
    sub = await db.get(BillingSubscription, org.id)
    if sub and sub.status in ("active", "trialing", "past_due", "incomplete"):
        raise BillingError("This account already has a subscription — change plans instead.", 409)
    if uses_helcim(org):
        return await _helcim_plan_checkout(db, org, user_id, plan_key=plan_key)
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


async def managed_checkout(db: AsyncSession, org: Organization, admin_id: uuid.UUID, *, amount_cents: int,
                           credits: int) -> str:
    """Admin, after the discovery call: a Checkout link for this account's Managed subscription.

    The standard price is used for the list amount; a custom amount uses an inline price on the same
    Managed product (no new products). Paying it starts the subscription; the webhook then sets the
    Managed entitlements and flags the account for onboarding."""
    from app.models.billing import BillingSubscription

    sub = await db.get(BillingSubscription, org.id)
    if sub and sub.status in ("active", "trialing", "past_due") and sub.plan_key == "managed":
        raise BillingError("This account is already on Managed.", 409)
    if sub and sub.status in ("active", "trialing", "past_due", "incomplete"):
        raise BillingError("This account already has a subscription. Cancel it (or let it end) first, "
                           "or change it in the Stripe dashboard — nothing was created.", 409)
    info = (await catalog.resolve_prices()).get("managed") or {}
    if info.get("status") != "ok":
        raise BillingError("Create the Managed price in the Stripe catalog first (Admin → Billing → Stripe catalog).", 409)
    plan = catalog.PLANS["managed"]
    custom = amount_cents != plan["amount_cents"] or credits != plan["included_credits"]
    line = ({"price": info["price_id"], "quantity": 1} if amount_cents == plan["amount_cents"] else
            {"price_data": {"currency": "usd", "product": info["product"], "unit_amount": amount_cents,
                            "recurring": {"interval": "month"}}, "quantity": 1})
    cid = await ensure_customer(db, org)
    meta = {"org_id": str(org.id), "purchase_type": "plan", "plan": "managed", "credits": str(credits),
            "custom": "1" if custom else "0", "created_by_admin": str(admin_id)}
    session = await stripe_api.create_checkout_session(
        mode="subscription", customer=cid, line_items=[line], metadata=meta, client_reference_id=str(org.id),
        subscription_data={"metadata": meta},
        success_url=app_url("/billing?tab=plans&checkout=success"), cancel_url=app_url("/billing?tab=plans"),
        idempotency_key=f"bs-managed-{org.id}-{amount_cents}-{credits}-{int(_now().timestamp() // 600)}",
    )
    return session["url"]


def is_number_only(obj: dict | None) -> bool:
    """A $3.50/mo subscription for one phone number (bought without a plan) — never treated as a plan."""
    return ((obj or {}).get("metadata") or {}).get("purchase_type") == "phone_number"


async def checkout_phone_number(db: AsyncSession, org: Organization, user_id: uuid.UUID, number: str, *, carrier: str = "twilio") -> str:
    """No plan: buy one number on its own for the monthly add-on price (the number is bought once paid)."""
    try:
        price = await catalog.sellable_price(catalog.PHONE_ADDON["key"])
    except catalog.NotSellable as exc:
        raise BillingError(str(exc), 409)
    cid = await ensure_customer(db, org)
    meta = {"org_id": str(org.id), "purchase_type": "phone_number", "number": number, "user_id": str(user_id), "carrier": carrier}
    session = await stripe_api.create_checkout_session(
        mode="subscription", customer=cid, line_items=[{"price": price, "quantity": 1}],
        metadata=meta, client_reference_id=str(org.id), subscription_data={"metadata": meta},
        success_url=app_url("/phone-numbers?checkout=success"), cancel_url=app_url("/phone-numbers?checkout=canceled"),
        idempotency_key=f"bs-number-{org.id}-{carrier}-{number}-{int(_now().timestamp() // 600)}",
    )
    log.info("number_checkout_created", org_id=str(org.id), number=number)
    return session["url"]


async def provision_number(db: AsyncSession, org_id: uuid.UUID, number: str, subscription_id: str, *, carrier: str = "twilio") -> None:
    """After payment: buy the chosen number (or another in the same area code if it was taken meanwhile)."""
    from app.models.billing import PhoneNumber
    from app.services import telephony

    done = (await db.execute(select(PhoneNumber).where(PhoneNumber.stripe_subscription_id == subscription_id)))        .scalar_one_or_none()
    if done:
        return
    candidates = [number]
    digits = "".join(ch for ch in number if ch.isdigit())
    area = digits[1:4] if len(digits) == 11 else digits[:3]
    # A timeout may have succeeded remotely. Never buy a second SignalWire
    # number as compensation or silently substitute a different selection.
    if carrier != "signalwire":
        try:
            candidates += [n["number"] for n in await telephony.search_available(area, carrier=carrier)][:5]
        except Exception:
            pass
    last_error = None
    for cand in dict.fromkeys(candidates):
        try:
            row = await telephony.purchase(db, org_id, cand, carrier=carrier)
        except Exception as exc:
            last_error = exc
            continue
        row.stripe_subscription_id = subscription_id
        await db.commit()
        log.info("number_provisioned", org_id=str(org_id), number=cand, subscription=subscription_id)
        return
    log.error("number_provision_failed", org_id=str(org_id), number=number, error=str(last_error))
    raise RuntimeError(f"Couldn't buy a number for subscription {subscription_id}: {last_error}")


async def release_number_for(db: AsyncSession, subscription_id: str) -> None:
    from app.models.billing import PhoneNumber
    from app.services import telephony

    row = (await db.execute(select(PhoneNumber).where(PhoneNumber.stripe_subscription_id == subscription_id,
                                                      PhoneNumber.status == "active"))).scalar_one_or_none()
    if row:
        await telephony.release(db, row, return_to_twilio=True)
        log.info("number_released_subscription_ended", number=row.number, subscription=subscription_id)


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
