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


def _lookup(item: dict) -> str | None:
    return (item.get("price") or {}).get("lookup_key")


def _is_phone_item(item: dict) -> bool:
    return _lookup(item) == catalog.PHONE_ADDON["lookup_key"]


def _is_agent_item(item: dict) -> bool:
    return _lookup(item) == catalog.AGENT_ADDON["lookup_key"]


def _plan_item(sub: dict) -> dict | None:
    return next((i for i in _items(sub) if _lookup(i) not in catalog.ADDON_LOOKUP_KEYS), None)


def _period_end(sub: dict, item: dict | None = None) -> datetime | None:
    # Newer API versions moved the period onto subscription items.
    return _ts(sub.get("current_period_end") or (item or {}).get("current_period_end"))


async def sync_from_stripe(db: AsyncSession, sub: dict, org_id: uuid.UUID) -> BillingSubscription:
    """Write Stripe's view of the subscription onto our mirror row. Caller commits."""
    prices = await catalog.resolve_prices()
    item = _plan_item(sub)
    price_id = ((item or {}).get("price") or {}).get("id")
    phone = next((i for i in _items(sub) if _is_phone_item(i)), None)
    agents = next((i for i in _items(sub) if _is_agent_item(i)), None)
    meta = sub.get("metadata") or {}
    row = await db.get(BillingSubscription, org_id)
    if row is None:
        row = BillingSubscription(org_id=org_id, stripe_subscription_id=sub["id"])
        db.add(row)
    elif row.stripe_subscription_id != sub["id"] and row.status in LIVE and sub.get("status") not in LIVE:
        return row  # an old, ended subscription mustn't overwrite the live one
    row.stripe_subscription_id = sub["id"]
    row.price_id = price_id
    row.plan_key = catalog.plan_for_price(price_id, prices, meta)
    row.status = sub.get("status") or "incomplete"
    row.current_period_end = _period_end(sub, item)
    row.cancel_at_period_end = bool(sub.get("cancel_at_period_end"))
    row.phone_item_id = phone["id"] if phone else None
    row.phone_quantity = int(phone.get("quantity") or 0) if phone else 0
    row.agent_item_id = agents["id"] if agents else None
    row.agent_slots = int(agents.get("quantity") or 0) if agents else 0
    custom = str(meta.get("credits") or "")
    row.custom_credits = int(custom) if row.plan_key == "managed" and custom.isdigit() else None
    if row.plan_key == "managed" and row.status in ("active", "trialing"):
        org = await db.get(Organization, org_id)
        if org is not None and not org.managed_onboarding:
            org.managed_onboarding = "needed"  # BlackSync's team sets the account up by hand
            log.info("managed_onboarding_flagged", org_id=str(org_id))
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
    if credits_n is None:
        row = await db.get(BillingSubscription, org.id)
        credits_n = row.custom_credits if row is not None and row.custom_credits is not None else None
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
    if ((sub.get("metadata") or {}).get("purchase_type")) == "phone_number":
        return org_id  # a number bought on its own — not a plan, no included credits
    row = await sync_from_stripe(db, sub, org_id)
    if row.plan_key:
        org = await db.get(Organization, org_id)
        await grant_included(db, org, plan_key=row.plan_key, invoice_id=inv["id"],
                             period_end=row.current_period_end)
    return org_id


# ── Customer actions ──────────────────────────────────────────────────────────


def is_helcim(row: BillingSubscription | None) -> bool:
    return bool(row and (row.stripe_subscription_id or "").startswith("helcim:"))


async def _live_sub(db: AsyncSession, org_id: uuid.UUID) -> tuple[BillingSubscription, dict]:
    row = await db.get(BillingSubscription, org_id)
    if row is None or row.status not in LIVE:
        raise BillingError("There's no active subscription on this account.", 409)
    if is_helcim(row):
        raise BillingError("Your plan is billed through Helcim. Message support and we'll change it for you.", 409)
    sub = await stripe_api.retrieve_subscription(row.stripe_subscription_id)
    return row, sub


def _check_target(row: BillingSubscription, plan_key: str) -> None:
    if plan_key not in catalog.PLANS:
        raise BillingError("Unknown plan.")
    if row.plan_key == plan_key:
        raise BillingError("You're already on this plan.")
    if plan_key == "managed":
        raise BillingError("Managed is set up with our team — book a call with sales and we'll send your link.", 409)
    if not catalog.self_serve(plan_key):
        raise BillingError("That plan isn't offered any more.", 409)
    if row.plan_key == "managed" or (row.custom_credits is not None):
        raise BillingError("Your Managed plan is changed with your BlackSync contact — reach out and we'll update it.", 409)


