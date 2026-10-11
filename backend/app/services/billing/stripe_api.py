"""
Thin async wrapper around the Stripe SDK. Every Stripe call in the app goes
through here (tests replace these functions). The secret key never leaves the
backend; nothing returned here includes it.
"""

from __future__ import annotations

import asyncio
from functools import partial

import structlog

from app.config import settings

log = structlog.get_logger(__name__)


# Managed Payments (Stripe as merchant of record) needs 2025-03-31.basil or newer.
# Handlers read both the old and new shapes (period end on items, invoice.parent).
API_VERSION = "2025-03-31.basil"
# Software as a service — business use. Required on every product sold under Managed Payments.
SAAS_TAX_CODE = "txcd_10103001"


class StripeNotConfigured(RuntimeError):
    pass


def secret_key() -> str:
    """STRIPE_SECRET_KEY from the environment, else the key an admin connected in the portal."""
    from app.services import secret_store

    return settings.stripe_secret_key or secret_store.get("stripe_secret_key")


def webhook_secret() -> str:
    from app.services import secret_store

    return settings.stripe_webhook_secret or secret_store.get("stripe_webhook_secret")


def ready() -> bool:
    return bool(secret_key())


def _client():
    import stripe

    if not secret_key():
        raise StripeNotConfigured("Stripe isn't connected yet.")
    stripe.api_key = secret_key()
    stripe.api_version = API_VERSION
    stripe.max_network_retries = 2  # safe: the SDK sends idempotency keys on retried POSTs
    return stripe


async def _run(fn, *args, **kwargs):
    return await asyncio.to_thread(partial(fn, *args, **kwargs))


def _plain(obj) -> dict:
    return obj.to_dict_recursive() if hasattr(obj, "to_dict_recursive") else dict(obj)


# ── Catalog ───────────────────────────────────────────────────────────────────


async def prices_by_lookup_keys(keys: list[str]) -> dict[str, dict]:
    s = _client()
    out: dict[str, dict] = {}
    for i in range(0, len(keys), 10):  # Stripe accepts up to 10 lookup keys per request
        res = await _run(s.Price.list, lookup_keys=keys[i:i + 10], active=True, limit=100)
        for p in res.auto_paging_iter():
            out[p["lookup_key"]] = _plain(p)
    return out


async def retrieve_price(price_id: str) -> dict | None:
    s = _client()
    try:
        return _plain(await _run(s.Price.retrieve, price_id))
    except s.error.InvalidRequestError:
        return None


async def list_recurring_prices() -> list[dict]:
    s = _client()
    res = await _run(s.Price.list, active=True, type="recurring", limit=100, expand=["data.product"])
    return [_plain(p) for p in res.auto_paging_iter()]


async def create_price(*, name: str, amount_cents: int, lookup_key: str, recurring_interval: str | None) -> dict:
    """Admin-approved creation of a missing catalog item (product + price)."""
    s = _client()
    product = await _run(s.Product.create, name=name, metadata={"blacksync": "catalog"}, tax_code=SAAS_TAX_CODE,
                         idempotency_key=f"bs-product-{lookup_key}")
    kwargs = {"product": product["id"], "unit_amount": amount_cents, "currency": "usd", "lookup_key": lookup_key}
    if recurring_interval:
        kwargs["recurring"] = {"interval": recurring_interval}
    return _plain(await _run(s.Price.create, idempotency_key=f"bs-price-{lookup_key}", **kwargs))


# ── Customers, checkout, portal ───────────────────────────────────────────────


async def create_customer(*, org_id: str, name: str, email: str | None) -> str:
    s = _client()
    c = await _run(s.Customer.create, name=name, email=email or None, metadata={"org_id": org_id},
                   idempotency_key=f"bs-customer-{org_id}")
    return c["id"]


async def create_checkout_session(**kwargs) -> dict:
    s = _client()
    return _plain(await _run(s.checkout.Session.create, **kwargs))


async def create_portal_session(*, customer: str, return_url: str) -> str:
    s = _client()
    return (await _run(s.billing_portal.Session.create, customer=customer, return_url=return_url))["url"]


async def default_payment_method(customer: str) -> dict | None:
    """The customer's default card (from invoice settings, else the newest attached card)."""
    s = _client()
    cust = await _run(s.Customer.retrieve, customer, expand=["invoice_settings.default_payment_method"])
    pm = (cust.get("invoice_settings") or {}).get("default_payment_method")
    if not pm:
        pms = await _run(s.PaymentMethod.list, customer=customer, type="card", limit=1)
        pm = pms["data"][0] if pms["data"] else None
    if not pm:
        return None
    pm = _plain(pm)
    card = pm.get("card") or {}
    return {"id": pm["id"], "brand": card.get("brand"), "last4": card.get("last4"),
            "exp_month": card.get("exp_month"), "exp_year": card.get("exp_year")}


