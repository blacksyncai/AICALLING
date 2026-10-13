"""Plan tiers, entitlements, agent slots, Managed and admin overrides."""

import asyncio
import time
import uuid

import pytest

from app.services.billing import catalog, stripe_api
from tests.test_billing import _account, _hook, stripe  # noqa: F401  (fixture)
from tests.test_phone_numbers import twilio  # noqa: F401  (fixture)


def _subscribe(client, c, stripe, plan_key, sub_id=None, extra_items=(), metadata=None, price_id=None):
    """Start a plan the way Checkout + webhooks do."""
    sub_id = sub_id or f"sub_{uuid.uuid4().hex[:8]}"
    assert c.post(f"/api/billing/plans/{plan_key}/checkout").status_code == 200
    sess = stripe.sessions[-1]
    plan = catalog.PLANS[plan_key]
    price = stripe.prices[plan["lookup_key"]]
    item = {"id": f"si_{sub_id}", "price": {"id": price_id or price["id"], "lookup_key": price["lookup_key"] if not price_id else None}}
    sub = {"id": sub_id, "customer": sess["customer"], "status": "active", "cancel_at_period_end": False,
           "current_period_end": int(time.time()) + 30 * 86400, "metadata": metadata or sess.get("metadata") or {},
           "items": {"data": [item, *extra_items]}}
    stripe.subs[sub_id] = sub
    _hook(client, "checkout.session.completed", {"id": sess["id"], "mode": "subscription", "customer": sess["customer"],
                                                 "subscription": sub_id, "metadata": sess["metadata"]})
    _hook(client, "invoice.paid", {"id": f"in_{sub_id}", "customer": sess["customer"], "subscription": sub_id,
                                   "billing_reason": "subscription_create"})
    return sub


def _new_agent(c, name="Agent"):
    return c.post("/api/agents/", json={"template": "blank", "name": name})


def _limit(r):
    assert r.status_code == 402, r.text
    d = r.json()["detail"]
    assert d["code"] == "plan_limit"
    return d


def test_catalog_has_four_tiers_and_managed_is_sales_led(client, make_client, stripe):
    _, c = _account(client, make_client, "Catalog Co")
    cat = c.get("/api/billing/catalog").json()
    plans = {p["key"]: p for p in cat["plans"]}
    assert list(plans) == ["solo", "growth", "teams", "managed"]
    assert [plans[k]["amount_cents"] for k in plans] == [9800, 19700, 34900, 79700]
    assert [plans[k]["included_credits"] for k in plans] == [150, 400, 900, 1500]
    assert [plans[k]["limits"]["agents"] for k in plans] == [2, 4, 8, 12]
    assert [plans[k]["limits"]["seats"] for k in plans] == [1, 4, 10, 15]
    assert [plans[k]["limits"]["numbers"] for k in plans] == [1, 2, 4, 4]
    assert plans["teams"]["recommended"] and plans["managed"]["self_serve"] is False
    assert cat["agent_addon"]["amount_cents"] == 1900 and cat["links"]["sales_booking_url"].startswith("https://")
    # No self-serve checkout or plan change into Managed.
    r = c.post("/api/billing/plans/managed/checkout")
    assert r.status_code == 409 and "sales" in r.json()["detail"]
    assert not any("plan_managed" in str(s) for s in stripe.sessions)
    # The public pricing payload has no Stripe ids.
    pub = c.get("/api/billing/public/plans").json()
    assert "price_" not in str(pub) and len(pub["plans"]) == 4


def test_existing_accounts_keep_access_without_a_plan(client, make_client, stripe):
    _, c = _account(client, make_client, "Trial Co")
    ent = c.get("/api/billing/entitlements").json()
    assert ent["plan"] is None and ent["limits_plan"] == "teams" and ent["limits"]["crm"] is None
    for i in range(3):
        assert _new_agent(c, f"A{i}").status_code == 201


