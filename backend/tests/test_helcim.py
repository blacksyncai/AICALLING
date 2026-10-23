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

    async def initialize_checkout(*, amount_cents, payment_type="purchase", customer=None):
        state["inits"].append(amount_cents)
        n = len(state["inits"])
        return {"checkoutToken": f"chk{n}-{uuid.uuid4().hex[:8]}", "secretToken": f"sec{n}"}

    async def get_transaction(tid):
        return state["txns"][str(tid)]

    state["subs"] = {}

    async def ensure_payment_plan(name, amount_cents):
        state.setdefault("plans", []).append((name, amount_cents))
        return 555

    async def create_subscription(*, customer_code, plan_id, amount_cents, activate, key):
        sid = int(uuid.uuid4().int % 10**8)
        state["subs"][sid] = {"id": sid, "status": "active", "timesBilled": state.get("billed_now", 1),
                              "hasFailedPayments": state.get("failed", "false"), "dateBilling": "2026-11-23",
                              "customerCode": customer_code, "recurringAmount": amount_cents / 100}
        return state["subs"][sid]

    async def get_subscription(sid):
        return state["subs"][int(sid)]

    async def delete_subscription(sid):
        state["subs"][int(sid)]["status"] = "inactive"

    for name, fn in [("initialize_checkout", initialize_checkout), ("get_transaction", get_transaction),
                     ("ensure_payment_plan", ensure_payment_plan), ("create_subscription", create_subscription),
                     ("get_subscription", get_subscription), ("delete_subscription", delete_subscription)]:
        monkeypatch.setattr(helcim_api, name, fn)
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


def _verify(tid, customer="CST9"):
    return {"transactionId": tid, "status": "APPROVED", "type": "verify", "amount": 0, "currency": "USD",
            "customerCode": customer}


def test_helcim_plan_subscribes_grants_credits_and_renews(client, make_client, stripe, helcim):
    import asyncio

    from app.database import AsyncSessionLocal
    from app.services.billing import catalog, subscriptions

    _, c = _account(client, make_client, "Calgary Co")
    c.post("/api/billing/country", json={"country": "CA"})
    r = c.post("/api/billing/plans/solo/checkout").json()
    pid = r["helcim"]["purchase_id"]
    assert not stripe.sessions
    helcim["txns"]["21"] = _verify(21)
    r = c.post("/api/billing/helcim/confirm", json={"purchase_id": pid, "data": _signed(_verify(21), "sec1")})
    assert r.status_code == 200, r.text
    plan = c.get("/api/billing/overview").json()
    assert plan["credits"]["balance"] == catalog.PLANS["solo"]["included_credits"]
    (sid, sub), = helcim["subs"].items()
    assert sub["customerCode"] == "CST9" and sub["recurringAmount"] == catalog.PLANS["solo"]["amount_cents"] / 100

    # Helcim bills month two: the sweep grants the next cycle once (running it again changes nothing).
    sub["timesBilled"] = 2
    async def sweep():
        async with AsyncSessionLocal() as db:
            await subscriptions.sweep_helcim(db)
    asyncio.run(sweep())
    asyncio.run(sweep())
    lots = [t for t in c.get("/api/billing/credits").json()["ledger"] if t["kind"] == "included"]
    assert len(lots) == 2

    # Plan changes go through support; cancel stops Helcim charging right away.
    assert c.post("/api/billing/plans/teams/preview").status_code == 409
    async def cancel():
        async with AsyncSessionLocal() as db:
            from app.models.billing import BillingSubscription
            row = (await db.execute(__import__("sqlalchemy").select(BillingSubscription).where(
                BillingSubscription.stripe_subscription_id == f"helcim:{sid}"))).scalar_one()
            await subscriptions.set_cancel(db, row.org_id, True)
    asyncio.run(cancel())
    assert sub["status"] == "inactive"


def test_helcim_plan_declined_first_month(client, make_client, stripe, helcim):
    helcim["failed"] = "true"
    _, c = _account(client, make_client, "Declined Co")
    c.post("/api/billing/country", json={"country": "OTHER"})
    pid = c.post("/api/billing/plans/solo/checkout").json()["helcim"]["purchase_id"]
    helcim["txns"]["31"] = _verify(31)
    r = c.post("/api/billing/helcim/confirm", json={"purchase_id": pid, "data": _signed(_verify(31), "sec1")})
    assert r.status_code == 402
    assert c.get("/api/billing/overview").json()["credits"]["balance"] == 0
    assert all(x["status"] == "inactive" for x in helcim["subs"].values())  # Helcim stops retrying
    # They can try again with another card.
    helcim["failed"] = "false"
    pid = c.post("/api/billing/plans/solo/checkout").json()["helcim"]["purchase_id"]
    helcim["txns"]["32"] = _verify(32)
    assert c.post("/api/billing/helcim/confirm", json={"purchase_id": pid, "data": _signed(_verify(32), "sec2")}).status_code == 200
