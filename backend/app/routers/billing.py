"""
Billing & Usage — plans, calling credits, auto-recharge, the lead-lookup
balance, invoices and payment methods, plus the verified Stripe webhook and
the BlackSync admin billing controls.

Money-moving actions need an account owner/admin. Prices always come from the
server-side catalog verified against Stripe; the browser never sends amounts
that are trusted, and the organization always comes from the session.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.config import settings
from app.models.account import CreditTransaction, Organization
from app.models.agent import Agent
from app.models.billing import (
    AutoRecharge, BillingAudit, BillingSubscription, CallUsage, LookupBalanceTransaction, Purchase,
)
from app.services.auth import AdminDep, CtxDep, DbDep, ManagerDep
from app.services.billing import (
    catalog, credits, lookups, purchases, recharge, settings_store, stripe_api, subscriptions, webhooks,
)
from app.services.billing.purchases import BillingError

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/billing", tags=["billing"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).isoformat()


def _err(exc: Exception) -> HTTPException:
    if isinstance(exc, BillingError):
        return HTTPException(status_code=exc.status, detail=str(exc))
    if isinstance(exc, stripe_api.StripeNotConfigured):
        return HTTPException(status_code=409, detail="Payments aren't set up yet.")
    log.error("billing_provider_error", error=str(exc), error_type=exc.__class__.__name__)
    return HTTPException(status_code=502, detail="The payment provider had a problem. Please try again.")


async def _guard(coro):
    try:
        return await coro
    except HTTPException:
        raise
    except Exception as exc:
        raise _err(exc)


# ── Shared payloads ───────────────────────────────────────────────────────────


async def _plan_payload(db, org_id: uuid.UUID) -> dict:
    row = await db.get(BillingSubscription, org_id)
    if row is None:
        return {"status": "none", "plan_key": None, "name": None}
    plan = catalog.PLANS.get(row.plan_key or "")
    return {
        "status": row.status, "plan_key": row.plan_key,
        # A price we don't manage (e.g. an older plan) is shown as-is and left alone.
        "name": plan["name"] if plan else "Custom plan", "managed": bool(plan),
        "amount_cents": plan["amount_cents"] if plan else None,
        "included_credits": plan["included_credits"] if plan else None,
        "current_period_end": _iso(row.current_period_end), "cancel_at_period_end": row.cancel_at_period_end,
    }


def _tx(t: CreditTransaction) -> dict:
    # Exact amounts (thousandths of a credit) when recorded; whole credits on older rows.
    amount = t.amount_milli / 1000 if t.amount_milli is not None else t.amount
    after = t.balance_after_milli / 1000 if t.balance_after_milli is not None else t.balance_after
    return {"id": str(t.id), "amount": amount, "balance_after": after, "kind": t.kind, "note": t.note,
            "call_id": str(t.call_id) if t.call_id else None, "created_at": _iso(t.created_at)}


def _ltx(t: LookupBalanceTransaction) -> dict:
    return {"id": str(t.id), "amount_cents": t.amount_cents, "balance_after_cents": t.balance_after_cents,
            "kind": t.kind, "note": t.note, "created_at": _iso(t.created_at)}


def _purchase(p: Purchase) -> dict:
    return {"id": str(p.id), "kind": p.kind, "pack_key": p.pack_key, "amount_cents": p.amount_cents,
            "credits": p.credits, "status": p.status, "error": p.error, "refunded_cents": p.refunded_cents,
            "created_at": _iso(p.created_at), "fulfilled_at": _iso(p.fulfilled_at)}


async def _catalog_payload() -> dict:
    prices = await catalog.resolve_prices()

    def ok(key):
        return prices.get(key, {}).get("status") == "ok"

    return {
        "stripe_ready": stripe_api.ready(),
        "plans": [{**{k: v for k, v in catalog.PLANS[k].items() if k not in ("price_env",)}, "available": ok(k)}
                  for k in catalog.PLAN_ORDER],
        "packs": [{**catalog.CREDIT_PACKS[k], "available": ok(k),
                   "cents_per_credit": catalog.CREDIT_PACKS[k]["amount_cents"] / catalog.CREDIT_PACKS[k]["credits"]}
                  for k in catalog.PACK_ORDER],
        "lookup_funds": [{**catalog.LOOKUP_FUNDS[k], "available": ok(k)} for k in catalog.FUNDS_ORDER],
        "phone_addon": {**catalog.PHONE_ADDON, "available": ok(catalog.PHONE_ADDON["key"])},
    }


# ── Customer: overview & catalog ──────────────────────────────────────────────


@router.get("/overview")
async def overview(ctx: CtxDep, db: DbDep):
    org = ctx.org
    breakdown = await credits.breakdown(db, org)
    since = datetime.now(timezone.utc) - timedelta(days=30)
    used_30d = (await db.execute(select(func.coalesce(func.sum(CallUsage.credits_deducted), 0)).where(
        CallUsage.org_id == org.id, CallUsage.created_at >= since))).scalar_one()
    seconds_30d = (await db.execute(select(func.coalesce(func.sum(CallUsage.connected_seconds), 0)).where(
        CallUsage.org_id == org.id, CallUsage.created_at >= since))).scalar_one()
    txs = (await db.execute(select(CreditTransaction).where(CreditTransaction.org_id == org.id)
                            .order_by(CreditTransaction.created_at.desc()).limit(8))).scalars().all()
    ltxs = (await db.execute(select(LookupBalanceTransaction).where(LookupBalanceTransaction.org_id == org.id)
                             .order_by(LookupBalanceTransaction.created_at.desc()).limit(8))).scalars().all()
    activity = sorted(
        [{"type": "credits", **_tx(t)} for t in txs] + [{"type": "lookup", **_ltx(t)} for t in ltxs],
        key=lambda a: a["created_at"] or "", reverse=True)[:10]
    ar = await db.get(AutoRecharge, org.id)
    return {
        "plan": await _plan_payload(db, org.id),
        "credits": {**breakdown, "used_30d": int(used_30d), "minutes_30d": round(int(seconds_30d) / 60, 1),
                    "estimated_value_cents": round(breakdown["balance"] * breakdown["cents_per_credit"])},
        "lookups": await lookups.status(db, org),
        "phones": await subscriptions.phone_summary(db, org.id),
        "auto_recharge": {"enabled": bool(ar and ar.enabled), "threshold": ar.threshold if ar else None,
                          "pack_key": ar.pack_key if ar else None, "last_error": ar.last_error if ar else None},
        "activity": activity,
        "stripe_ready": stripe_api.ready(),
        "can_manage": ctx.can_manage,
    }


@router.get("/catalog")
async def get_catalog(ctx: CtxDep, db: DbDep):
    return {**await _catalog_payload(), "current_plan": await _plan_payload(db, ctx.org.id)}


@router.get("/rates")
async def rates(ctx: CtxDep, db: DbDep):
    """Credit rate per model (for the agent editor) and what a credit is worth to this account."""
    cfg = await settings_store.get_all(db)
    return {"model_rates": cfg["model_credit_rates"], "premium_voice_surcharge": cfg["premium_voice_surcharge"],
            "phone_minute_fee": cfg["phone_minute_fee"], "free_test_minutes": cfg["free_test_minutes"],
            "cents_per_credit": round(await credits.cents_per_credit(db, ctx.org.id), 4)}


@router.get("/agents/{agent_id}/rate")
async def agent_rate(agent_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Agent not found")
    rate = await credits.rate_for_agent(db, agent)
    cpc = await credits.cents_per_credit(db, ctx.org.id)
    return {"credits_per_minute": rate, "approx_cents_per_minute": round(rate * cpc, 2),
            "premium_voice": await credits._is_premium(agent)}


# ── Plans ─────────────────────────────────────────────────────────────────────


class PlanChange(BaseModel):
    confirm: bool = False


@router.post("/plans/{plan_key}/checkout")
async def plan_checkout(plan_key: str, ctx: ManagerDep, db: DbDep):
    url = await _guard(purchases.checkout_plan(db, ctx.org, ctx.user.id, plan_key))
    return {"url": url}


@router.post("/plans/{plan_key}/preview")
async def plan_preview(plan_key: str, ctx: ManagerDep, db: DbDep):
    return await _guard(subscriptions.preview_change(db, ctx.org.id, plan_key))


@router.post("/plans/{plan_key}/change")
async def plan_change(plan_key: str, body: PlanChange, ctx: ManagerDep, db: DbDep):
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Please confirm the plan change.")
    await _guard(subscriptions.change_plan(db, ctx.org.id, plan_key, ctx.user.id))
    return await _plan_payload(db, ctx.org.id)


@router.post("/subscription/cancel")
async def cancel_subscription(ctx: ManagerDep, db: DbDep):
    await _guard(subscriptions.set_cancel(db, ctx.org.id, True))
    return await _plan_payload(db, ctx.org.id)


@router.post("/subscription/resume")
async def resume_subscription(ctx: ManagerDep, db: DbDep):
    await _guard(subscriptions.set_cancel(db, ctx.org.id, False))
    return await _plan_payload(db, ctx.org.id)


# ── Calling credits ───────────────────────────────────────────────────────────


class PackIn(BaseModel):
    pack: str


@router.get("/credits")
async def credits_page(ctx: CtxDep, db: DbDep, limit: int = 50):
    breakdown = await credits.breakdown(db, ctx.org)
    txs = (await db.execute(select(CreditTransaction).where(CreditTransaction.org_id == ctx.org.id)
                            .order_by(CreditTransaction.created_at.desc()).limit(min(limit, 200)))).scalars().all()
    since = datetime.now(timezone.utc) - timedelta(days=30)
    by_agent = (await db.execute(
        select(CallUsage.agent_id, Agent.name, func.count(), func.sum(CallUsage.connected_seconds),
               func.sum(CallUsage.credits_deducted))
        .outerjoin(Agent, Agent.id == CallUsage.agent_id)
        .where(CallUsage.org_id == ctx.org.id, CallUsage.created_at >= since)
        .group_by(CallUsage.agent_id, Agent.name))).all()
    return {
        **breakdown, "ledger": [_tx(t) for t in txs],
        "usage_by_agent": [{"agent_id": str(a) if a else None, "agent_name": n or "Deleted agent", "calls": c,
                            "minutes": round((s or 0) / 60, 1), "credits": int(cr or 0)} for a, n, c, s, cr in by_agent],
    }


@router.post("/credits/checkout")
async def credits_checkout(body: PackIn, ctx: ManagerDep, db: DbDep):
    url = await _guard(purchases.checkout_credit_pack(db, ctx.org, ctx.user.id, body.pack))
    return {"url": url}


@router.get("/purchases/{purchase_id}")
async def purchase_status(purchase_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    p = await db.get(Purchase, purchase_id)
    if not p or p.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Purchase not found")
    return _purchase(p)


# ── Auto-recharge ─────────────────────────────────────────────────────────────


class AutoRechargeIn(BaseModel):
    enabled: bool
    pack_key: str
    threshold: int = Field(ge=1, le=100000)
    monthly_limit_cents: int = Field(ge=0, le=10_000_000)
    consent: bool = False


async def _card(db, org_id) -> dict | None:
    cid = await purchases.customer_id(db, org_id)
    if not cid or not stripe_api.ready():
        return None
    try:
        return await stripe_api.default_payment_method(cid)
    except Exception:
        return None


@router.get("/auto-recharge")
async def get_auto_recharge(ctx: CtxDep, db: DbDep):
    row = await recharge.get_config(db, ctx.org.id)
    return {**recharge.config_to_dict(row, await recharge.month_to_date_cents(db, ctx.org.id), await _card(db, ctx.org.id)),
            "max_monthly_cents": await settings_store.get(db, "auto_recharge_max_monthly_cents")}


@router.put("/auto-recharge")
async def put_auto_recharge(body: AutoRechargeIn, ctx: ManagerDep, db: DbDep):
    row = await _guard(recharge.update_config(db, ctx.org, ctx.user.id, **body.model_dump()))
    return recharge.config_to_dict(row, await recharge.month_to_date_cents(db, ctx.org.id), await _card(db, ctx.org.id))


# ── Lead lookup balance ───────────────────────────────────────────────────────


class FundsIn(BaseModel):
    amount: str


@router.get("/lookups")
async def lookups_page(ctx: CtxDep, db: DbDep):
    txs = (await db.execute(select(LookupBalanceTransaction).where(LookupBalanceTransaction.org_id == ctx.org.id)
                            .order_by(LookupBalanceTransaction.created_at.desc()).limit(50))).scalars().all()
    return {**await lookups.status(db, ctx.org), "ledger": [_ltx(t) for t in txs]}


@router.post("/lookups/checkout")
async def lookups_checkout(body: FundsIn, ctx: ManagerDep, db: DbDep):
    url = await _guard(purchases.checkout_lookup_funds(db, ctx.org, ctx.user.id, body.amount))
    return {"url": url}


# ── Invoices & payment methods ────────────────────────────────────────────────


@router.get("/invoices")
async def invoices(ctx: CtxDep, db: DbDep):
    ours = (await db.execute(select(Purchase).where(Purchase.org_id == ctx.org.id)
                             .order_by(Purchase.created_at.desc()).limit(50))).scalars().all()
    out: dict = {"purchases": [_purchase(p) for p in ours], "invoices": [], "card": None,
                 "has_billing_profile": False, "stripe_ready": stripe_api.ready()}
    cid = await purchases.customer_id(db, ctx.org.id)
    if not cid or not stripe_api.ready():
        return out
    out["has_billing_profile"] = True
    try:
        out["card"] = await stripe_api.default_payment_method(cid)
        out["invoices"] = [{
            "id": i["id"], "number": i.get("number"), "status": i.get("status"), "total_cents": i.get("total"),
            "currency": i.get("currency"), "created": _iso(datetime.fromtimestamp(i["created"], tz=timezone.utc)),
            "hosted_url": i.get("hosted_invoice_url"), "pdf": i.get("invoice_pdf"),
        } for i in await stripe_api.list_invoices(cid)]
    except Exception as exc:
        log.warning("invoices_fetch_failed", org_id=str(ctx.org.id), error=str(exc))
        out["error"] = "Couldn't load invoices from the payment provider right now."
    return out


@router.post("/portal")
async def portal(ctx: ManagerDep, db: DbDep):
    return {"url": await _guard(subscriptions.portal_url(db, ctx.org.id))}


# ── Stripe webhook ────────────────────────────────────────────────────────────


@router.post("/webhook")
async def stripe_webhook(request: Request, db: DbDep):
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = stripe_api.construct_event(payload, signature)
    except stripe_api.StripeNotConfigured:
        raise HTTPException(status_code=503, detail="Webhook not configured")
    except Exception:
        log.warning("stripe_webhook_bad_signature")
        raise HTTPException(status_code=400, detail="Invalid signature")
    try:
        result = await webhooks.process(db, event)
    except Exception:
        raise HTTPException(status_code=500, detail="Processing failed")
    log.info("stripe_webhook", event_id=event["id"], type=event["type"], result=result)
    return {"received": True, "result": result}


# ── Admin ─────────────────────────────────────────────────────────────────────


class LookupAdjust(BaseModel):
    amount_cents: int = Field(ge=-10_000_000, le=10_000_000)
    reason: str = Field(min_length=3, max_length=500)


class BillingSettingsIn(BaseModel):
    property_lookup_price_cents: int | None = Field(default=None, ge=1, le=10_000)
    clear_lookup_price: bool = False
    lookup_charge_policy: str | None = Field(default=None, pattern="^(match|completed)$")
    lookup_free_daily: int | None = Field(default=None, ge=0, le=1000)
    model_credit_rates: dict[str, float] | None = None
    premium_voice_surcharge: float | None = Field(default=None, ge=0, le=10)
    included_phone_numbers: int | None = Field(default=None, ge=0, le=100)
    phone_minute_fee: float | None = Field(default=None, ge=0, le=5)
    free_test_minutes: int | None = Field(default=None, ge=0, le=600)
    min_ai_billable_seconds: int | None = Field(default=None, ge=0, le=120)
    auto_recharge_max_monthly_cents: int | None = Field(default=None, ge=0, le=10_000_000)
    reason: str = Field(default="Updated billing settings", max_length=500)


class CreatePriceIn(BaseModel):
    confirm: bool = False


@admin_router.get("/billing/orgs/{org_id}")
async def admin_org_billing(org_id: uuid.UUID, _: AdminDep, db: DbDep):
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Account not found")
    since = datetime.now(timezone.utc) - timedelta(days=30)
    usage = (await db.execute(select(func.count(), func.coalesce(func.sum(CallUsage.connected_seconds), 0),
                                     func.coalesce(func.sum(CallUsage.credits_deducted), 0),
                                     func.coalesce(func.sum(CallUsage.shortfall), 0))
                              .where(CallUsage.org_id == org.id, CallUsage.created_at >= since))).one()
    lookup_spend = (await db.execute(select(func.coalesce(func.sum(LookupBalanceTransaction.amount_cents), 0)).where(
        LookupBalanceTransaction.org_id == org.id, LookupBalanceTransaction.kind == "lookup",
        LookupBalanceTransaction.created_at >= since))).scalar_one()
    ps = (await db.execute(select(Purchase).where(Purchase.org_id == org.id).order_by(Purchase.created_at.desc())
                           .limit(25))).scalars().all()
    audits = (await db.execute(select(BillingAudit).where(BillingAudit.org_id == org.id)
                               .order_by(BillingAudit.created_at.desc()).limit(25))).scalars().all()
    ar = await db.get(AutoRecharge, org.id)
    return {
        "plan": await _plan_payload(db, org.id),
        "credits": await credits.breakdown(db, org),
        "lookups": await lookups.status(db, org),
        "phones": await subscriptions.phone_summary(db, org.id),
        "usage_30d": {"calls": usage[0], "minutes": round(int(usage[1]) / 60, 1), "credits": int(usage[2]),
                      "shortfall": int(usage[3]), "lookup_spend_cents": -int(lookup_spend)},
        "purchases": [_purchase(p) for p in ps],
        "auto_recharge": recharge.config_to_dict(ar, await recharge.month_to_date_cents(db, org.id), None) if ar else None,
        "audit": [{"admin_id": str(a.admin_id) if a.admin_id else None, "target": a.target, "previous": a.previous,
                   "adjustment": a.adjustment, "new": a.new, "reason": a.reason, "at": _iso(a.created_at)} for a in audits],
        "stripe_customer": await purchases.customer_id(db, org.id),
    }


@admin_router.post("/orgs/{org_id}/lookup-balance")
async def admin_lookup_adjust(org_id: uuid.UUID, body: LookupAdjust, admin: AdminDep, db: DbDep):
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Account not found")
    if body.amount_cents == 0:
        raise HTTPException(status_code=400, detail="Enter a non-zero amount.")
    before = org.lookup_balance_cents or 0
    applied = await purchases.add_lookup_funds(db, org, body.amount_cents, kind="adjustment", note=body.reason,
                                               created_by=admin.id)
    db.add(BillingAudit(admin_id=admin.id, org_id=org.id, target="lookup_balance", previous=str(before),
                        adjustment=f"{applied:+d}", new=str(org.lookup_balance_cents or 0), reason=body.reason))
    await db.commit()
    return {"balance_cents": org.lookup_balance_cents or 0, "applied_cents": applied}


@admin_router.get("/billing/settings")
async def admin_billing_settings(_: AdminDep, db: DbDep):
    return {**await settings_store.get_all(db), "stripe_ready": stripe_api.ready(),
            "webhook_ready": bool(stripe_api.webhook_secret()),
            "included_credits_rollover": settings.included_credits_rollover}


@admin_router.patch("/billing/settings")
async def admin_update_billing_settings(body: BillingSettingsIn, admin: AdminDep, db: DbDep):
    changes = body.model_dump(exclude_none=True, exclude={"reason", "clear_lookup_price"})
    if body.clear_lookup_price:
        changes["property_lookup_price_cents"] = None
    if "model_credit_rates" in changes:
        rates = {k.strip(): float(v) for k, v in changes["model_credit_rates"].items() if k.strip()}
        if not rates or any(v <= 0 or v > 20 for v in rates.values()):
            raise HTTPException(status_code=400, detail="Rates must be between 0 and 20 credits per minute.")
        changes["model_credit_rates"] = rates
    for key, value in changes.items():
        await settings_store.set_value(db, key, value, admin.id, reason=body.reason or "Updated billing settings")
    await db.commit()
    return await admin_billing_settings(admin, db)


@admin_router.get("/billing/catalog")
async def admin_catalog(_: AdminDep):
    prices = await _guard(catalog.resolve_prices(force=True))
    return {"stripe_ready": stripe_api.ready(), "items": [
        {"kind": kind, "key": item["key"], "name": item["name"], "amount_cents": item["amount_cents"],
         "lookup_key": item["lookup_key"], "type": expected, **prices.get(item["key"], {})}
        for kind, item, expected in catalog.all_items()]}


@admin_router.post("/billing/catalog/{key}/create")
async def admin_create_price(key: str, body: CreatePriceIn, admin: AdminDep):
    """Create a missing Stripe product+price — only after an admin explicitly confirms."""
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Confirm creating this price in Stripe.")
    found = next(((kind, item, exp) for kind, item, exp in catalog.all_items() if item["key"] == key), None)
    if not found:
        raise HTTPException(status_code=404, detail="Unknown catalog item")
    kind, item, expected = found
    status = (await _guard(catalog.resolve_prices(force=True))).get(key, {}).get("status")
    if status != "missing":
        raise HTTPException(status_code=409, detail="This item already has a Stripe price — nothing was created.")
    price = await _guard(stripe_api.create_price(
        name=f"BlackSync {item['name']}" if kind != "lookup_funds" else f"BlackSync lead lookup funds {item['name']}",
        amount_cents=item["amount_cents"], lookup_key=item["lookup_key"],
        recurring_interval=item.get("interval") if expected == "recurring" else None))
    catalog.invalidate()
    log.info("stripe_price_created", key=key, price=price.get("id"), by=str(admin.id))
    return {"price_id": price.get("id")}


@admin_router.get("/billing/failures")
async def admin_failures(_: AdminDep, db: DbDep):
    return await webhooks.recent_failures(db)


# ── Admin: connect Stripe from the portal ─────────────────────────────────────


class StripeConnectIn(BaseModel):
    secret_key: str = Field(min_length=20, max_length=300)


def _mask(key: str) -> str:
    return f"{key[:8]}…{key[-4:]}" if key else ""


@admin_router.get("/billing/stripe")
async def stripe_connection(_: AdminDep):
    from app.services import secret_store

    key = stripe_api.secret_key()
    return {
        "connected": bool(key),
        "source": "environment" if settings.stripe_secret_key else ("portal" if key else None),
        "mode": "live" if "_live_" in key else ("test" if key else None),
        "key_hint": _mask(key),
        "account_name": secret_store.get("stripe_account_name") or None,
        "webhook_ready": bool(stripe_api.webhook_secret()),
        "webhook_url": purchases.app_url("/api/billing/webhook"),
        "can_store": secret_store.available(),
    }


@admin_router.post("/billing/stripe")
async def connect_stripe(body: StripeConnectIn, admin: AdminDep, db: DbDep):
    """Check the key with Stripe, create the webhook endpoint, then store both encrypted."""
    from app.services import secret_store

    key = body.secret_key.strip()
    if not key.startswith(("sk_live_", "sk_test_", "rk_live_", "rk_test_")):
        raise HTTPException(status_code=400, detail="That doesn't look like a Stripe secret key (it starts with sk_live_ or sk_test_).")
    if settings.stripe_secret_key:
        raise HTTPException(status_code=409, detail="Stripe is set by the STRIPE_SECRET_KEY environment variable — change it there.")
    if not secret_store.available():
        raise HTTPException(status_code=503, detail="Secure storage isn't set up on the server (SECRETS_ENCRYPTION_KEY).")
    try:
        account = await stripe_api.inspect_key(key)
    except Exception as exc:
        log.warning("stripe_connect_rejected", error_type=exc.__class__.__name__)
        raise HTTPException(status_code=400, detail="Stripe rejected that key. Copy the secret key again from Developers → API keys.")
    webhook_note = None
    try:
        hook = await stripe_api.ensure_webhook(key, purchases.app_url("/api/billing/webhook"), sorted(webhooks.HANDLED))
        await secret_store.put(db, "stripe_webhook_secret", hook["secret"])
        await secret_store.put(db, "stripe_webhook_id", hook["id"])
    except Exception as exc:
        log.warning("stripe_webhook_create_failed", error=str(exc))
        webhook_note = "The key works, but the webhook couldn't be created automatically (the key may lack webhook permission)."
    await secret_store.put(db, "stripe_secret_key", key)
    await secret_store.put(db, "stripe_account_name", str(account.get("name") or ""))
    db.add(BillingAudit(admin_id=admin.id, target="pricing", previous="", adjustment="stripe_connected",
                        new=_mask(key)[:64], reason=f"Stripe connected ({account.get('id')})"))
    await db.commit()
    catalog.invalidate()
    log.info("stripe_connected", account=account.get("id"), mode="live" if "_live_" in key else "test", by=str(admin.id))
    return {**await stripe_connection(admin), "warning": webhook_note}


@admin_router.delete("/billing/stripe")
async def disconnect_stripe(admin: AdminDep, db: DbDep):
    from app.services import secret_store

    if settings.stripe_secret_key:
        raise HTTPException(status_code=409, detail="Stripe is set by the STRIPE_SECRET_KEY environment variable — remove it there.")
    key, hook_id = secret_store.get("stripe_secret_key"), secret_store.get("stripe_webhook_id")
    if key and hook_id:
        await stripe_api.delete_webhook(key, hook_id)
    for name in ("stripe_secret_key", "stripe_webhook_secret", "stripe_webhook_id", "stripe_account_name"):
        await secret_store.remove(db, name)
    db.add(BillingAudit(admin_id=admin.id, target="pricing", previous=_mask(key)[:64], adjustment="stripe_disconnected",
                        new="", reason="Stripe disconnected"))
    await db.commit()
    catalog.invalidate()
    return await stripe_connection(admin)
