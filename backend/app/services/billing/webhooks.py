"""
Stripe webhook processing. The router verifies the signature; this module
deduplicates by event id and applies each event idempotently. The organization
always comes from our own records (purchase row or customer mapping) — metadata
is only used to find those records and is cross-checked against them.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Organization
from app.models.billing import AutoRecharge, CreditLot, Purchase, StripeEvent
from app.services.billing import credits, purchases, stripe_api, subscriptions

log = structlog.get_logger(__name__)

HANDLED = {
    "checkout.session.completed", "checkout.session.async_payment_succeeded", "checkout.session.async_payment_failed",
    "checkout.session.expired", "payment_intent.succeeded", "payment_intent.payment_failed",
    "customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted",
    "invoice.paid", "invoice.payment_failed", "charge.refunded", "charge.dispute.created", "charge.dispute.closed",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid(v) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(v))
    except (TypeError, ValueError):
        return None


async def process(db: AsyncSession, event: dict) -> str:
    """Apply one verified event. Returns processed | duplicate | ignored. Raises on failure (Stripe retries)."""
    evt_id, etype = event["id"], event["type"]
    row = await db.get(StripeEvent, evt_id)
    if row and row.status in ("processed", "ignored"):
        return "duplicate"
    if row is None:
        row = StripeEvent(id=evt_id, type=etype)
        db.add(row)
        await db.commit()
    if etype not in HANDLED:
        row.status, row.processed_at = "ignored", _now()
        await db.commit()
        return "ignored"
    obj = event["data"]["object"]
    try:
        org_id = await _dispatch(db, etype, obj)
        row = await db.get(StripeEvent, evt_id)
        row.status, row.org_id, row.processed_at, row.error = "processed", org_id, _now(), None
        await db.commit()
        return "processed"
    except Exception as exc:
        await db.rollback()
        row = await db.get(StripeEvent, evt_id)
        row.status, row.error = "failed", f"{exc.__class__.__name__}: {exc}"[:1000]
        await db.commit()
        log.error("stripe_event_failed", event_id=evt_id, type=etype, error=str(exc))
        raise


async def _dispatch(db: AsyncSession, etype: str, obj: dict) -> uuid.UUID | None:
    if etype.startswith("checkout.session."):
        return await _checkout(db, etype, obj)
    if etype.startswith("payment_intent."):
        return await _payment_intent(db, etype, obj)
    if etype.startswith("customer.subscription."):
        org_id = await purchases.org_for_customer(db, obj.get("customer"))
        if org_id:
            await subscriptions.sync_from_stripe(db, obj, org_id)
            await db.commit()
        return org_id
    if etype == "invoice.paid":
        org_id = await subscriptions.on_invoice_paid(db, obj)
        await db.commit()
        return org_id
    if etype == "invoice.payment_failed":
        org_id = await purchases.org_for_customer(db, obj.get("customer"))
        log.warning("invoice_payment_failed", org_id=str(org_id), invoice=obj.get("id"))
        return org_id
    if etype == "charge.refunded":
        return await _refund(db, obj)
    if etype.startswith("charge.dispute."):
        return await _dispute(db, etype, obj)
    return None


# ── One-time payments ─────────────────────────────────────────────────────────


async def _purchase_for_session(db: AsyncSession, session: dict) -> Purchase | None:
    pid = _uuid((session.get("metadata") or {}).get("purchase_id"))
    p = await db.get(Purchase, pid) if pid else None
    if p is None:
        p = (await db.execute(select(Purchase).where(Purchase.stripe_checkout_session_id == session["id"])))\
            .scalar_one_or_none()
    if p is None or p.stripe_checkout_session_id != session["id"]:
        return None
    owner = await purchases.org_for_customer(db, session.get("customer"))
    if owner != p.org_id:
        log.error("checkout_org_mismatch", purchase_id=str(p.id), session=session["id"])
        return None
    return p


async def _checkout(db: AsyncSession, etype: str, session: dict) -> uuid.UUID | None:
    if session.get("mode") == "subscription":
        org_id = await purchases.org_for_customer(db, session.get("customer"))
        if org_id and session.get("subscription"):
            sub = await stripe_api.retrieve_subscription(session["subscription"])
            await subscriptions.sync_from_stripe(db, sub, org_id)
            await db.commit()
        return org_id
    p = await _purchase_for_session(db, session)
    if p is None:
        return None
    pi = session.get("payment_intent")
    if isinstance(pi, dict):
        pi = pi.get("id")
    if etype == "checkout.session.completed" and session.get("payment_status") in ("paid", "no_payment_required"):
        await purchases.fulfill(db, p.id, payment_intent=pi, org_id=p.org_id)
    elif etype == "checkout.session.async_payment_succeeded":
        await purchases.fulfill(db, p.id, payment_intent=pi, org_id=p.org_id)
    elif etype == "checkout.session.async_payment_failed":
        await purchases.mark_failed(db, p.id, "The payment didn't go through.")
    elif etype == "checkout.session.expired":
        if p.status == "pending":
            p.status = "canceled"
    # completed + unpaid = delayed method (e.g. bank debit): wait for async_payment_succeeded.
    await db.commit()
    return p.org_id


async def _payment_intent(db: AsyncSession, etype: str, pi: dict) -> uuid.UUID | None:
    meta = pi.get("metadata") or {}
    if meta.get("purchase_type") != "auto_recharge":
        return None  # Checkout purchases are handled by checkout.session.* events
    p = await db.get(Purchase, _uuid(meta.get("purchase_id"))) if _uuid(meta.get("purchase_id")) else None
    if p is None or await purchases.org_for_customer(db, pi.get("customer")) != p.org_id:
        return None
    from app.services.billing import recharge

    if etype == "payment_intent.succeeded":
        await purchases.fulfill(db, p.id, payment_intent=pi["id"], org_id=p.org_id)
        await recharge.on_result(db, p, ok=True)
    else:
        err = ((pi.get("last_payment_error") or {}).get("message")) or "Payment failed"
        await purchases.mark_failed(db, p.id, err)
        await recharge.on_result(db, p, ok=False, error=err)
    await db.commit()
    return p.org_id


# ── Refunds & disputes ────────────────────────────────────────────────────────


async def _purchase_for_pi(db: AsyncSession, pi_id: str | None) -> Purchase | None:
    if not pi_id:
        return None
    return (await db.execute(select(Purchase).where(Purchase.stripe_payment_intent_id == pi_id).with_for_update()))\
        .scalar_one_or_none()


async def _claw_back(db: AsyncSession, p: Purchase, cents: int, *, kind: str, note: str, ref: str) -> int:
    """Take back what `cents` of this purchase bought, as far as it's unused. Returns units taken."""
    org = await db.get(Organization, p.org_id)
    if p.kind == "lookup_funds":
        grant = p.credits or p.amount_cents  # bonus balance is taken back in proportion
        want = min(grant, round(grant * cents / p.amount_cents)) if p.amount_cents else 0
        applied = await purchases.add_lookup_funds(db, org, -want, kind=kind, note=note, purchase_id=p.id, stripe_ref=ref)
        taken = -applied
        p.unrecovered += want - taken
        return taken
    want = round(p.credits * cents / p.amount_cents) if p.amount_cents else 0
    lot = (await db.execute(select(CreditLot).where(CreditLot.purchase_id == p.id))).scalars().first()
    taken = await credits.take_from_lot(db, org, lot, want, kind=kind, note=note, stripe_ref=ref) if lot else 0
    p.unrecovered += want - taken
    return taken


