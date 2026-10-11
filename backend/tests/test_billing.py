"""Billing & Usage: catalog, checkout + webhooks, credits engine, plans, auto-recharge, lookups, refunds, admin."""

import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.config import settings
from app.services.billing import catalog, recharge, stripe_api
from tests.test_accounts import _login, _new_account


# ── Fake Stripe ───────────────────────────────────────────────────────────────


def _price(pid, item, typ):
    return {"id": pid, "unit_amount": item["amount_cents"], "currency": "usd", "type": typ, "active": True,
            "lookup_key": item["lookup_key"], "product": "prod_" + item["key"]}


@pytest.fixture
def stripe(monkeypatch):
    st = SimpleNamespace(customers={}, sessions=[], subs={}, charges=[], card={"id": "pm_1", "brand": "visa", "last4": "4242",
                         "exp_month": 1, "exp_year": 2030}, charge_status="succeeded", missing=set(), quantity_calls=[])
    prices = {}
    for kind, item, typ in catalog.all_items():
        if item["key"] in st.missing:
            continue
        prices[item["lookup_key"]] = _price(item.get("price_id") or f"price_{item['key']}", item, typ)

    async def prices_by_lookup_keys(keys):
        return {k: v for k, v in prices.items() if k in keys and v["lookup_key"] not in st.missing}

    async def retrieve_price(pid):
        return next((p for p in prices.values() if p["id"] == pid and p["lookup_key"] not in st.missing), None)

    async def create_customer(*, org_id, name, email):
        cid = f"cus_{org_id[:8]}"
        st.customers[cid] = org_id
        return cid

    async def create_checkout_session(**kw):
        sid = f"cs_{uuid.uuid4().hex[:10]}"
        st.sessions.append({"id": sid, **kw})
        return {"id": sid, "url": f"https://checkout.stripe.test/{sid}"}

    async def default_payment_method(cid):
        return st.card

    async def charge_off_session(**kw):
        st.charges.append(kw)
        pi = f"pi_{uuid.uuid4().hex[:10]}"
        if st.charge_status == "succeeded":
            return {"id": pi, "status": "succeeded"}
        return {"id": pi, "status": "failed", "error": "Your card was declined."}

    async def retrieve_subscription(sid):
        return st.subs[sid]

    async def preview_plan_change(*, customer, subscription, item_id, new_price):
        return {"total": 29600, "lines": {"data": [{"amount": 15000, "proration": True}]}}

    async def change_plan(*, subscription_id, item_id, new_price, idempotency_key):
        sub = st.subs[subscription_id]
        sub["items"]["data"][0]["price"] = {"id": new_price, "lookup_key": "x"}
        return sub

    async def set_cancel_at_period_end(sid, cancel):
        st.subs[sid]["cancel_at_period_end"] = cancel
        return st.subs[sid]

    async def set_phone_quantity(*, subscription_id, item_id, price_id, quantity, idempotency_key):
        st.quantity_calls.append(quantity)
        sub = st.subs[subscription_id]
        sub["items"]["data"] = [i for i in sub["items"]["data"] if (i.get("price") or {}).get("lookup_key") != catalog.PHONE_ADDON["lookup_key"]]
        if quantity > 0:
            sub["items"]["data"].append({"id": "si_phone", "quantity": quantity,
                                         "price": {"id": price_id, "lookup_key": catalog.PHONE_ADDON["lookup_key"]}})
        return sub

    def construct_event(payload, signature):
        if signature != "good":
            raise ValueError("bad signature")
        return json.loads(payload)

    for name, fn in list(locals().items()):
        if callable(fn) and hasattr(stripe_api, name) and name not in ("st", "prices"):
            monkeypatch.setattr(stripe_api, name, fn)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_fake")
    catalog.invalidate()
    st.prices = prices
    yield st
    catalog.invalidate()


