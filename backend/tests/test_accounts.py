import asyncio
import uuid
from datetime import datetime, timedelta, timezone


def _new_account(client, name="Acme Roofing", email=None, credits=0):
    email = email or f"owner-{uuid.uuid4().hex[:6]}@acme.dev"
    r = client.post("/api/admin/orgs", json={
        "name": name, "owner_first_name": "Ava", "owner_last_name": "Stone", "owner_email": email,
        "password": "owner-pass-123", "credits": credits,
    })
    assert r.status_code == 201, r.text
    return r.json(), email


def _login(make_client, email, password="owner-pass-123"):
    c = make_client()
    r = c.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return c


def test_api_requires_login(make_client):
    c = make_client()
    assert c.get("/api/agents/").status_code == 401
    assert c.get("/api/auth/me").status_code == 401
    assert c.post("/api/auth/login", json={"email": "admin@test.dev", "password": "nope"}).status_code == 401


def test_sub_accounts_are_isolated(client, make_client, agent_id):
    org, email = _new_account(client)
    owner = _login(make_client, email)
    me = owner.get("/api/auth/me").json()
    assert me["org"]["name"] == "Acme Roofing" and me["role"] == "owner" and not me["user"]["is_superadmin"]

    agents = owner.get("/api/agents/").json()
    assert len(agents) == 1, "a new account starts with one ready-to-test agent"
    assert agent_id not in {a["id"] for a in agents}
    assert owner.get(f"/api/agents/{agent_id}").status_code == 404, "can't read another account's agent"
    assert owner.patch(f"/api/agents/{agent_id}", json={"name": "x"}).status_code == 404

    # Sub-account users can't reach the admin portal.
    assert owner.get("/api/admin/orgs").status_code == 403

    # The super-admin can open the account and see what the owner sees, then return.
    switched = client.post("/api/auth/switch-org", json={"org_id": org["id"]}).json()
    assert switched["impersonating"] and switched["org"]["id"] == org["id"]
    assert {a["id"] for a in client.get("/api/agents/").json()} == {a["id"] for a in agents}
    back = client.post("/api/auth/switch-org", json={"org_id": None}).json()
    assert not back["impersonating"]