async def charge_off_session(*, customer: str, payment_method: str, amount_cents: int, idempotency_key: str,
                             metadata: dict, description: str) -> dict:
    """Charge a saved card without the customer present (auto-recharge). Returns the PaymentIntent."""
    s = _client()
    try:
        pi = await _run(s.PaymentIntent.create, amount=amount_cents, currency="usd", customer=customer,
                        payment_method=payment_method, off_session=True, confirm=True, metadata=metadata,
                        description=description, idempotency_key=idempotency_key)
        return _plain(pi)
    except s.error.CardError as exc:
        err = exc.error
        return {"id": getattr(err, "payment_intent", {}).get("id") if getattr(err, "payment_intent", None) else None,
                "status": "failed", "error": err.message if err else str(exc)}


# ── Subscriptions & invoices ──────────────────────────────────────────────────


async def retrieve_subscription(sub_id: str) -> dict:
    s = _client()
    return _plain(await _run(s.Subscription.retrieve, sub_id))


async def preview_plan_change(*, customer: str, subscription: dict, item_id: str, new_price: str) -> dict:
    s = _client()
    inv = await _run(s.Invoice.create_preview, customer=customer, subscription=subscription["id"],
                     subscription_details={"items": [{"id": item_id, "price": new_price}],
                                           "proration_behavior": "create_prorations"})
    return _plain(inv)


async def change_plan(*, subscription_id: str, item_id: str, new_price: str, idempotency_key: str) -> dict:
    s = _client()
    return _plain(await _run(s.Subscription.modify, subscription_id, items=[{"id": item_id, "price": new_price}],
                             proration_behavior="create_prorations", idempotency_key=idempotency_key))


async def set_cancel_at_period_end(subscription_id: str, cancel: bool) -> dict:
    s = _client()
    return _plain(await _run(s.Subscription.modify, subscription_id, cancel_at_period_end=cancel))


async def set_phone_quantity(*, subscription_id: str, item_id: str | None, price_id: str, quantity: int,
                             idempotency_key: str) -> dict:
    """Add/update/remove the phone-number add-on item. Returns the subscription."""
    s = _client()
    if item_id and quantity <= 0:
        items = [{"id": item_id, "deleted": True}]
    elif item_id:
        items = [{"id": item_id, "quantity": quantity}]
    elif quantity > 0:
        items = [{"price": price_id, "quantity": quantity}]
    else:
        return await retrieve_subscription(subscription_id)
    return _plain(await _run(s.Subscription.modify, subscription_id, items=items,
                             proration_behavior="create_prorations", idempotency_key=idempotency_key))


async def upcoming_invoice(customer: str, subscription_id: str) -> dict | None:
    s = _client()
    try:
        return _plain(await _run(s.Invoice.create_preview, customer=customer, subscription=subscription_id))
    except s.error.InvalidRequestError:
        return None


async def list_invoices(customer: str, limit: int = 24) -> list[dict]:
    s = _client()
    res = await _run(s.Invoice.list, customer=customer, limit=limit)
    return [_plain(i) for i in res["data"]]


async def list_payments(customer: str, limit: int = 24) -> list[dict]:
    s = _client()
    res = await _run(s.PaymentIntent.list, customer=customer, limit=limit)
    return [_plain(p) for p in res["data"]]


async def retrieve_charge(charge_id: str) -> dict:
    s = _client()
    return _plain(await _run(s.Charge.retrieve, charge_id))


def construct_event(payload: bytes, signature: str) -> dict:
    s = _client()
    if not webhook_secret():
        raise StripeNotConfigured("The Stripe webhook isn't set up yet.")
    return _plain(s.Webhook.construct_event(payload, signature, webhook_secret()))


# ── Connecting an account from the admin portal ───────────────────────────────


async def inspect_key(key: str) -> dict:
    """Validate a secret key against Stripe without touching the configured one."""
    import stripe

    stripe.api_version = API_VERSION

    acct = await _run(stripe.Account.retrieve, api_key=key)
    acct = _plain(acct)
    settings_ = acct.get("settings") or {}
    name = ((settings_.get("dashboard") or {}).get("display_name")
            or (acct.get("business_profile") or {}).get("name") or acct.get("email") or acct.get("id"))
    return {"id": acct.get("id"), "name": name, "charges_enabled": acct.get("charges_enabled")}


async def ensure_webhook(key: str, url: str, events: list[str]) -> dict:
    """Create our webhook endpoint (replacing one we created before for the same URL). Returns id + secret."""
    import stripe

    stripe.api_version = API_VERSION

    existing = await _run(stripe.WebhookEndpoint.list, api_key=key, limit=100)
    for ep in existing.auto_paging_iter():
        if ep["url"] == url and (ep.get("metadata") or {}).get("blacksync") == "true":
            await _run(stripe.WebhookEndpoint.delete, ep["id"], api_key=key)
    ep = await _run(stripe.WebhookEndpoint.create, api_key=key, url=url, enabled_events=events,
                    description="BlackSync billing", metadata={"blacksync": "true"})
    return {"id": ep["id"], "secret": ep["secret"]}


async def delete_webhook(key: str, endpoint_id: str) -> None:
    import stripe

    try:
        await _run(stripe.WebhookEndpoint.delete, endpoint_id, api_key=key)
    except Exception as exc:  # already gone is fine
        log.warning("stripe_webhook_delete_failed", error=str(exc))
