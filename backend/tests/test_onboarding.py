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
    agents = {a["template"]: a for a in c.get("/api/agents/").json()}
    assert set(agents) == {"welcome_demo", "fsbo_prospecting"}
    # Real estate starts with the FSBO agent in the account's own name, paused until they launch it.
    fsbo = c.get(f"/api/agents/{agents['fsbo_prospecting']['id']}").json()
    assert fsbo["status"] == "paused" and fsbo["ai_disclosure"] is False
    assert "Maya from Summit Realty" in fsbo["system_prompt"] and "Central Time" in fsbo["system_prompt"]
    assert "Waldina" not in fsbo["system_prompt"] and fsbo["first_message"] == "Hey, this is {{name}}, right?"
    assert fsbo["builder"]["test_contact"]["name"] == "David"
    demo = c.get(f"/api/agents/{agents['welcome_demo']['id']}").json()
    assert "Summit Realty" in demo["system_prompt"] and "Expired Listings" in demo["system_prompt"]
    assert c.get("/api/business-profile").json()["industry"] == "real_estate"
    # Only once per login.
    assert c.post("/api/onboarding/start", json={"company": "Again", "industry": "other"}).status_code == 409


def test_real_estate_without_fsbo_goal_gets_no_fsbo_agent(client, make_client):
    c = _orphan_login(client, make_client)
    c.post("/api/onboarding/start", json={"company": "Lease Co", "industry": "real_estate", "goals": ["expired_listings"]})
    assert [a["template"] for a in c.get("/api/agents/").json()] == ["welcome_demo"]


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

    async def fake_send(to, subject, body, kind="other"):
        sent.append((to, subject, body))
        return True

    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(onboarding_emails, "send_email", fake_send)

    c = _orphan_login(client, make_client)
    assert c.post("/api/onboarding/start", json={"company": "Welcome Co", "industry": "other"}).status_code == 201
    for _ in range(50):
        if len(sent) >= 2:
            break
        time.sleep(0.05)
    welcome = [m for m in sent if not m[1].startswith("New signup")]
    assert len(welcome) == 1 and "Welcome Co" in welcome[0][2]
    email = welcome[0][0]
    # The team gets a heads-up too.
    alert = [m for m in sent if m[1].startswith("New signup")]
    assert len(alert) == 1 and alert[0][0] == settings.support_notify_email and email in alert[0][2]
    assert "/admin/accounts/" in alert[0][2] and "Welcome Co" in alert[0][1]

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


def test_onboarding_phone_is_normalized_saved_and_available_to_signup_alert(client, make_client, monkeypatch):
    from app.services import onboarding_emails

    captured = []
    monkeypatch.setattr(onboarding_emails, 'alert_new_signup', lambda user, *args: captured.append(user.phone))
    c = _orphan_login(client, make_client)
    r = c.post('/api/onboarding/start', json={'company': 'Connected Co', 'industry': 'other',
                                            'phone': '(415) 555-0123'})
    assert r.status_code == 201, r.text
    assert r.json()['user']['phone'] == '+14155550123'
    assert c.get('/api/auth/me').json()['user']['phone'] == '+14155550123'
    assert captured == ['+14155550123']


def test_onboarding_rejects_bad_phone_without_creating_workspace(client, make_client):
    c = _orphan_login(client, make_client)
    for phone in ['', '123', 'not a number', '+9991234567890']:
        r = c.post('/api/onboarding/start', json={'company': 'Invalid Co', 'industry': 'other', 'phone': phone})
        assert r.status_code == 422, r.text
    assert c.get('/api/auth/me').json()['org'] is None
    r = c.post('/api/onboarding/start', json={'company': 'International Co', 'industry': 'other',
                                            'phone': '+44 20 7946 0958'})
    assert r.status_code == 201, r.text
    assert r.json()['user']['phone'] == '+442079460958'


def test_marketing_signup(client, make_client):
    c = _orphan_login(client, make_client)
    options = c.get('/api/onboarding/options').json()
    assert any(i['key'] == 'marketing' and i['label'] == 'Marketing' for i in options['industries'])
    response = c.post('/api/onboarding/start', json={'company': 'Bright Agency', 'industry': 'marketing'})
    assert response.status_code == 201, response.text
    assert response.json()['org']['industry'] == 'marketing'
    assert c.get('/api/business-profile').json()['industry'] == 'marketing'
