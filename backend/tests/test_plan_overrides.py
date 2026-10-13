"""Admin plan assignment (billing plan vs effective access) and Radar gating."""

import asyncio
import copy
import time
import uuid
from datetime import datetime, timedelta, timezone

from app.services.billing import catalog
from tests.test_accounts import _login, _new_account
from tests.test_billing import _account, _hook, stripe  # noqa: F401  (fixture)
from tests.test_entitlements import _subscribe


def _db(fn):
    from app.database import AsyncSessionLocal

    async def go():
        async with AsyncSessionLocal() as db:
            return await fn(db)
    return asyncio.run(go())


def _assign(client, org_id, **body):
    return client.put(f"/api/admin/billing/orgs/{org_id}/plan", json=body)


def _crm(c):
    return c.post("/api/integrations/crm/close/connect", json={"fields": {"api_key": "x"}})


def test_admin_gives_solo_growth_without_touching_stripe_or_credits(client, make_client, stripe):
    org, c = _account(client, make_client, "Gabriel Co", credits=40)
    sub = _subscribe(client, c, stripe, "solo")
    before_sub, sessions = copy.deepcopy(stripe.subs[sub["id"]]), len(stripe.sessions)
    balance = c.get("/api/billing/overview").json()["credits"]["balance"]
    assert _crm(c).status_code == 402 and c.get("/api/radar").status_code == 402

    v = client.get(f"/api/admin/billing/orgs/{org['id']}/plan").json()
    assert v["billing"]["plan"] == "solo" and v["effective"]["plan"] == "solo" and v["controlled_by"] == "stripe"
    assert v["org"]["owner"]["email"] and v["credits_balance"] == balance

    r = _assign(client, org["id"], mode="manual", plan="growth", reason="Thanks for the referral")
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["effective"]["plan"] == "growth" and v["billing"]["plan"] == "solo" and v["controlled_by"] == "admin_override"
    assert v["override"]["mode"] == "manual" and v["override"]["expires_at"] is None  # indefinite by default

    # Stripe untouched; no checkout, no plan change; credits unchanged.
    assert stripe.subs[sub["id"]] == before_sub and len(stripe.sessions) == sessions
    assert stripe.quantity_calls == [] and stripe.slot_calls == []
    ov = c.get("/api/billing/overview").json()
    assert ov["plan"]["plan_key"] == "solo" and ov["credits"]["balance"] == balance

    # Growth features unlock immediately (the CRM call now gets past the plan check).
    assert _crm(c).status_code != 402
    assert c.get("/api/radar").status_code == 200
    ent = c.get("/api/billing/entitlements").json()
    assert ent["plan"] == "growth" and ent["source"] == "override" and ent["billing"]["plan"] == "solo"
    assert "overrides" not in ent and "reason" not in (ent["override"] or {})  # internal notes stay internal

    # A renewal still bills Solo and grants Solo's credits; the override survives the webhook.
    _hook(client, "invoice.paid", {"id": "in_renew", "customer": sub["customer"], "subscription": sub["id"],
                                   "billing_reason": "subscription_cycle"})
    assert c.get("/api/billing/overview").json()["credits"]["included"] == 150
    assert c.get("/api/billing/entitlements").json()["plan"] == "growth"

    # Back to billing.
    v = _assign(client, org["id"], mode="billing", reason="Promo over").json()
    assert v["effective"]["plan"] == "solo" and v["controlled_by"] == "stripe" and v["override"] is None
    assert c.get("/api/radar").status_code == 402
    hist = v["history"]
    assert [h["change"] for h in hist] == ["removed", "manual_override"]
    assert hist[1]["previous"].startswith("Solo") and hist[1]["new"].startswith("Growth") and hist[1]["admin_id"]


def test_complimentary_access_and_expiry(client, make_client, stripe):
    org, c = _account(client, make_client, "Comp Co")
    assert c.get("/api/radar").status_code == 402  # no plan → demo only
    until = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    v = _assign(client, org["id"], mode="complimentary", plan="teams", expires_at=until, reason="Pilot").json()
    assert v["effective"]["plan"] == "teams" and v["billing"]["live"] is False and v["override"]["expires_at"]
    assert c.get("/api/radar").status_code == 200
    assert c.get("/api/billing/overview").json()["plan"]["status"] == "none"  # nothing billed

    # Replacing an override keeps a single active one.
    _assign(client, org["id"], mode="complimentary", plan="managed", expires_at=until, reason="Bigger pilot")
    assert c.get("/api/billing/entitlements").json()["plan"] == "managed"

    from sqlalchemy import select

    from app.models.billing import EntitlementOverride
    from app.services import entitlements

    async def age(db):
        rows = (await db.execute(select(EntitlementOverride).where(
            EntitlementOverride.org_id == uuid.UUID(org["id"]), EntitlementOverride.revoked_at.is_(None)))).scalars().all()
        assert len(rows) == 1
        rows[0].expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
    _db(age)
    # Access falls back the moment it ends, even before the sweeper runs…
    assert c.get("/api/billing/entitlements").json()["source"] == "no_plan"
    assert c.get("/api/radar").status_code == 402
    # …and the sweeper records it.
    assert _db(entitlements.expire_overrides) == 1 and _db(entitlements.expire_overrides) == 0
    hist = client.get(f"/api/admin/billing/orgs/{org['id']}/plan").json()["history"]
    assert hist[0]["change"] == "expired" and hist[0]["admin_id"] is None


