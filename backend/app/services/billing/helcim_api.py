"""Helcim API v2 (https://devdocs.helcim.com) for Canadian/other customers' one-time purchases.

Flow (HelcimPay.js): the backend initializes a checkout and gets a checkoutToken (shown to the
browser, which opens Helcim's payment modal) and a secretToken (kept server-side). When the modal
reports success, the browser posts the transaction data back; we confirm it against the
secretToken hash and Helcim's own record of the transaction before granting anything.
The API token never leaves the backend.
"""
from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import structlog

from app.config import settings

log = structlog.get_logger(__name__)

API_BASE = "https://api.helcim.com/v2"
CURRENCY = "USD"  # our prices are USD and the Helcim account settles in USD


class HelcimNotConfigured(RuntimeError):
    pass


class HelcimError(RuntimeError):
    pass


def ready() -> bool:
    return bool(settings.helcim_api_key)


async def _request(method: str, path: str, *, json_body: dict | None = None, idempotency_key: str = "") -> dict | list:
    if not ready():
        raise HelcimNotConfigured("Helcim isn't configured yet.")
    headers = {"api-token": settings.helcim_api_key, "accept": "application/json", "content-type": "application/json"}
    if idempotency_key:
        headers["idempotency-key"] = idempotency_key
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
        resp = await client.request(method, f"{API_BASE}{path}", json=json_body, headers=headers)
    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except ValueError:
            detail = resp.text[:200]
        log.warning("helcim_api_error", path=path, status=resp.status_code, detail=str(detail)[:300])
        raise HelcimError(f"Helcim error (HTTP {resp.status_code}).")
    return resp.json() if resp.content else {}


async def connection_test() -> bool:
    try:
        await _request("GET", "/connection-test")
        return True
    except (HelcimNotConfigured, HelcimError, httpx.HTTPError):
        return False


async def initialize_checkout(*, amount_cents: int, payment_type: str = "purchase",
                              customer: dict | None = None) -> dict:
    """A HelcimPay.js session. Returns {"checkoutToken", "secretToken"} (valid 60 minutes).
    payment_type "verify" with a customer saves the card as that new customer's default (for subscriptions)."""
    body = {"paymentType": payment_type, "amount": round(amount_cents / 100, 2), "currency": CURRENCY}
    if customer:
        body["customerRequest"] = customer
    data = await _request("POST", "/helcim-pay/initialize", json_body=body)
    if not isinstance(data, dict) or not data.get("checkoutToken") or not data.get("secretToken"):
        raise HelcimError("Helcim didn't return a checkout.")
    return data


async def get_transaction(transaction_id: str | int) -> dict:
    data = await _request("GET", f"/card-transactions/{int(transaction_id)}")
    if isinstance(data, list):
        data = data[0] if data else {}
    return data


def hash_matches(data: dict, secret_token: str, given_hash: str) -> bool:
    """HelcimPay.js integrity check: sha256(JSON-encoded transaction data + secretToken) == hash.
    Helcim's samples encode compactly (PHP's json_encode escapes "/" and non-ASCII); accept either."""
    if not (secret_token and given_hash):
        return False
    variants = {json.dumps(data, separators=(",", ":"), ensure_ascii=False),
                json.dumps(data, separators=(",", ":")),
                json.dumps(data, separators=(",", ":")).replace("/", "\\/")}
    return any(hmac.compare_digest(hashlib.sha256((v + secret_token).encode()).hexdigest(), given_hash)
               for v in variants)


def _data(res):
    return res.get("data", res) if isinstance(res, dict) else res


async def ensure_payment_plan(name: str, amount_cents: int) -> int:
    """Our monthly plan in Helcim (reused by name). Returns its paymentPlanId."""
    amount = round(amount_cents / 100, 2)
    for plan in _data(await _request("GET", "/payment-plans")) or []:
        if plan.get("name") == name and plan.get("status") == "active" and abs(float(plan.get("recurringAmount") or 0) - amount) < 0.005:
            return int(plan["id"])
    created = _data(await _request("POST", "/payment-plans", json_body={"paymentPlans": [{
        "name": name, "type": "subscription", "status": "active", "currency": CURRENCY, "recurringAmount": amount,
        "billingPeriod": "monthly", "billingPeriodIncrements": 1, "dateBilling": "Sign-up", "termType": "forever",
        "paymentMethod": "card", "taxType": "no_tax"}]}))
    return int(created[0]["id"])


async def create_subscription(*, customer_code: str, plan_id: int, amount_cents: int, activate: str, key: str) -> dict:
    """Subscribe a customer (charges their default card on the activation date, then monthly)."""
    created = _data(await _request("POST", "/subscriptions", idempotency_key=key, json_body={"subscriptions": [{
        "customerCode": customer_code, "paymentPlanId": plan_id, "dateActivated": activate,
        "recurringAmount": round(amount_cents / 100, 2), "paymentMethod": "card"}]}))
    return created[0] if isinstance(created, list) else created


async def get_subscription(sub_id: str | int) -> dict:
    return _data(await _request("GET", f"/subscriptions/{int(sub_id)}")) or {}


async def delete_subscription(sub_id: str | int) -> None:
    await _request("DELETE", f"/subscriptions/{int(sub_id)}")