def test_solo_limits_and_upgrade_prompts(client, make_client, stripe):
    org, c = _account(client, make_client, "Solo Co")
    _subscribe(client, c, stripe, "solo")
    ent = c.get("/api/billing/entitlements").json()
    assert ent["plan"] == "solo" and ent["limits"]["agents"] == 2 and ent["usage"]["agents"] == 0  # demo agent exempt
    assert _new_agent(c, "One").status_code == 201
    assert _new_agent(c, "Two").status_code == 201
    d = _limit(_new_agent(c, "Three"))
    assert d["feature"] == "agents" and d["suggest"]["plan"] == "growth" and d["suggest"]["addon"] == "agent_slot"
    # CRM → Growth, invites → Growth, API keys / webhooks → Teams.
    d = _limit(c.post("/api/integrations/crm/close/connect", json={"fields": {"api_key": "x"}}))
    assert d["feature"] == "crm" and d["suggest"]["plan"] == "growth"
    d = _limit(c.post("/api/account/org/invites", json={"email": "pal@solo.dev", "role": "member"}))
    assert d["feature"] == "seats" and d["suggest"]["plan"] == "growth"
    assert _limit(c.post("/api/integrations/api-keys", json={"name": "k"}))["suggest"]["plan"] == "teams"
    # Team analytics are locked, not an error.
    an = c.get("/api/analytics").json()
    assert an["locked"] == ["by_agent"] and an["by_agent"] == []
    # Concurrency above the plan's cap.
    agent = next(a for a in c.get("/api/agents/").json() if a["name"] == "One")
    d = _limit(c.post("/api/campaigns/", json={"name": "Big", "agent_id": agent["id"], "max_concurrent_calls": 5}))
    assert d["feature"] == "concurrency"
    assert c.post("/api/campaigns/", json={"name": "Ok", "agent_id": agent["id"], "max_concurrent_calls": 2}).status_code == 201


def test_growth_seats_roles_and_one_crm(client, make_client, stripe):
    _, c = _account(client, make_client, "Growth Co")
    _subscribe(client, c, stripe, "growth")
    d = _limit(c.post("/api/account/org/invites", json={"email": "boss@g.dev", "role": "admin"}))
    assert d["feature"] == "roles" and d["suggest"]["plan"] == "teams"
    for i in range(3):  # owner + 3 pending invites = 4 seats
        assert c.post("/api/account/org/invites", json={"email": f"m{i}@g.dev", "role": "member"}).status_code == 201
    assert c.post("/api/account/org/invites", json={"email": "m0@g.dev", "role": "member"}).status_code == 201  # re-invite
    assert _limit(c.post("/api/account/org/invites", json={"email": "m9@g.dev", "role": "member"}))["feature"] == "seats"
    # Growth may connect one CRM: the limit isn't hit until one is connected.
    assert c.get("/api/billing/entitlements").json()["limits"]["crm"] == 1
    assert c.post("/api/integrations/webhooks", json={"name": "h", "url": "https://example.com/h", "events": ["call.completed"]}).status_code == 402


def test_agent_slots_raise_the_limit_and_removing_never_deletes(client, make_client, stripe):
    org, c = _account(client, make_client, "Slots Co")
    _subscribe(client, c, stripe, "solo")
    ids = [_new_agent(c, f"S{i}").json()["id"] for i in range(2)]
    _limit(_new_agent(c, "S2"))
    pv = c.post("/api/billing/addons/agents/preview", json={"quantity": 1}).json()
    assert pv["monthly_change_cents"] == 1900 and pv["agent_limit"] == 3
    assert c.post("/api/billing/addons/agents", json={"quantity": 1}).status_code == 400  # needs confirm
    assert c.post("/api/billing/addons/agents", json={"quantity": 1, "confirm": True}).json()["agent_slots"] == 1
    assert stripe.slot_calls[-1] == (1, "error_if_incomplete")  # charged now; refused if the card fails
    third = _new_agent(c, "S2").json()["id"]
    assert c.get("/api/billing/entitlements").json()["limits"]["agents"] == 3
    # Remove the slot: all three agents stay; the newest can't call; activation is refused.
    assert c.post("/api/billing/addons/agents", json={"quantity": 0, "confirm": True}).json()["agent_slots"] == 0
    assert stripe.slot_calls[-1] == (0, None)
    assert len([a for a in c.get("/api/agents/").json() if a["name"].startswith("S")]) == 3
    ent = c.get("/api/billing/entitlements").json()
    assert ent["over_limit"] == ["agents"]

    from app.database import AsyncSessionLocal
    from app.models.account import Organization
    from app.models.agent import Agent
    from app.services import entitlements

    async def can_call(aid):
        async with AsyncSessionLocal() as db:
            o = await db.get(Organization, uuid.UUID(org["id"]))
            try:
                await entitlements.check_agent_can_call(db, o, await db.get(Agent, uuid.UUID(aid)))
                return True
            except entitlements.PlanLimit:
                return False
    assert asyncio.run(can_call(ids[0])) and asyncio.run(can_call(ids[1])) and not asyncio.run(can_call(third))
    assert c.patch(f"/api/agents/{third}", json={"status": "paused"}).status_code == 200
    _limit(c.patch(f"/api/agents/{third}", json={"status": "active"}))
    # A failed card refuses the slot (nothing changes).
    stripe.charge_status = "declined"
    assert c.post("/api/billing/addons/agents", json={"quantity": 1, "confirm": True}).status_code == 402
    assert c.get("/api/billing/overview").json()["plan"]["agent_slots"] == 0