def test_credits_gate_and_bill_phone_calls(client, make_client, monkeypatch):
    from app.config import settings
    from app.database import AsyncSessionLocal
    from app.models.call_log import CallLog

    monkeypatch.setattr(settings, "livekit_sip_outbound_trunk_id", "ST_test")
    org, email = _new_account(client, name="Zero Credits Co")
    owner = _login(make_client, email)
    agent = owner.get("/api/agents/").json()[0]

    r = owner.post(f"/api/agents/{agent['id']}/phone-call", json={"to_phone": "+14155550123"})
    assert r.status_code == 402 and "credits" in r.json()["detail"]

    r = client.post(f"/api/admin/orgs/{org['id']}/credits", json={"amount": 10, "note": "Trial"})
    assert r.status_code == 200 and r.json()["balance"] == 10

    # A 2m05s answered call (after 20s of ringing) bills exactly 2m05s at the agent's rate, once
    # (ringing isn't billed).
    call_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    async def make_call():
        async with AsyncSessionLocal() as db:
            db.add(CallLog(id=call_id, org_id=uuid.UUID(org["id"]), agent_id=uuid.UUID(agent["id"]),
                           call_type="outbound", to_phone="+14155550123", livekit_room_name="call-bill",
                           status="connected", started_at=now - timedelta(seconds=145),
                           answered_at=now - timedelta(seconds=125)))
            await db.commit()

    asyncio.run(make_call())
    transcript = [{"role": "assistant", "text": "Hi"}, {"role": "user", "text": "Hey"}]
    for _ in range(2):  # a duplicate report must not double-bill
        assert client.post(f"/internal/calls/{call_id}/outcome",
                           json={"outcome": "completed", "transcript": transcript}).status_code == 200

    credits = owner.get("/api/account/credits").json()
    call = owner.get(f"/api/calls/{call_id}").json()
    assert 125 <= call["duration_seconds"] <= 127
    rate = owner.get(f"/api/billing/agents/{agent['id']}/rate").json()["credits_per_minute"]
    d = call["duration_seconds"]
    used = round(round(d * rate * 1000 / 60) / 1000 + -(-d // 60) * 0.053, 3)  # AI time + phone fee per started minute
    assert call["credits_used"] == used
    assert credits["balance"] == round(10 - used, 3)
    assert [t["amount"] for t in credits["transactions"]] == [-used, 10]


def test_team_invites_roles_and_password(client, make_client):
    org, email = _new_account(client, name="Team Co")
    owner = _login(make_client, email)

    assert owner.patch("/api/account/org", json={"name": "Team Co LLC"}).json()["name"] == "Team Co LLC"
    assert owner.patch("/api/account/profile", json={"phone": "+15551234567"}).json()["phone"] == "+15551234567"

    inv = owner.post("/api/account/org/invites", json={"email": "Rep@Team.dev", "role": "member"}).json()
    assert inv["emailed"] is False and "/invite/" in inv["invite_url"]
    token = inv["invite_url"].rsplit("/", 1)[1]

    guest = make_client()
    info = guest.get(f"/api/auth/invites/{token}").json()
    assert info == {"email": "rep@team.dev", "org_name": "Team Co LLC", "role": "member", "existing_user": False}
    assert guest.post(f"/api/auth/invites/{token}/accept", json={"first_name": "Rep", "password": "short"}).status_code == 400
    joined = guest.post(f"/api/auth/invites/{token}/accept",
                        json={"first_name": "Rep", "last_name": "One", "password": "rep-pass-123"}).json()
    assert joined["org"]["id"] == org["id"] and joined["role"] == "member"
    assert guest.get(f"/api/auth/invites/{token}").status_code == 404, "invite links are single-use"

    # Members can work in the account but not manage it.
    assert guest.get("/api/agents/").status_code == 200
    assert guest.patch("/api/account/org", json={"name": "Hijack"}).status_code == 403
    assert guest.post("/api/account/org/invites", json={"email": "x@y.dev"}).status_code == 403
    team = owner.get("/api/account/org").json()
    assert {m["email"] for m in team["members"]} == {email, "rep@team.dev"}

    # The last owner can't be demoted.
    owner_m = next(m for m in team["members"] if m["role"] == "owner")
    assert owner.patch(f"/api/account/org/members/{owner_m['membership_id']}", json={"role": "member"}).status_code == 400

    # Changing a password signs out other sessions.
    other = _login(make_client, email)
    assert owner.post("/api/account/password", json={"current_password": "wrong", "new_password": "new-pass-123"}).status_code == 400
    assert owner.post("/api/account/password", json={"current_password": "owner-pass-123", "new_password": "new-pass-123"}).status_code == 200
    assert owner.get("/api/auth/me").status_code == 200
    assert other.get("/api/auth/me").status_code == 401
    _login(make_client, email, "new-pass-123")


def test_contacts_crm(client, make_client):
    _, email = _new_account(client, name="CRM Co")
    c = _login(make_client, email)
    csv = "first name,last name,phone,company,industry\nJamie,Rivera,(415) 555-0123,Globex,SaaS\n" \
          "Sam,Lee,4155550124,Initech,\nBad,Row,12,,\nDupe,Person,415-555-0123,,\n"
    r = c.post("/api/contacts/import", json={"csv": csv, "tags": ["webinar"]}).json()
    assert r == {"created": 2, "skipped": 1, "duplicates": 1}

    listing = c.get("/api/contacts?q=globex").json()
    assert listing["total"] == 1
    jamie = listing["items"][0]
    assert jamie["name"] == "Jamie Rivera" and jamie["phone"] == "+14155550123"
    assert jamie["tags"] == ["webinar"] and jamie["custom_fields"] == {"industry": "SaaS"}
    assert c.get("/api/contacts?tag=webinar").json()["total"] == 2

    camp = c.post("/api/campaigns/", json={"name": "Follow up"}).json()
    all_ids = [x["id"] for x in c.get("/api/contacts").json()["items"]]
    assert c.post("/api/contacts/bulk", json={"ids": all_ids, "action": "add_to_campaign",
                                              "campaign_id": camp["id"]}).json()["updated"] == 2
    assert c.get(f"/api/campaigns/{camp['id']}").json()["total_targets"] == 2

    upd = c.patch(f"/api/contacts/{jamie['id']}", json={"status": "interested", "notes": "Call back Tuesday"}).json()
    assert upd["status"] == "interested" and upd["notes"] == "Call back Tuesday"
    assert c.get("/api/contacts").json()["status_counts"] == {"interested": 1, "new": 1}

    assert c.delete(f"/api/contacts/{jamie['id']}").status_code == 204
    assert c.get(f"/api/campaigns/{camp['id']}").json()["total_targets"] == 1
    # Deleting a campaign keeps its contacts.
    assert c.delete(f"/api/campaigns/{camp['id']}").status_code == 204
    assert c.get("/api/contacts").json()["total"] == 1

    overview = c.get("/api/calls/overview").json()
    assert overview["total_leads"] == 1 and "meaningful_calls" in overview and "follow_ups" in overview


def test_api_keys_and_webhooks(client, make_client):
    _, email = _new_account(client, name="API Co")
    c = _login(make_client, email)
    created = c.post("/api/integrations/api-keys", json={"name": "Zapier"}).json()
    key = created["key"]
    assert key.startswith("bsk_") and created["prefix"] == key[:10]

    api = make_client()
    assert api.get("/api/v1/me").status_code == 401
    assert api.get("/api/v1/me", headers={"Authorization": "Bearer bsk_wrong"}).status_code == 401
    h = {"Authorization": f"Bearer {key}"}
    assert api.get("/api/v1/me", headers=h).json()["account_name"] == "API Co"
    contact = api.post("/api/v1/contacts", headers=h, json={"name": "Form Fill", "phone": "+14155550199"})
    assert contact.status_code == 201 and contact.json()["source"] == "api"
    assert c.get("/api/contacts").json()["total"] == 1
    assert c.get("/api/integrations").json()["api_keys"][0]["last_used_at"]

    # Webhooks: validated on save, and never delivered to private/internal addresses.
    assert c.post("/api/integrations/webhooks", json={"url": "ftp://x"}).status_code == 400
    hook = c.post("/api/integrations/webhooks", json={"url": "http://127.0.0.1:8000/internal/x"}).json()
    assert hook["secret"].startswith("whsec_") and hook["events"] == ["call.completed", "meeting.booked", "contact.created"]
    test = c.post(f"/api/integrations/webhooks/{hook['id']}/test").json()
    assert test["ok"] is False and "public" in test["error"]

    assert c.delete(f"/api/integrations/api-keys/{created['id']}").status_code == 204
    assert api.get("/api/v1/me", headers=h).status_code == 401


def test_admin_portal(client):
    org, _ = _new_account(client, name="Portal Co", credits=25)
    orgs = client.get("/api/admin/orgs").json()["orgs"]
    row = next(o for o in orgs if o["id"] == org["id"])
    assert row["credits_balance"] == 25 and row["members"] == 1 and row["agents"] == 1
    assert row["owner"]["name"] == "Ava Stone"

    detail = client.get(f"/api/admin/orgs/{org['id']}").json()
    assert detail["transactions"][0]["note"] == "Starting credits"
    assert client.patch(f"/api/admin/orgs/{org['id']}", json={"status": "suspended"}).json()["status"] == "suspended"
    owner_id = detail["members"][0]["id"]
    reset = client.post(f"/api/admin/users/{owner_id}/reset-password").json()
    assert len(reset["temporary_password"]) >= 12

    generated = client.post("/api/admin/orgs", json={"name": "Gen Co", "owner_email": "gen@co.dev"}).json()
    assert generated["owner_status"] == "created" and generated["temporary_password"]
    invited = client.post("/api/admin/orgs", json={"name": "Inv Co", "owner_email": "inv@co.dev",
                                                   "send_invite": True}).json()
    assert invited["owner_status"] == "invited" and "/invite/" in invited["invite_url"]
    assert client.get("/api/admin/overview").json()["accounts"] >= 4


def test_admin_portal_needs_its_password(client, make_client):
    admin = make_client()
    admin.post("/api/auth/login", json={"email": "admin@test.dev", "password": "admin-pass-123"})
    assert admin.get("/api/admin/lock").json() == {"unlocked": False}
    assert admin.get("/api/admin/orgs").status_code == 423
    assert admin.post("/api/admin/unlock", json={"password": "nope"}).status_code == 403
    assert admin.post("/api/admin/unlock", json={"password": "portal-pass-456"}).status_code == 200
    assert admin.get("/api/admin/orgs").status_code == 200
    admin.post("/api/admin/lock")
    assert admin.get("/api/admin/orgs").status_code == 423

    # Knowing the password isn't enough without a platform-admin login.
    _, email = _new_account(client, name="Nosy Co")
    owner = _login(make_client, email)
    assert owner.post("/api/admin/unlock", json={"password": "portal-pass-456"}).status_code == 403


def test_new_accounts_start_with_the_welcome_demo(client, make_client):
    org, email = _new_account(client, name="Fresh Co")
    owner = _login(make_client, email)
    agents = owner.get("/api/agents/").json()
    assert len(agents) == 1
    demo = agents[0]
    assert demo["template"] == "welcome_demo" and demo["name"] == "Marissa"
    assert demo["voice_id"] == "97f03c16-fab2-4747-b655-9caefbd68fcf" and demo["max_duration_seconds"] == 420
    assert demo["first_message"].startswith("Hey, welcome to BlackSync AI!")
    assert demo["specialty"] == "Welcome Demo"
    assert "welcome_demo" not in [t["template"] for t in owner.get("/api/agents/templates/list").json()]


def test_admin_can_delete_an_account(client, make_client):
    from tests.test_meetings_analytics import _seed

    org, email = _new_account(client, name="Doomed Co", credits=20)
    owner = _login(make_client, email)
    agent = owner.get("/api/agents/").json()[0]
    _seed(org["id"], agent["id"], [{"outcome": "meeting_booked", "duration_seconds": 60}],
          lead={"name": "Pat", "phone": "+14155550199", "email": "", "company": ""}, campaign="List")

    r = client.request("DELETE", f"/api/admin/orgs/{org['id']}", json={"confirm_name": "doomed co"})
    assert r.status_code == 400  # name must match exactly
    house = client.get("/api/auth/me").json()["org"]
    assert client.request("DELETE", f"/api/admin/orgs/{house['id']}", json={"confirm_name": house["name"]}).status_code == 409
    # Members can't do it.
    assert owner.request("DELETE", f"/api/admin/orgs/{org['id']}", json={"confirm_name": "Doomed Co"}).status_code in (401, 403)

    r = client.request("DELETE", f"/api/admin/orgs/{org['id']}", json={"confirm_name": "Doomed Co"})
    assert r.status_code == 200, r.text
    assert r.json()["removed"]["agents"] == 1 and r.json()["removed"]["call_logs"] == 1
    assert client.get(f"/api/admin/orgs/{org['id']}").status_code == 404
    # The login stays, without an account.
    assert owner.get("/api/auth/me").json()["org"] is None


def test_unedited_welcome_demo_is_upgraded_edited_one_kept(client, make_client):
    import asyncio

    from app.agent import templates
    from app.database import AsyncSessionLocal
    from app.models.agent import Agent

    _, e1 = _new_account(client, name="Old Marissa Co")
    _, e2 = _new_account(client, name="Edited Marissa Co")
    a1 = _login(make_client, e1).get("/api/agents/").json()[0]["id"]
    a2 = _login(make_client, e2).get("/api/agents/").json()[0]["id"]

    async def setup():
        async with AsyncSessionLocal() as db:
            old = templates._PREVIOUS_WELCOME_PROMPTS[0] + templates._VOICE_RULES
            (await db.get(Agent, __import__("uuid").UUID(a1))).system_prompt = old
            (await db.get(Agent, __import__("uuid").UUID(a2))).system_prompt = old + "\nAlways mention our Austin office."
            await db.commit()
        await templates.refresh_welcome_agents()
        async with AsyncSessionLocal() as db:
            return ((await db.get(Agent, __import__("uuid").UUID(a1))).system_prompt,
                    (await db.get(Agent, __import__("uuid").UUID(a2))).system_prompt)

    p1, p2 = asyncio.run(setup())
    assert p1 == templates.WELCOME_DEMO["system_prompt"]
    assert "Austin office" in p2
