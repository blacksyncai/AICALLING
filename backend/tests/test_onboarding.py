import asyncio
import uuid

from tests.test_accounts import _login, _new_account


def _orphan_login(client, make_client):
    """A login that isn't in any account (what a self-serve sign-up looks like)."""
    from sqlalchemy import delete, select

    from app.database import AsyncSessionLocal
    from app.models.account import Membership, User

    _, email = _new_account(client, name="Placeholder")

    async def drop():
        async with AsyncSessionLocal() as db:
            u = (await db.execute(select(User).where(User.email == email))).scalar_one()
            await db.execute(delete(Membership).where(Membership.user_id == u.id))
            u.active_org_id = None
            await db.commit()

    asyncio.run(drop())
    return _login(make_client, email)


def test_trial_onboarding_real_estate(client, make_client):
    c = _orphan_login(client, make_client)
    assert c.get("/api/agents/").status_code == 403  # no account yet
    opts = c.get("/api/onboarding/options").json()
    assert opts["trial_credits"] == 30 and "real_estate" in opts["lead_finder_industries"]
    assert any(i["key"] == "logistics" for i in opts["industries"])

    r = c.post("/api/onboarding/start", json={"company": "Summit Realty", "industry": "real_estate",
                                              "goals": ["expired_listings", "fsbo_prospecting", "bogus"],
                                              "team_size": "2_5", "timezone": "America/Chicago"})
    assert r.status_code == 201, r.text
    org = r.json()["org"]
    assert org["name"] == "Summit Realty" and org["industry"] == "real_estate"
    assert org["lead_finder_enabled"] is True and org["credits_balance"] == 30
    assert org["onboarding"]["goals"] == ["expired_listings", "fsbo_prospecting"]
    agents = c.get("/api/agents/").json()
    assert [a["template"] for a in agents] == ["welcome_demo"]
    demo = c.get(f"/api/agents/{agents[0]['id']}").json()
    assert "Summit Realty" in demo["system_prompt"] and "Expired Listings" in demo["system_prompt"]
    assert c.get("/api/business-profile").json()["industry"] == "real_estate"
    # Only once per login.
    assert c.post("/api/onboarding/start", json={"company": "Again", "industry": "other"}).status_code == 409


def test_trial_onboarding_logistics_has_no_lead_finder(client, make_client):
    c = _orphan_login(client, make_client)
    assert c.post("/api/onboarding/start", json={"company": "Acme Freight", "industry": "nope"}).status_code == 422
    org = c.post("/api/onboarding/start", json={"company": "Acme Freight", "industry": "logistics"}).json()["org"]
    assert org["lead_finder_enabled"] is False and org["industry"] == "logistics"


def test_signup_sends_welcome_then_walkthrough_offer_a_day_later(client, make_client, monkeypatch):
    import time
    from datetime import datetime, timedelta, timezone

    from app.config import settings
    from app.database import AsyncSessionLocal
    from app.services import onboarding_emails

    sent: list[tuple[str, str, str]] = []

    async def fake_send(to, subject, body):
        sent.append((to, subject, body))
        return True

    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(onboarding_emails, "send_email", fake_send)

    c = _orphan_login(client, make_client)
    assert c.post("/api/onboarding/start", json={"company": "Welcome Co", "industry": "other"}).status_code == 201
    for _ in range(50):
        if sent:
            break
        time.sleep(0.05)
    assert len(sent) == 1 and "Welcome" in sent[0][1] and "Welcome Co" in sent[0][2]
    email = sent[0][0]

    async def sweep(at):
        async with AsyncSessionLocal() as db:
            return await onboarding_emails.send_due_followups(db, now=at)

    now = datetime.now(timezone.utc)
    assert asyncio.run(sweep(now + timedelta(hours=2))) == 0          # too early
    assert asyncio.run(sweep(now + timedelta(hours=25))) == 1         # the next day
    assert sent[-1][0] == email and "walkthrough" in sent[-1][2] and "cal.com" in sent[-1][2]
    assert asyncio.run(sweep(now + timedelta(hours=26))) == 0         # only once


def test_funeral_home_onboarding(client, make_client):
    c = _orphan_login(client, make_client)
    opts = c.get("/api/onboarding/options").json()
    fh = next(i for i in opts["industries"] if i["key"] == "funeral_services")
    assert fh["label"] == "Funeral Homes" and "cremation" in fh["hint"]
    goals = [s["key"] for s in opts["specialties"]["funeral_services"]] if "specialties" in opts else ["first_call_answering"]
    assert "first_call_answering" in goals
    r = c.post("/api/onboarding/start", json={"company": "Peaceful Rest Funeral Home", "industry": "funeral_services",
                                              "goals": ["first_call_answering", "preplanning_inquiries"],
                                              "website": "peacefulrest.example"})
    assert r.status_code == 201, r.text
    assert r.json()["org"]["industry"] == "funeral_services"
    demo = c.get(f"/api/agents/{c.get('/api/agents/').json()[0]['id']}").json()
    assert "Funeral Homes" in demo["system_prompt"] and "24/7 First Call Answering" in demo["system_prompt"]
