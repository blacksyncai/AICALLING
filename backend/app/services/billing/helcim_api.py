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


async def _request(method: str, path: str, *, json_body: dict | None = None) -> dict | list:
    if not ready():
        raise HelcimNotConfigured("Helcim isn't configured yet.")
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
        resp = await client.request(
            method, f"{API_BASE}{path}", json=json_body,
            headers={"api-token": settings.helcim_api_key, "accept": "application/json",
                     "content-type": "application/json"},
        )
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


async def initialize_checkout(*, amount_cents: int) -> dict:
    """A HelcimPay.js purchase session. Returns {"checkoutToken", "secretToken"} (valid 60 minutes)."""
    data = await _request("POST", "/helcim-pay/initialize", json_body={
        "paymentType": "purchase", "amount": round(amount_cents / 100, 2), "currency": CURRENCY,
    })
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