async def _refund(db: AsyncSession, charge: dict) -> uuid.UUID | None:
    p = await _purchase_for_pi(db, charge.get("payment_intent"))
    if p is None:
        return None
    total_refunded = int(charge.get("amount_refunded") or 0)
    delta = total_refunded - p.refunded_cents
    if delta > 0:
        await _claw_back(db, p, delta, kind="refund", note=f"Refund of ${delta / 100:,.2f}", ref=charge["id"])
        p.refunded_cents = total_refunded
        p.status = "refunded" if total_refunded >= p.amount_cents else "partially_refunded"
    await db.commit()
    return p.org_id


async def _dispute(db: AsyncSession, etype: str, dispute: dict) -> uuid.UUID | None:
    pi = dispute.get("payment_intent")
    if not pi and dispute.get("charge"):
        pi = (await stripe_api.retrieve_charge(dispute["charge"])).get("payment_intent")
    p = await _purchase_for_pi(db, pi)
    if p is None:
        return None
    if etype == "charge.dispute.created" and p.dispute_taken is None:
        open_cents = max(0, p.amount_cents - p.refunded_cents)
        p.dispute_taken = await _claw_back(db, p, open_cents, kind="dispute", note="Payment disputed", ref=dispute["id"])
        p.status = "disputed"
    elif etype == "charge.dispute.closed" and dispute.get("status") == "won" and p.dispute_taken:
        org = await db.get(Organization, p.org_id)
        if p.kind == "lookup_funds":
            await purchases.add_lookup_funds(db, org, p.dispute_taken, kind="dispute_won", note="Dispute won — funds restored",
                                             purchase_id=p.id, stripe_ref=dispute["id"])
        else:
            await credits.add_lot(db, org, p.dispute_taken, source="purchased", kind="dispute_won",
                                  note="Dispute won — credits restored", purchase_id=p.id, stripe_ref=dispute["id"],
                                  amount_paid_cents=round(p.amount_cents * p.dispute_taken / p.credits) if p.credits else None)
        p.dispute_taken, p.status = 0, "paid"
    await db.commit()
    return p.org_id


async def recent_failures(db: AsyncSession, limit: int = 50) -> dict:
    events = (await db.execute(select(StripeEvent).where(StripeEvent.status == "failed")
                               .order_by(StripeEvent.received_at.desc()).limit(limit))).scalars().all()
    failed = (await db.execute(select(Purchase, Organization.name).join(Organization, Organization.id == Purchase.org_id)
                               .where(Purchase.status == "failed").order_by(Purchase.created_at.desc()).limit(limit))).all()
    recharge_errors = (await db.execute(select(AutoRecharge, Organization.name).join(Organization, Organization.id == AutoRecharge.org_id)
                                        .where(AutoRecharge.last_error.is_not(None)))).all()
    return {
        "webhook_failures": [{"id": e.id, "type": e.type, "error": e.error, "org_id": str(e.org_id) if e.org_id else None,
                              "at": e.received_at.isoformat() if e.received_at else None} for e in events],
        "payment_failures": [{"id": str(p.id), "org_id": str(p.org_id), "org_name": name, "kind": p.kind,
                              "amount_cents": p.amount_cents, "error": p.error,
                              "at": p.created_at.isoformat() if p.created_at else None} for p, name in failed],
        "auto_recharge_errors": [{"org_id": str(r.org_id), "org_name": name, "error": r.last_error,
                                  "failures": r.consecutive_failures, "enabled": r.enabled} for r, name in recharge_errors],
    }