def _account(client, make_client, name, credits=0):
    """A fresh account whose starter agent runs at 1 credit/min (gpt-4.1-mini)."""
    org, email = _new_account(client, name=name, credits=credits)
    c = _login(make_client, email)
    for a in c.get("/api/agents/").json():
        c.patch(f"/api/agents/{a['id']}", json={"llm_model": "gpt-4.1-mini"})
    return org, c


_n = [0]


def _hook(client, etype, obj, evt_id=None):
    _n[0] += 1
    evt = {"id": evt_id or f"evt_{uuid.uuid4().hex[:12]}", "type": etype, "data": {"object": obj}}
    return client.post("/api/billing/webhook", content=json.dumps(evt), headers={"stripe-signature": "good"})


def _paid_session(stripe, session_id=None, **over):
    s = stripe.sessions[-1] if session_id is None else next(x for x in stripe.sessions if x["id"] == session_id)
    return {"id": s["id"], "mode": "payment", "payment_status": "paid", "customer": s["customer"],
            "metadata": s["metadata"], "payment_intent": f"pi_{s['id']}", **over}


def _lots(org_id):
    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.billing import CreditLot

    async def go():
        async with AsyncSessionLocal() as db:
            return [(l.source, l.credits_granted, l.credits_remaining) for l in (await db.execute(
                select(CreditLot).where(CreditLot.org_id == uuid.UUID(org_id)).order_by(CreditLot.created_at))).scalars()]
    return asyncio.run(go())


def _balance(c):
    return c.get("/api/billing/overview").json()["credits"]["balance"]


# ── Catalog ───────────────────────────────────────────────────────────────────


def test_catalog_verifies_against_stripe(client, stripe):
    items = {i["key"]: i for i in client.get("/api/admin/billing/catalog").json()["items"]}
    assert items["credits_500"]["status"] == "ok" and items["credits_500"]["price_id"] == "price_1UPKcPR0Rid8tnhHKkgMDP69"
    stripe.prices["credits_75_one_time"]["unit_amount"] = 2500
    catalog.invalidate()
    items = {i["key"]: i for i in client.get("/api/admin/billing/catalog").json()["items"]}
    assert items["credits_75"]["status"] == "mismatch" and "expected 2900" in items["credits_75"]["detail"]
    stripe.prices["credits_75_one_time"]["unit_amount"] = 2900
    del stripe.prices["lookup_funds_5_one_time"]
    catalog.invalidate()
    items = {i["key"]: i for i in client.get("/api/admin/billing/catalog").json()["items"]}
    assert items["lookup_5"]["status"] == "missing"
    # Creating a missing price needs explicit confirmation, and never duplicates an existing one.
    assert client.post("/api/admin/billing/catalog/lookup_5/create", json={}).status_code == 400
    assert client.post("/api/admin/billing/catalog/credits_500/create", json={"confirm": True}).status_code == 409


