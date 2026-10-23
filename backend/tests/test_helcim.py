"""Canada/other accounts pay one-time purchases through HelcimPay.js; US stays on Stripe."""

import hashlib
import json
import uuid

import pytest

from app.config import settings
from app.services.billing import helcim_api
from tests.test_billing import _account, stripe  # noqa: F401  (fixture)


@pytest.fixture
def helcim(monkeypatch):
    state = {"txns": {}, "inits": []}
    monkeypatch.setattr(settings, "helcim_api_key", "test-token", raising=False)

    async def initialize_checkout(*, amount_cents):
        state["inits"].append(amount_cents)
        n = len(state["inits"])
        return {"checkoutToken": f"chk{n}-{uuid.uuid4().hex[:8]}", "secretToken": f"sec{n}"}

    async def get_transaction(tid):
        return state["txns"][str(tid)]

    monkeypatch.setattr(helcim_api, "initialize_checkout", initialize_checkout)
    monkeypatch.setattr(helcim_api, "get_transaction", get_transaction)
    return state


def _signed(data: dict, secret: str) -> dict:
    return {"data": data, "hash": hashlib.sha256((json.dumps(data, separators=(",", ":")) + secret).encode()).hexdigest()}


def _txn(tid, amount, status="APPROVED"):
    return {"transactionId": tid, "status": status, "type": "purchase", "amount": amount, "currency": "USD"}


def test_canada_gets_helcim_and_us_gets_stripe(client, make_client, stripe, helcim):
    _, ca = _account(client, make_client, "Maple Co")
    ca.post("/api/billing/country", json={"country": "CA"})
    r = ca.post("/api/billing/lookups/checkout", json={"amount": "lookup_5"}).json()
    assert r["helcim"]["checkout_token"].startswith("chk1-") and "url" not in r
    assert helcim["inits"] == [500] and not stripe.sessions

    _, us = _account(client, make_client, "Eagle Co")
    us.post("/api/billing/country", json={"country": "US"})
    assert "url" in us.post("/api/billing/lookups/checkout", json={"amount": "lookup_5"}).json()


def test_helcim_confirm_grants_once_and_only_when_approved(client, make_client, stripe, helcim):
    _, c = _account(client, make_client, "Toronto Co")
    c.post("/api/billing/country", json={"country": "OTHER"})
    pid = c.post("/api/billing/lookups/checkout", json={"amount": "lookup_5"}).json()["helcim"]["purchase_id"]

    helcim["txns"]["11"] = _txn(11, 5.00, status="DECLINED")
    r = c.post("/api/billing/helcim/confirm", json={"purchase_id": pid, "data": _signed(_txn(11, 5.00), "sec1")})
    assert r.status_code == 402 and c.get("/api/billing/lookups").json()["balance_cents"] == 0

    helcim["txns"]["12"] = _txn(12, 1.00)  # wrong amount
    assert c.post("/api/billing/helcim/confirm", json={"purchase_id": pid, "data": _signed(_txn(12, 1.00), "sec1")}).status_code == 402

    helcim["txns"]["13"] = _txn(13, 5.00)
    r = c.post("/api/billing/helcim/confirm", json={"purchase_id": pid, "data": _signed(_txn(13, 5.00), "sec1")})
    assert r.status_code == 200 and r.json()["status"] == "paid"
    assert c.get("/api/billing/lookups").json()["balance_cents"] == 500
    # Replays don't grant twice, and the same transaction can't pay for a second purchase.
    assert c.post("/api/billing/helcim/confirm", json={"purchase_id": pid, "data": _signed(_txn(13, 5.00), "sec1")}).status_code == 200
    pid2 = c.post("/api/billing/lookups/checkout", json={"amount": "lookup_5"}).json()["helcim"]["purchase_id"]
    assert c.post("/api/billing/helcim/confirm", json={"purchase_id": pid2, "data": _signed(_txn(13, 5.00), "sec2")}).status_code == 409
    assert c.get("/api/billing/lookups").json()["balance_cents"] == 500

    # Another account can't confirm this account's purchase.
    _, other = _account(client, make_client, "Other Co")
    assert other.post("/api/billing/helcim/confirm", json={"purchase_id": pid2, "data": _signed(_txn(14, 5.00), "sec2")}).status_code == 404


def test_hash_matches_compact_json():
    data = {"transactionId": "1", "amount": "5.00", "cardHolderName": "José / Q"}
    for encoded in (json.dumps(data, separators=(",", ":"), ensure_ascii=False), json.dumps(data, separators=(",", ":"))):
        h = hashlib.sha256((encoded + "s").encode()).hexdigest()
        assert helcim_api.hash_matches(data, "s", h)
    assert not helcim_api.hash_matches(data, "s", "bad")
