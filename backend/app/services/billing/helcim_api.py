"""Thin async wrapper around the Helcim API v1.

Canadian/other customers pay through Helcim instead of Stripe. Only one-time
purchases (credit packs, lookup funds) route here; subscriptions stay on Stripe.

The API key never leaves the backend. Helcim API v1 authenticates per-request
with an Api-Key header containing "{apiKeyId}:{apiKeySecret}".
"""
from __future__ import annotations

import asyncio
from functools import partial

import httpx
import structlog

from app.config import settings

log = structlog.get_logger(__name__)

API_BASE = "https://api.helcim.com/api/v1"


class HelcimNotConfigured(RuntimeError):
    pass


def ready() -> bool:
    return bool(settings.helcim_api_key)


def _auth_header() -> str:
    key = settings.helcim_api_key
    if not key:
        raise HelcimNotConfigured("Helcim isn't configured yet.")
    return key


async def _run(fn, *args, **kwargs):
    return await asyncio.to_thread(partial(fn, *args, **kwargs))


async def _request(method: str, path: str, *, json: dict | None = None) -> dict:
    if not ready():
        raise HelcimNotConfigured("Helcim isn't configured yet.")
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
        resp = await client.request(
            method, f"{API_BASE}{path}",
            headers={"Api-Key": _auth_header(), "Accept": "application/json"},
            json=json,
        )
        resp.raise_for_status()
        if not resp.content:
            return {}
        return resp.json()


async def verify_gateway() -> dict | None:
    """Confirm the key works (and capture the default gateway id). Returns None when not configured."""
    try:
        data = await _request("GET", "/configuration")
        return data
    except HelcimNotConfigured:
        return None
    except Exception as exc:
        log.warning("helcim_verify_failed", error=str(exc)[:200])
        return None


async def create_invoice_checkouts(*, amount_cents: int, currency: str, order_number: str,
                                   customer_name: str, customer_email: str | None,
                                   checkout_return_url: str, checkout_cancel_url: str,
                                   metadata: dict) -> dict:
    """A hosted-payment checkout for a one-time amount.

    Returns Helcim's response including the checkout URL. On success Helcim
    redirects the customer to checkout_return_url with a hash we verify in the
    webhook/return handling.
    """
    body = {
        "amount": f"{amount_cents / 100:.2f}",
        "currency": currency,
        "orderNumber": order_number,
        "checkoutReturnUrl": checkout_return_url,
        "checkoutCancelUrl": checkout_cancel_url,
        "customerName": customer_name,
        "customerEmail": customer_email or "",
        "metadata": metadata,
    }
    return await _request("POST", "/configuration/invoice-checkouts", json=body)


async def get_invoice_checkout(checkout_id: str) -> dict:
    """Poll a checkout's status server-side (used to verify completion)."""
    return await _request("GET", f"/invoice-checkouts/{checkout_id}")


async def create_recurring_payment(*, amount_cents: int, currency: str, order_number: str,
                                   customer_name: str, customer_email: str | None,
                                   frequency: str, billing_date: str,
                                   checkout_return_url: str, checkout_cancel_url: str,
                                   metadata: dict) -> dict:
    """A recurring (subscription) charge for plans — CAD/OTHER accounts, USD amounts.

    frequency: "monthly" etc. The first charge runs when the hosted checkout
    completes; entitlements are granted from the confirmed payment, never the
    browser redirect. NOTE: endpoint shape verified against Helcim API v1
    docs; isolate changes here.
    """
    body = {
        "amount": f"{amount_cents / 100:.2f}",
        "currency": currency,
        "orderNumber": order_number,
        "recurringFrequency": frequency,
        "billingDate": billing_date,
        "checkoutReturnUrl": checkout_return_url,
        "checkoutCancelUrl": checkout_cancel_url,
        "customerName": customer_name,
        "customerEmail": customer_email or "",
        "metadata": metadata,
    }
    return await _request("POST", "/recurring-payments", json=body)


async def get_recurring_payment(recurring_id: str) -> dict:
    """Poll a recurring payment's status server-side."""
    return await _request("GET", f"/recurring-payments/{recurring_id}")


async def cancel_recurring_payment(recurring_id: str) -> dict:
    """Stop a recurring plan charge (customer cancels/downgrades)."""
    return await _request("POST", f"/recurring-payments/{recurring_id}/cancel", json={})