async def preview_change(db: AsyncSession, org_id: uuid.UUID, plan_key: str) -> dict:
    row, sub = await _live_sub(db, org_id)
    _check_target(row, plan_key)
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
    lost = []
    if not upgrade:
        org = await db.get(Organization, org_id)
        lost = await downgrade_effects(db, org, plan_key, row.agent_slots or 0)
    return {
        "downgrade_effects": lost,
        "plan": plan_key, "upgrade": upgrade, "amount_due_now_cents": max(0, proration) if upgrade else 0,
        "proration_cents": proration, "next_invoice_total_cents": inv.get("total"),
        "next_period_end": row.current_period_end.isoformat() if row.current_period_end else None,
        "new_monthly_cents": new_plan["amount_cents"],
        "included_credits_now": max(0, new_plan["included_credits"] - (old_plan or {}).get("included_credits", 0))
        if upgrade else 0,
    }


async def change_plan(db: AsyncSession, org_id: uuid.UUID, plan_key: str, user_id: uuid.UUID) -> BillingSubscription:
    row, sub = await _live_sub(db, org_id)
    _check_target(row, plan_key)
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
    row = await db.get(BillingSubscription, org_id)
    if is_helcim(row) and row.status in LIVE:
        return await _cancel_helcim(db, row, cancel)
    row, sub = await _live_sub(db, org_id)
    updated = await stripe_api.set_cancel_at_period_end(sub["id"], cancel)
    row = await sync_from_stripe(db, updated, org_id)
    await db.commit()
    return row


async def downgrade_effects(db: AsyncSession, org: Organization, plan_key: str, slots: int) -> list[str]:
    """Plain-language list of what goes over the limit on a lower plan (nothing is deleted)."""
    from app.services import entitlements

    lim = catalog.plan_limits(plan_key) or {}
    used = await entitlements.usage(db, org)
    out = []
    if lim.get("agents") is not None and used["agents"] > lim["agents"] + slots:
        out.append(f"You have {used['agents']} active agents; {catalog.PLANS[plan_key]['name']} allows "
                   f"{lim['agents'] + slots}. Extra agents are kept but can't call until you pause some.")
    if lim.get("seats") is not None and used["seats"] > lim["seats"]:
        out.append(f"You have {used['seats']} team members and invites; the plan includes {lim['seats']}. "
                   "Everyone keeps access, but you can't invite more.")
    if lim.get("crm") is not None and used["crm"] > lim["crm"]:
        out.append(f"You have {used['crm']} CRMs connected; the plan includes {lim['crm']}. "
                   "They stay connected, but you can't add more.")
    if lim.get("numbers") is not None and used["numbers"] > lim["numbers"]:
        out.append(f"{used['numbers'] - lim['numbers']} of your numbers will be billed at "
                   f"${catalog.PHONE_ADDON['amount_cents'] / 100:.2f}/mo each.")
    for flag, label in (("workflows", "Workflow automations (speed-to-lead, Slack, Sheets, scheduled imports)"),
                        ("advanced_workflows", "Webhooks and the API"), ("team_reporting", "Team analytics")):
        if not lim.get(flag):
            prev = catalog.plan_limits((await db.get(BillingSubscription, org.id)).plan_key) or {}
            if prev.get(flag):
                out.append(f"{label} turn off.")
    return out


# ── Extra agent slots ─────────────────────────────────────────────────────────


async def preview_agent_slots(db: AsyncSession, org_id: uuid.UUID, quantity: int) -> dict:
    from app.services import entitlements

    row, sub = await _live_sub(db, org_id)
    if row.plan_key is None:
        raise BillingError("Extra agent slots are added to a BlackSync plan — start a plan first.", 409)
    try:
        await catalog.sellable_price(catalog.AGENT_ADDON["key"])
    except catalog.NotSellable as exc:
        raise BillingError(str(exc), 409)
    current = row.agent_slots or 0
    org = await db.get(Organization, org_id)
    eff = await entitlements.effective(db, org)
    active = len(await entitlements.active_agent_ids(db, org_id))
    new_limit = (eff["limits"]["agents"] - current + quantity) if eff["limits"].get("agents") is not None else None
    return {"current": current, "quantity": quantity, "unit_cents": catalog.AGENT_ADDON["amount_cents"],
            "monthly_change_cents": (quantity - current) * catalog.AGENT_ADDON["amount_cents"],
            "new_monthly_addon_cents": quantity * catalog.AGENT_ADDON["amount_cents"],
            "agent_limit": new_limit, "active_agents": active,
            "over_after": bool(new_limit is not None and active > new_limit),
            "proration": "Adding slots charges the prorated amount for the rest of this billing period now. "
                         "Removing slots credits the unused time to your next invoice.",
            "next_period_end": row.current_period_end.isoformat() if row.current_period_end else None}