def test_downgrade_preview_lists_what_goes_over(client, make_client, stripe):
    _, c = _account(client, make_client, "Down Co")
    _subscribe(client, c, stripe, "teams")
    for i in range(3):
        assert _new_agent(c, f"D{i}").status_code == 201
    pv = c.post("/api/billing/plans/solo/preview").json()
    assert pv["upgrade"] is False and any("3 active agents" in x for x in pv["downgrade_effects"])
    assert any("Webhooks" in x for x in pv["downgrade_effects"])
    assert c.post("/api/billing/plans/managed/preview").status_code == 409


def test_legacy_teams_price_keeps_teams_entitlements(client, make_client, stripe):
    _, c = _account(client, make_client, "Legacy Co")
    c.post("/api/billing/plans/solo/checkout")
    sess = stripe.sessions[-1]
    old = stripe.prices["plan_teams_monthly"]
    stripe.subs["sub_old"] = {"id": "sub_old", "customer": sess["customer"], "status": "active", "metadata": {},
                              "current_period_end": int(time.time()) + 86400,
                              "items": {"data": [{"id": "si_old", "price": {"id": old["id"], "lookup_key": "plan_teams_monthly"}}]}}
    _hook(client, "customer.subscription.updated", stripe.subs["sub_old"])
    _hook(client, "invoice.paid", {"id": "in_old", "customer": sess["customer"], "subscription": "sub_old",
                                   "billing_reason": "subscription_cycle"})
    ov = c.get("/api/billing/overview").json()
    assert ov["plan"]["plan_key"] == "teams_legacy" and ov["plan"]["legacy"] and ov["credits"]["included"] == 500
    ent = c.get("/api/billing/entitlements").json()
    assert ent["limits"]["agents"] == 8 and ent["limits"]["team_reporting"] is True


def test_admin_managed_link_activates_managed_and_flags_onboarding(client, make_client, stripe):
    org, c = _account(client, make_client, "Managed Co")
    r = client.post(f"/api/admin/billing/orgs/{org['id']}/managed-checkout", json={"amount_cents": 120000, "credits": 2500})
    assert r.status_code == 200 and r.json()["url"].startswith("https://checkout.stripe.test/")
    sess = stripe.sessions[-1]
    line = sess["line_items"][0]
    assert line["price_data"]["unit_amount"] == 120000 and line["price_data"]["product"] == "prod_managed"
    assert sess["metadata"]["plan"] == "managed" and sess["metadata"]["custom"] == "1" and sess["metadata"]["credits"] == "2500"
    sub = {"id": "sub_m", "customer": sess["customer"], "status": "active", "cancel_at_period_end": False,
           "metadata": sess["subscription_data"]["metadata"], "current_period_end": int(time.time()) + 30 * 86400,
           "items": {"data": [{"id": "si_m", "price": {"id": "price_adhoc_123", "lookup_key": None}}]}}
    stripe.subs["sub_m"] = sub
    _hook(client, "checkout.session.completed", {"id": sess["id"], "mode": "subscription", "customer": sess["customer"],
                                                 "subscription": "sub_m", "metadata": sess["metadata"]})
    for evt in ("evt_m1", "evt_m1", "evt_m2"):  # retried + duplicate delivery of the same invoice
        _hook(client, "invoice.paid", {"id": "in_m", "customer": sess["customer"], "subscription": "sub_m",
                                       "billing_reason": "subscription_create"}, evt)
    ov = c.get("/api/billing/overview").json()
    assert ov["plan"]["plan_key"] == "managed" and ov["plan"]["custom"] and ov["credits"]["included"] == 2500
    ent = c.get("/api/billing/entitlements").json()
    assert ent["plan"] == "managed" and ent["limits"]["agents"] == 12 and ent["managed_onboarding"] == "needed"
    adm = client.get(f"/api/admin/billing/orgs/{org['id']}").json()
    assert adm["managed_onboarding"] == "needed" and adm["subscription"]["custom_credits"] == 2500
    assert any(a["target"] == "managed" for a in adm["audit"])
    # The customer can't self-change a Managed plan; a second link is refused.
    assert c.post("/api/billing/plans/teams/preview").status_code == 409
    assert client.post(f"/api/admin/billing/orgs/{org['id']}/managed-checkout", json={}).status_code == 409
    assert client.patch(f"/api/admin/billing/orgs/{org['id']}/onboarding", json={"status": "done"}).json()["managed_onboarding"] == "done"