def test_unconfigured_stripe_blocks_purchases(client, make_client, monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    catalog.invalidate()
    _, c = _account(client, make_client, "No Stripe Co")
    cat = c.get("/api/billing/catalog").json()
    assert cat["stripe_ready"] is False and not any(p["available"] for p in cat["packs"])
    assert c.post("/api/billing/credits/checkout", json={"pack": "credits_500"}).status_code == 409


# ── Checkout + webhooks ───────────────────────────────────────────────────────


def test_credits_only_after_verified_webhook_and_once(client, make_client, stripe):
    org, c = _account(client, make_client, "Pack Co")
    r = c.post("/api/billing/credits/checkout", json={"pack": "credits_500"})
    assert r.status_code == 200 and r.json()["url"].startswith("https://checkout.stripe.test/")
    sess = stripe.sessions[-1]
    assert sess["line_items"] == [{"price": "price_1UPKcPR0Rid8tnhHKkgMDP69", "quantity": 1}]
    assert sess["metadata"]["org_id"] == org["id"] and sess["metadata"]["purchase_type"] == "credit_pack"
    assert _balance(c) == 0  # returning from Checkout grants nothing

    bad = client.post("/api/billing/webhook", content=json.dumps({"id": "evt_x", "type": "checkout.session.completed",
                                                                 "data": {"object": _paid_session(stripe)}}),
                      headers={"stripe-signature": "forged"})
    assert bad.status_code == 400 and _balance(c) == 0

    assert _hook(client, "checkout.session.completed", _paid_session(stripe), "evt_pack_1").status_code == 200
    assert _balance(c) == 500
    _hook(client, "checkout.session.completed", _paid_session(stripe), "evt_pack_1")  # retry of the same event
    _hook(client, "checkout.session.async_payment_succeeded", _paid_session(stripe))  # different event, same purchase
    assert _balance(c) == 500
    pid = sess["metadata"]["purchase_id"]
    assert c.get(f"/api/billing/purchases/{pid}").json()["status"] == "paid"


def test_webhook_cannot_grant_to_another_org(client, make_client, stripe):
    _, a = _account(client, make_client, "Victim Co")
    other, b = _account(client, make_client, "Attacker Co")
    a.post("/api/billing/credits/checkout", json={"pack": "credits_75"})
    session = _paid_session(stripe)
    b.post("/api/billing/credits/checkout", json={"pack": "credits_75"})
    # Tampered metadata pointing A's purchase at B's customer is ignored.
    _hook(client, "checkout.session.completed", {**session, "customer": stripe.sessions[-1]["customer"]})
    assert _balance(a) == 0 and _balance(b) == 0


def test_delayed_payment_waits_for_async_success(client, make_client, stripe):
    _, c = _account(client, make_client, "Bank Co")
    c.post("/api/billing/credits/checkout", json={"pack": "credits_75"})
    _hook(client, "checkout.session.completed", _paid_session(stripe, payment_status="unpaid"))
    assert _balance(c) == 0
    _hook(client, "checkout.session.async_payment_succeeded", _paid_session(stripe))
    assert _balance(c) == 75

    c.post("/api/billing/credits/checkout", json={"pack": "credits_75"})
    _hook(client, "checkout.session.async_payment_failed", _paid_session(stripe, payment_status="unpaid"))
    pid = stripe.sessions[-1]["metadata"]["purchase_id"]
    assert c.get(f"/api/billing/purchases/{pid}").json()["status"] == "failed" and _balance(c) == 75


def test_refund_and_dispute_claw_back_unused_credits(client, make_client, stripe):
    _, c = _account(client, make_client, "Refund Co")
    c.post("/api/billing/credits/checkout", json={"pack": "credits_75"})
    s = _paid_session(stripe)
    _hook(client, "checkout.session.completed", s)
    assert _balance(c) == 75
    # Half the money back takes back half the credits (37.5 → 38).
    _hook(client, "charge.refunded", {"id": "ch_1", "payment_intent": s["payment_intent"], "amount": 2900, "amount_refunded": 1450})
    assert _balance(c) == 37
    _hook(client, "charge.dispute.created", {"id": "dp_1", "payment_intent": s["payment_intent"], "amount": 1450})
    assert _balance(c) == 0
    _hook(client, "charge.dispute.closed", {"id": "dp_1", "payment_intent": s["payment_intent"], "status": "won"})
    assert _balance(c) == 37


# ── Credits engine ────────────────────────────────────────────────────────────


def _finish_call(client, org_id, agent_id, seconds, call_id=None):
    from app.database import AsyncSessionLocal
    from app.models.call_log import CallLog

    call_id = call_id or uuid.uuid4()
    now = datetime.now(timezone.utc)

    async def make():
        async with AsyncSessionLocal() as db:
            db.add(CallLog(id=call_id, org_id=uuid.UUID(org_id), agent_id=uuid.UUID(agent_id), call_type="outbound",
                           to_phone="+14155550123", livekit_room_name=f"call-{call_id}", status="connected",
                           started_at=now - timedelta(seconds=seconds + 5), answered_at=now - timedelta(seconds=seconds)))
            await db.commit()

    asyncio.run(make())
    transcript = [{"role": "user", "text": "hi"}]
    for _ in range(2):  # duplicate outcome reports must not double-bill
        client.post(f"/internal/calls/{call_id}/outcome", json={"outcome": "completed", "transcript": transcript})
    return call_id


def test_per_second_billing_rates_carry_and_never_negative(client, make_client):
    org, c = _account(client, make_client, "Meter Co", credits=10)
    agent = c.get("/api/agents/").json()[0]
    c.patch(f"/api/agents/{agent['id']}", json={"llm_model": "gpt-4.1"})  # 1.4 credits/min by default
    rate = c.get(f"/api/billing/agents/{agent['id']}/rate").json()
    assert rate["credits_per_minute"] == 1.4 and rate["approx_cents_per_minute"] > 0

    _finish_call(client, org["id"], agent["id"], 90)        # 90s × 1.4/60 = 2.1 → 2 now, 0.1 carried
    assert _balance(c) == 8
    _finish_call(client, org["id"], agent["id"], 39)        # 0.91 + 0.1 carried = 1.01 → 1
    assert _balance(c) == 7
    _finish_call(client, org["id"], agent["id"], 600)       # owes 14, only 7 left → 0, shortfall 7
    assert _balance(c) == 0
    ledger = c.get("/api/billing/credits").json()["ledger"]
    assert [t["amount"] for t in ledger[:3]] == [-7, -1, -2] and all(t["balance_after"] >= 0 for t in ledger)


def test_included_credits_spent_first_and_expire_purchased_never(client, make_client, stripe):
    org, c = _account(client, make_client, "Plan Co")
    c.post("/api/billing/plans/solo/checkout")
    sess = stripe.sessions[-1]
    assert sess["mode"] == "subscription"
    end = int(time.time()) + 30 * 86400
    sub = {"id": "sub_plan", "customer": sess["customer"], "status": "active", "cancel_at_period_end": False,
           "current_period_end": end, "items": {"data": [{"id": "si_plan", "price": {"id": "price_solo", "lookup_key": "plan_solo_monthly"}}]}}
    stripe.subs["sub_plan"] = sub
    _hook(client, "checkout.session.completed", {"id": sess["id"], "mode": "subscription", "customer": sess["customer"],
                                                 "subscription": "sub_plan", "metadata": sess["metadata"]})
    _hook(client, "invoice.paid", {"id": "in_1", "customer": sess["customer"], "subscription": "sub_plan",
                                   "billing_reason": "subscription_create"})
    _hook(client, "invoice.paid", {"id": "in_1", "customer": sess["customer"], "subscription": "sub_plan",
                                   "billing_reason": "subscription_create"}, "evt_dup_invoice")
    ov = c.get("/api/billing/overview").json()
    assert ov["plan"]["plan_key"] == "solo" and ov["credits"]["included"] == 150 and ov["credits"]["balance"] == 150

    c.post("/api/billing/credits/checkout", json={"pack": "credits_75"})
    _hook(client, "checkout.session.completed", _paid_session(stripe))
    agent = c.get("/api/agents/").json()[0]
    _finish_call(client, org["id"], agent["id"], 60 * 20)
    cr = c.get("/api/billing/overview").json()["credits"]
    assert cr["included"] == 130 and cr["purchased"] == 75

    # Next cycle: leftover included credits are replaced; purchased credits stay.
    _hook(client, "invoice.paid", {"id": "in_2", "customer": sess["customer"], "subscription": "sub_plan",
                                   "billing_reason": "subscription_cycle"})
    cr = c.get("/api/billing/overview").json()["credits"]
    assert cr["included"] == 150 and cr["purchased"] == 75 and cr["balance"] == 225

    # Plan change: preview first, explicit confirm, upgrade tops up included credits.
    pv = c.post("/api/billing/plans/teams/preview").json()
    assert pv["upgrade"] is True and pv["amount_due_now_cents"] == 15000 and pv["included_credits_now"] == 550
    assert c.post("/api/billing/plans/teams/change", json={}).status_code == 400
    stripe.prices["plan_teams_monthly"]["id"] = "price_teams"
    assert c.post("/api/billing/plans/teams/change", json={"confirm": True}).status_code == 200
    assert c.get("/api/billing/overview").json()["credits"]["included"] == 700


def test_unknown_plan_is_preserved_read_only(client, make_client, stripe):
    _, c = _account(client, make_client, "Legacy Plan Co")
    c.post("/api/billing/credits/checkout", json={"pack": "credits_75"})  # creates the customer
    cid = stripe.sessions[-1]["customer"]
    sub = {"id": "sub_legacy", "customer": cid, "status": "active", "current_period_end": int(time.time()) + 86400,
           "items": {"data": [{"id": "si_x", "price": {"id": "price_front_desk_starter", "lookup_key": None}}]}}
    _hook(client, "customer.subscription.updated", sub)
    plan = c.get("/api/billing/overview").json()["plan"]
    assert plan["status"] == "active" and plan["plan_key"] is None and plan["managed"] is False


def test_call_reservation_caps_duration(client, make_client, monkeypatch):
    from app.services import outbound_call

    org, c = _account(client, make_client, "Cap Co", credits=3)
    agent = c.get("/api/agents/").json()[0]
    sent = []

    class LK:
        def __init__(self):
            async def create_room(req):
                sent.append(json.loads(req.metadata))

            async def noop(*a, **k):
                return SimpleNamespace(id="x", sip_call_id="y")

            self.room = SimpleNamespace(create_room=create_room, delete_room=noop)
            self.agent_dispatch = SimpleNamespace(create_dispatch=noop)
            self.sip = SimpleNamespace(create_sip_participant=noop)
            self.aclose = noop

    monkeypatch.setattr(outbound_call, "_lk", LK)
    monkeypatch.setattr(settings, "livekit_sip_outbound_trunk_id", "ST_test")
    assert c.post(f"/api/agents/{agent['id']}/phone-call", json={"to_phone": "+14155550123"}).status_code == 200
    assert sent[0]["agent"]["max_duration_seconds"] == 180  # 3 credits at 1/min
    # All 3 credits are reserved by the call in progress, so a second call is refused.
    r = c.post(f"/api/agents/{agent['id']}/phone-call", json={"to_phone": "+14155550124"})
    assert r.status_code == 402


# ── Auto-recharge ─────────────────────────────────────────────────────────────


def test_auto_recharge_consent_threshold_limit_and_failures(client, make_client, stripe):
    org, c = _account(client, make_client, "Recharge Co")
    cfg = c.get("/api/billing/auto-recharge").json()
    assert cfg["enabled"] is False
    body = {"enabled": True, "pack_key": "credits_75", "threshold": 50, "monthly_limit_cents": 5800}
    assert c.put("/api/billing/auto-recharge", json=body).status_code == 400  # no consent
    assert c.put("/api/billing/auto-recharge", json={**body, "consent": True}).status_code == 409  # no saved card yet
    c.post("/api/billing/credits/checkout", json={"pack": "credits_75"})
    _hook(client, "checkout.session.completed", _paid_session(stripe))
    assert c.put("/api/billing/auto-recharge", json={**body, "consent": True}).status_code == 200

    async def run():
        from app.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            return await recharge.maybe_recharge(db, uuid.UUID(org["id"]))

    assert asyncio.run(run()) is None  # 75 ≥ threshold 50
    agent = c.get("/api/agents/").json()[0]

    def spend_and_settle(minutes):
        _finish_call(client, org["id"], agent["id"], 60 * minutes)  # schedules a background check
        time.sleep(0.3)
        asyncio.run(run())  # and a direct one — still at most one charge per drop

    spend_and_settle(60)  # 15 left → one recharge of 75
    assert len(stripe.charges) == 1 and _balance(c) == 90
    assert stripe.charges[0]["idempotency_key"].startswith("bs-recharge-")
    spend_and_settle(100)  # 0 left → second recharge ($58 so far)
    assert len(stripe.charges) == 2 and _balance(c) == 75
    spend_and_settle(100)  # 0 left, but a third pack would pass the $58 monthly limit
    assert len(stripe.charges) == 2 and _balance(c) == 0
    assert "limit" in c.get("/api/billing/auto-recharge").json()["last_error"]
    assert c.get("/api/billing/auto-recharge").json()["month_to_date_cents"] == 5800


def test_auto_recharge_turns_off_after_three_failures(client, make_client, stripe):
    org, c = _account(client, make_client, "Declined Co")
    c.post("/api/billing/credits/checkout", json={"pack": "credits_75"})
    _hook(client, "checkout.session.completed", _paid_session(stripe))
    c.put("/api/billing/auto-recharge", json={"enabled": True, "pack_key": "credits_75", "threshold": 500,
                                               "monthly_limit_cents": 100000, "consent": True})
    stripe.charge_status = "failed"

    async def run():
        from app.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            return await recharge.maybe_recharge(db, uuid.UUID(org["id"]))

    for _ in range(4):
        asyncio.run(run())
    cfg = c.get("/api/billing/auto-recharge").json()
    assert cfg["enabled"] is False and cfg["consecutive_failures"] == 3 and len(stripe.charges) == 3
    assert _balance(c) == 75


# ── Lead lookups ──────────────────────────────────────────────────────────────


@pytest.fixture
def dataskip(monkeypatch):
    from app.services import lead_finder as lf

    reply = {"value": {"success": True, "found": True, "charged": 0.07, "contact": {"fullName": "Dana Reyes"}, "phones": [], "emails": []}}

    def handler(request):
        return httpx.Response(200, json=reply["value"])

    real = httpx.AsyncClient
    monkeypatch.setattr(lf.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(settings, "skiptrace_api_key", "dsk_test")
    lf._hits.clear()
    return reply


def _addr(n):
    return {"street": f"{500 + n} Oak St", "city": "Erie", "state": "PA", "zip": "16503"}


def test_lookup_free_allowance_then_confirmed_paid_balance(client, make_client, stripe, dataskip):
    from app.services import lead_finder as lf

    org, c = _account(client, make_client, "Lookup Pay Co")
    client.patch("/api/admin/billing/settings", json={"clear_lookup_price": True})
    for i in range(5):
        lf._hits.clear()
        assert c.post("/api/lead-finder/lookups", json=_addr(i)).status_code == 200
    usage = c.get("/api/lead-finder/usage").json()
    assert usage["free_remaining"] == 0
    lf._hits.clear()
    r = c.post("/api/lead-finder/lookups", json=_addr(9))
    assert r.status_code == 402 and r.json()["code"] == "paid_disabled"  # no price set → no paid lookups
    assert c.post("/api/lead-finder/lookups", json=_addr(0)).json()["cached"] is True  # repeat views stay free

    client.patch("/api/admin/billing/settings", json={"property_lookup_price_cents": 25})
    try:
        r = c.post("/api/lead-finder/lookups", json=_addr(9))
        assert r.status_code == 402 and r.json()["code"] == "confirm_price" and r.json()["price_cents"] == 25
        r = c.post("/api/lead-finder/lookups", json={**_addr(9), "expected_price_cents": 25})
        assert r.status_code == 402 and r.json()["code"] == "insufficient_balance"

        c.post("/api/billing/lookups/checkout", json={"amount": "lookup_5"})
        assert stripe.sessions[-1]["metadata"]["purchase_type"] == "lookup_funds"
        _hook(client, "checkout.session.completed", _paid_session(stripe))
        assert c.get("/api/billing/lookups").json()["balance_cents"] == 500

        lf._hits.clear()
        assert c.post("/api/lead-finder/lookups", json={**_addr(9), "expected_price_cents": 25}).status_code == 200
        assert c.get("/api/billing/lookups").json()["balance_cents"] == 475
        # Stale price (admin changed it) must be re-confirmed.
        assert c.post("/api/lead-finder/lookups", json={**_addr(10), "expected_price_cents": 20}).json()["code"] == "confirm_price"
        # "match" policy: no owner found = no charge.
        dataskip["value"] = {"success": True, "found": False, "charged": 0, "contact": None, "phones": [], "emails": []}
        lf._hits.clear()
        assert c.post("/api/lead-finder/lookups", json={**_addr(11), "expected_price_cents": 25}).status_code == 200
        lk = c.get("/api/billing/lookups").json()
        assert lk["balance_cents"] == 475 and [t["amount_cents"] for t in lk["ledger"]] == [-25, 500]
        # Calling credits are separate.
        assert _balance(c) == 0
    finally:
        client.patch("/api/admin/billing/settings", json={"clear_lookup_price": True})


# ── Admin ─────────────────────────────────────────────────────────────────────


def test_admin_adjustments_are_audited_and_admin_only(client, make_client):
    org, c = _account(client, make_client, "Audit Co")
    assert client.post(f"/api/admin/orgs/{org['id']}/credits", json={"amount": 40, "note": "Goodwill"}).status_code == 200
    assert client.post(f"/api/admin/orgs/{org['id']}/credits", json={"amount": -100, "note": "Correction"}).json()["balance"] == 0
    r = client.post(f"/api/admin/orgs/{org['id']}/lookup-balance", json={"amount_cents": 1000, "reason": "Promo"})
    assert r.json() == {"balance_cents": 1000, "applied_cents": 1000}
    audit = client.get(f"/api/admin/billing/orgs/{org['id']}").json()["audit"]
    assert [(a["target"], a["previous"], a["adjustment"], a["new"], a["reason"]) for a in audit] == [
        ("lookup_balance", "0", "+1000", "1000", "Promo"),
        ("calling_credits", "40", "-40", "0", "Correction"),
        ("calling_credits", "0", "+40", "40", "Goodwill"),
    ]
    assert c.post(f"/api/admin/orgs/{org['id']}/lookup-balance", json={"amount_cents": 5, "reason": "me"}).status_code in (401, 403)
    assert c.patch("/api/admin/billing/settings", json={"lookup_free_daily": 100}).status_code in (401, 403)


def test_billing_data_is_tenant_isolated(client, make_client, stripe):
    _, a = _account(client, make_client, "Iso A")
    _, b = _account(client, make_client, "Iso B")
    a.post("/api/billing/credits/checkout", json={"pack": "credits_75"})
    pid = stripe.sessions[-1]["metadata"]["purchase_id"]
    assert b.get(f"/api/billing/purchases/{pid}").status_code == 404
    assert b.get("/api/billing/invoices").json()["purchases"] == []


def test_members_cannot_spend(client, make_client, stripe):
    org, owner = _account(client, make_client, "Member Co")
    inv = owner.post("/api/account/org/invites", json={"email": f"m-{uuid.uuid4().hex[:6]}@x.dev", "role": "member"}).json()
    token = inv["invite_url"].rsplit("/", 1)[1]
    m = make_client()
    m.post(f"/api/auth/invites/{token}/accept", json={"first_name": "M", "password": "member-pass-1"})
    assert m.get("/api/billing/overview").status_code == 200
    assert m.post("/api/billing/credits/checkout", json={"pack": "credits_75"}).status_code == 403


def test_phone_addon_quantity_tracks_numbers(client, make_client, stripe):
    from app.services.billing import subscriptions

    org, c = _account(client, make_client, "Phones Bill Co")
    c.post("/api/billing/credits/checkout", json={"pack": "credits_75"})
    cid = stripe.sessions[-1]["customer"]
    stripe.subs["sub_ph"] = {"id": "sub_ph", "customer": cid, "status": "active", "current_period_end": int(time.time()) + 86400,
                            "items": {"data": [{"id": "si_p", "price": {"id": "price_solo", "lookup_key": "plan_solo_monthly"}}]}}
    _hook(client, "customer.subscription.created", stripe.subs["sub_ph"])

    from app.database import AsyncSessionLocal
    from app.models.billing import PhoneNumber

    async def add_numbers(n):
        async with AsyncSessionLocal() as db:
            for _ in range(n):
                db.add(PhoneNumber(org_id=uuid.UUID(org["id"]), number=f"+1628{uuid.uuid4().int % 10_000_000:07d}"))
            await db.commit()
            await subscriptions.sync_phone_quantity(db, uuid.UUID(org["id"]))

    asyncio.run(add_numbers(1))
    assert stripe.quantity_calls == []  # one number is included
    asyncio.run(add_numbers(2))
    assert stripe.quantity_calls == [2]
    ph = c.get("/api/billing/overview").json()["phones"]
    assert ph == {**ph, "active": 3, "included": 1, "billable": 2, "billed_quantity": 2, "unit_cents": 350}


# ── Connecting Stripe from the admin portal ───────────────────────────────────


def test_admin_connects_stripe_key_encrypted_and_never_returned(client, make_client, monkeypatch):
    from cryptography.fernet import Fernet

    from app.models.account import AppSecret
    from app.services import secret_store

    monkeypatch.setattr(settings, "stripe_secret_key", "")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "")
    monkeypatch.setattr(settings, "secrets_encryption_key", Fernet.generate_key().decode())
    made = []

    async def inspect_key(key):
        if key.endswith("bad"):
            raise ValueError("invalid")
        return {"id": "acct_1", "name": "BlackSync LLC", "charges_enabled": True}

    async def ensure_webhook(key, url, events):
        made.append((url, events))
        return {"id": "we_1", "secret": "whsec_from_stripe"}

    async def delete_webhook(key, endpoint_id):
        made.append(("deleted", endpoint_id))

    monkeypatch.setattr(stripe_api, "inspect_key", inspect_key)
    monkeypatch.setattr(stripe_api, "ensure_webhook", ensure_webhook)
    monkeypatch.setattr(stripe_api, "delete_webhook", delete_webhook)
    key = "sk_test_" + "a" * 30 + "wxyz"
    try:
        assert client.get("/api/admin/billing/stripe").json()["connected"] is False
        assert client.post("/api/admin/billing/stripe", json={"secret_key": "pk_test_" + "a" * 30}).status_code == 400
        assert client.post("/api/admin/billing/stripe", json={"secret_key": "sk_test_" + "a" * 30 + "bad"}).status_code == 400

        r = client.post("/api/admin/billing/stripe", json={"secret_key": key})
        assert r.status_code == 200, r.text
        body = r.json()
        assert key not in r.text and body["key_hint"].endswith("wxyz") and body["mode"] == "test"
        assert body["connected"] and body["webhook_ready"] and body["account_name"] == "BlackSync LLC"
        assert made[0][0].endswith("/api/billing/webhook") and "checkout.session.completed" in made[0][1]
        assert stripe_api.secret_key() == key and stripe_api.webhook_secret() == "whsec_from_stripe"

        async def stored():
            from app.database import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                return (await db.get(AppSecret, "enc:stripe_secret_key")).value

        assert key not in asyncio.run(stored())  # encrypted at rest

        _, c = _account(client, make_client, "Peeker Co")
        assert c.get("/api/admin/billing/stripe").status_code in (401, 403)
        assert c.post("/api/admin/billing/stripe", json={"secret_key": key}).status_code in (401, 403)

        assert client.delete("/api/admin/billing/stripe").json()["connected"] is False
        assert ("deleted", "we_1") in made and stripe_api.secret_key() == ""
    finally:
        for name in ("stripe_secret_key", "stripe_webhook_secret", "stripe_webhook_id", "stripe_account_name"):
            secret_store._cache.pop(name, None)