async def set_agent_slots(db: AsyncSession, org_id: uuid.UUID, quantity: int, user_id: uuid.UUID) -> BillingSubscription:
    """Change the extra-agent-slot quantity. Removing slots never deletes or pauses agents."""
    row, sub = await _live_sub(db, org_id)
    if row.plan_key is None:
        raise BillingError("Extra agent slots are added to a BlackSync plan — start a plan first.", 409)
    if row.status == "past_due":
        raise BillingError("Your last payment didn't go through — update your card before adding slots.", 402)
    if quantity == (row.agent_slots or 0):
        return row
    try:
        price = await catalog.sellable_price(catalog.AGENT_ADDON["key"])
    except catalog.NotSellable as exc:
        raise BillingError(str(exc), 409)
    adding = quantity > (row.agent_slots or 0)
    try:
        updated = await stripe_api.set_item_quantity(
            subscription_id=sub["id"], item_id=row.agent_item_id, price_id=price, quantity=quantity,
            idempotency_key=f"bs-agents-{org_id}-{quantity}-{uuid.uuid4().hex[:6]}",
            payment_behavior="error_if_incomplete" if adding else None)
    except stripe_api.StripeNotConfigured:
        raise
    except Exception as exc:
        if not adding:
            raise
        log.warning("agent_slot_charge_failed", org_id=str(org_id), error=str(exc))
        raise BillingError("The charge for the extra slot didn't go through. Check your card under Billing.", 402)
    row = await sync_from_stripe(db, updated, org_id)
    await db.commit()
    log.info("agent_slots_changed", org_id=str(org_id), slots=quantity, by=str(user_id))
    return row


# ── Phone number add-on ───────────────────────────────────────────────────────


async def phone_summary(db: AsyncSession, org_id: uuid.UUID) -> dict:
    from app.services import entitlements
    from app.services.telephony import active_numbers

    org = await db.get(Organization, org_id)
    included = await entitlements.included_numbers(db, org) if org else 0
    # Numbers bought on their own already have their own $3.50/mo subscription.
    active = len([n for n in await active_numbers(db, org_id) if not n.stripe_subscription_id])
    row = await db.get(BillingSubscription, org_id)
    subscribed = bool(row and row.status in LIVE)
    return {"active": active, "included": included if subscribed else 0,
            "billable": max(0, active - included) if subscribed else 0,
            "billed_quantity": row.phone_quantity if row else 0,
            "unit_cents": catalog.PHONE_ADDON["amount_cents"], "subscribed": subscribed}


async def sync_phone_quantity(db: AsyncSession, org_id: uuid.UUID) -> None:
    """Bill max(0, active numbers − included) on the subscription. No subscription = nothing billed."""
    row = await db.get(BillingSubscription, org_id)
    if row is None or row.status not in LIVE or not stripe_api.ready() or is_helcim(row):
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


async def charge_for_new_number(db: AsyncSession, org_id: uuid.UUID) -> bool:
    """Before buying a number past the plan's included ones: raise the add-on quantity and collect the
    prorated charge now. Raises BillingError if the payment fails (the number isn't bought). Returns
    whether the quantity changed (so a failed purchase can undo it with sync_phone_quantity)."""
    row = await db.get(BillingSubscription, org_id)
    if row is None or row.status not in LIVE or not stripe_api.ready() or is_helcim(row):
        return False
    summary = await phone_summary(db, org_id)
    wanted = max(0, summary["active"] + 1 - summary["included"])
    if wanted <= row.phone_quantity:
        return False
    if row.status == "past_due":
        raise BillingError("Your last payment didn't go through — update your card before adding a number.", 402)
    try:
        price = await catalog.sellable_price(catalog.PHONE_ADDON["key"])
    except catalog.NotSellable as exc:
        raise BillingError(str(exc), 409)
    try:
        sub = await stripe_api.set_phone_quantity(
            subscription_id=row.stripe_subscription_id, item_id=row.phone_item_id, price_id=price, quantity=wanted,
            idempotency_key=f"bs-phones-{org_id}-{wanted}-{uuid.uuid4().hex[:6]}", payment_behavior="error_if_incomplete")
    except stripe_api.StripeNotConfigured:
        raise
    except Exception as exc:
        log.warning("number_charge_failed", org_id=str(org_id), error=str(exc))
        raise BillingError("The charge for the extra number didn't go through. Check your card under Billing.", 402)
    await sync_from_stripe(db, sub, org_id)
    await db.commit()
    return True