def test_validation_and_only_platform_admins(client, make_client, stripe):
    org, c = _account(client, make_client, "Self Grant Co")
    assert _assign(client, org["id"], mode="manual", plan="nope").status_code == 400
    assert _assign(client, org["id"], mode="manual", plan="teams_legacy").status_code == 400
    assert _assign(client, org["id"], mode="manual", plan="growth",
                   expires_at="2000-01-01T00:00:00Z").status_code == 400
    assert client.post(f"/api/admin/billing/orgs/{org['id']}/overrides",
                       json={"key": "plan", "value": "teams", "reason": "old path"}).status_code == 400
    # The account's own owner can't grant themselves anything (owner role ≠ platform admin).
    for call in (lambda: c.put(f"/api/admin/billing/orgs/{org['id']}/plan", json={"mode": "complimentary", "plan": "managed"}),
                 lambda: c.get(f"/api/admin/billing/orgs/{org['id']}/plan"),
                 lambda: c.post(f"/api/admin/billing/orgs/{org['id']}/overrides", json={"key": "radar", "value": True, "reason": "me!"})):
        assert call().status_code in (401, 403)
    assert c.get("/api/radar").status_code == 402
    # A platform admin whose portal isn't unlocked can't either.
    admin_email = f"padmin-{uuid.uuid4().hex[:6]}@acme.dev"
    _new_account(client, name="Other", email=admin_email)

    async def make_admin(db):
        from sqlalchemy import select

        from app.models.account import User
        u = (await db.execute(select(User).where(User.email == admin_email))).scalar_one()
        u.is_superadmin = True
        await db.commit()
    _db(make_admin)
    locked = _login(make_client, admin_email)
    assert locked.put(f"/api/admin/billing/orgs/{org['id']}/plan", json={"mode": "complimentary", "plan": "managed"}).status_code == 423


def test_radar_paid_growth_and_org_isolation(client, make_client, stripe):
    org_a, a = _account(client, make_client, "Radar Growth Co")
    _subscribe(client, a, stripe, "growth")
    assert a.get("/api/radar").json() == {"crms": []}
    assert a.post("/api/radar/close/scan").status_code == 404  # entitled; just no CRM connected
    org_b, b = _account(client, make_client, "Radar Solo Co")
    _subscribe(client, b, stripe, "solo")
    d = b.get("/api/radar").json()["detail"]
    assert d["code"] == "plan_limit" and d["feature"] == "radar" and d["suggest"]["plan"] == "growth"
    assert b.post("/api/radar/close/scan").status_code == 402

    # A scan saved for account A can't be used from another entitled account.
    from app.models.crm import CrmConnection, CrmScan

    async def seed(db):
        conn = CrmConnection(org_id=uuid.UUID(org_a["id"]), provider="close", method="api_key", config={})
        db.add(conn)
        await db.flush()
        scan = CrmScan(org_id=conn.org_id, connection_id=conn.id, result={"scanned": 1, "plays": []})
        db.add(scan)
        await db.commit()
        return str(scan.id)
    scan_id = _db(seed)
    _assign(client, org_b["id"], mode="manual", plan="growth", reason="test")
    agent = b.get("/api/agents/").json()[0]
    r = b.post(f"/api/radar/scans/{scan_id}/launch", json={"play": "hot", "agent_id": agent["id"], "mode": "campaign"})
    assert r.status_code == 404
    assert [c["provider"] for c in b.get("/api/radar").json()["crms"]] == []  # B never sees A's CRM


def test_radar_plans_are_configurable(client, make_client, stripe):
    org, c = _account(client, make_client, "Config Co")
    _subscribe(client, c, stripe, "solo")
    from app.services.billing import settings_store

    async def allow_solo(db):
        await settings_store.set_value(db, "radar_plans", ["solo", "growth", "teams", "managed"], None, reason="test")
        await db.commit()

    async def reset(db):
        await settings_store.set_value(db, "radar_plans", ["growth", "teams", "managed"], None, reason="test")
        await db.commit()
    _db(allow_solo)
    try:
        assert c.get("/api/radar").status_code == 200
    finally:
        _db(reset)
    assert c.get("/api/radar").status_code == 402
    assert catalog.PLANS["growth"]["limits"]["radar"] and not catalog.PLANS["solo"]["limits"]["radar"]
    assert time.time()  # keep imports used