def test_admin_overrides_are_audited_and_reversible(client, make_client, stripe):
    org, c = _account(client, make_client, "Override Co")
    _subscribe(client, c, stripe, "solo")
    assert c.post("/api/billing/plans/solo/checkout").status_code == 409
    r = client.post(f"/api/admin/billing/orgs/{org['id']}/overrides", json={"key": "crm", "value": 1, "reason": "Pilot"})
    assert r.status_code == 201
    oid = r.json()["id"]
    assert c.get("/api/billing/entitlements").json()["limits"]["crm"] == 1
    assert client.post(f"/api/admin/billing/orgs/{org['id']}/overrides",
                       json={"key": "agents", "value": -1, "reason": "bad"}).status_code == 400
    assert client.post(f"/api/admin/billing/orgs/{org['id']}/overrides",
                       json={"key": "workflows", "value": True, "reason": "old", "expires_at": "2000-01-01T00:00:00Z"}).status_code == 400
    assert client.delete(f"/api/admin/billing/orgs/{org['id']}/overrides/{oid}").json()["revoked_at"]
    assert c.get("/api/billing/entitlements").json()["limits"]["crm"] == 0
    audit = client.get(f"/api/admin/billing/orgs/{org['id']}").json()["audit"]
    assert [a["adjustment"] for a in audit if a["target"] == "entitlements"] == ["revoked", "override"]
    # A non-admin can't grant themselves anything.
    assert c.post(f"/api/admin/billing/orgs/{org['id']}/overrides", json={"key": "crm", "value": 9, "reason": "me"}).status_code in (401, 403)


def test_admin_quote_creates_a_hosted_invoice(client, make_client, stripe, monkeypatch):
    org, _ = _account(client, make_client, "Quote Co")
    made = []

    async def fake_quote(**kw):
        made.append(kw)
        return {"id": "in_q", "hosted_invoice_url": "https://invoice.stripe.test/q", "status": "open"}

    monkeypatch.setattr(stripe_api, "create_quote_invoice", fake_quote)
    r = client.post(f"/api/admin/billing/orgs/{org['id']}/quote", json={"description": "Custom agent build", "amount_cents": 50000})
    assert r.json()["url"] == "https://invoice.stripe.test/q" and made[0]["amount_cents"] == 50000
    assert made[0]["metadata"]["purchase_type"] == "service_quote"


def test_extra_number_needs_confirmation_and_payment_first(client, make_client, stripe, twilio):
    def bought():
        return [f["PhoneNumber"] for m, p, f in twilio.calls if m == "POST" and p.endswith("/IncomingPhoneNumbers.json")]

    client.patch("/api/admin/telephony/settings", json={"self_serve_numbers": True, "max_numbers_per_org": 5})
    try:
        _, c = _account(client, make_client, "Numbers Co")
        _subscribe(client, c, stripe, "solo")
        n1, n2 = f"+1415555{uuid.uuid4().int % 10000:04d}", f"+1415556{uuid.uuid4().int % 10000:04d}"
        assert c.post("/api/phone-numbers/purchase", json={"number": n1}).status_code == 201  # included
        assert stripe.quantity_calls == []
        r = c.post("/api/phone-numbers/purchase", json={"number": n2})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "confirm_charge" and r.json()["detail"]["unit_cents"] == 350
        stripe.charge_status = "declined"
        assert c.post("/api/phone-numbers/purchase", json={"number": n2, "confirm_charge": True}).status_code == 402
        assert bought() == [n1]  # nothing bought when the charge fails
        stripe.charge_status = "succeeded"
        assert c.post("/api/phone-numbers/purchase", json={"number": n2, "confirm_charge": True}).status_code == 201
        assert bought() == [n1, n2] and stripe.quantity_calls[-1] == 1
    finally:
        client.patch("/api/admin/telephony/settings", json={"self_serve_numbers": False, "max_numbers_per_org": 5})


def test_no_plan_setting_can_tighten_trials(client, make_client, stripe):
    _, c = _account(client, make_client, "Strict Trial Co")
    assert client.patch("/api/admin/billing/settings", json={"no_plan_entitlements": "solo"}).status_code == 200
    try:
        assert c.get("/api/billing/entitlements").json()["limits_plan"] == "solo"
        _limit(c.post("/api/integrations/crm/close/connect", json={"fields": {"api_key": "x"}}))
    finally:
        client.patch("/api/admin/billing/settings", json={"no_plan_entitlements": "teams"})