async def portal_url(db: AsyncSession, org_id: uuid.UUID) -> str:
    from app.services.billing.purchases import app_url

    cid = await customer_id(db, org_id)
    if not cid:
        raise BillingError("Add a payment first — there's no billing profile yet.", 409)
    return await stripe_api.create_portal_session(customer=cid, return_url=app_url("/billing?tab=invoices"))


# ── Helcim subscriptions (Canada / other) ─────────────────────────────────────
# Helcim charges the saved card monthly on its own. We read its subscription to keep our row in step and grant
# each paid cycle's included credits once (keyed by Helcim's timesBilled).


def _helcim_date(v: str | None) -> datetime | None:
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc) if v else None
    except ValueError:
        return None


async def sync_helcim(db: AsyncSession, org: Organization, row: BillingSubscription, sub: dict | None = None) -> None:
    from app.services.billing import helcim_api

    now = datetime.now(timezone.utc)
    if row.cancel_at_period_end:
        if row.current_period_end is None or row.current_period_end <= now:
            row.status = "canceled"
        return
    sub = sub or await helcim_api.get_subscription(row.stripe_subscription_id.removeprefix("helcim:"))
    times = int(sub.get("timesBilled") or 0)
    if str(sub.get("status") or "").lower() != "active":
        row.status = "canceled"
    elif str(sub.get("hasFailedPayments") or "").lower() == "true":
        row.status = "past_due"
    elif times >= 1:
        row.status = "active"
        row.current_period_end = _helcim_date(sub.get("dateBilling")) or row.current_period_end
        if row.plan_key in catalog.PLANS:
            await grant_included(db, org, plan_key=row.plan_key, invoice_id=f"helcim:sub:{sub.get('id')}:{times}",
                                 period_end=row.current_period_end)
    else:
        row.status = "incomplete"  # the first charge hasn't run yet
    await db.flush()


async def _cancel_helcim(db: AsyncSession, row: BillingSubscription, cancel: bool) -> BillingSubscription:
    from app.services.billing import helcim_api

    if not cancel:
        if row.cancel_at_period_end:
            raise BillingError("A canceled Helcim plan can't be resumed. Start a new plan when this one ends.", 409)
        return row
    await helcim_api.delete_subscription(row.stripe_subscription_id.removeprefix("helcim:"))  # no more charges
    row.cancel_at_period_end = True  # keeps the plan until the paid month runs out
    await db.commit()
    log.info("helcim_plan_canceled", org_id=str(row.org_id))
    return row


async def sweep_helcim(db: AsyncSession) -> int:
    """Renewals, failed payments and ended plans for every Helcim subscription."""
    rows = (await db.execute(select(BillingSubscription).where(
        BillingSubscription.stripe_subscription_id.like("helcim:%"),
        BillingSubscription.status.in_(("active", "past_due", "incomplete", "trialing"))))).scalars().all()
    for row in rows:
        try:
            org = await db.get(Organization, row.org_id)
            await sync_helcim(db, org, row)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            log.warning("helcim_sync_failed", org_id=str(row.org_id), error=str(exc)[:200])
    return len(rows)


def start_helcim_sweeper():
    import asyncio

    from app.database import AsyncSessionLocal
    from app.services.billing import helcim_api

    async def loop():
        while True:
            if helcim_api.ready():
                try:
                    async with AsyncSessionLocal() as db:
                        await sweep_helcim(db)
                except Exception as exc:
                    log.warning("helcim_sweep_failed", error=str(exc)[:200])
            await asyncio.sleep(3600)

    return asyncio.create_task(loop())
