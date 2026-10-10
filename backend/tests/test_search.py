import asyncio
import uuid
from datetime import datetime, timezone

import main
from app.routers import search as search_router

if not any(getattr(r, "path", "").startswith("/api/search") for r in main.app.routes):
    main.app.include_router(search_router.router)


def _new_account(client, name):
    email = f"owner-{uuid.uuid4().hex[:6]}@search.dev"
    r = client.post("/api/admin/orgs", json={
        "name": name, "owner_first_name": "Sam", "owner_last_name": "Reed", "owner_email": email,
        "password": "owner-pass-123", "credits": 0,
    })
    assert r.status_code == 201, r.text
    return r.json(), email


def _login(make_client, email):
    c = make_client()
    assert c.post("/api/auth/login", json={"email": email, "password": "owner-pass-123"}).status_code == 200
    return c


def _seed(c, org_id, tag):
    """A contact, renamed agent, campaign and phone call, all mentioning `tag`."""
    agent = c.get("/api/agents/").json()[0]
    assert c.patch(f"/api/agents/{agent['id']}", json={"name": f"{tag} Closer"}).status_code == 200
    contact = c.post("/api/contacts", json={"name": f"Jane {tag}", "phone": "+14155550111",
                                            "company": "Zephyr Labs", "email": "jane@zephyr.dev"}).json()
    campaign = c.post("/api/campaigns/", json={"name": f"{tag} Spring Push"}).json()

    from app.database import AsyncSessionLocal
    from app.models.call_log import CallLog

    call_id = uuid.uuid4()

    async def add_call():
        async with AsyncSessionLocal() as db:
            db.add(CallLog(id=call_id, org_id=uuid.UUID(org_id), agent_id=uuid.UUID(agent["id"]),
                           lead_id=uuid.UUID(contact["id"]), call_type="outbound", to_phone="+14155550111",
                           livekit_room_name=f"call-{call_id.hex[:8]}", status="completed",
                           outcome="interested", started_at=datetime.now(timezone.utc)))
            await db.commit()

    asyncio.run(add_call())
    return agent, contact, campaign, str(call_id)


def test_search_requires_login(make_client):
    assert make_client().get("/api/search?q=abc").status_code == 401


def test_search_short_query_returns_empty(client):
    r = client.get("/api/search?q=a")
    assert r.status_code == 200
    assert r.json() == {"contacts": [], "agents": [], "campaigns": [], "calls": []}


def test_search_finds_everything_in_account(client, make_client):
    tag = f"Qx{uuid.uuid4().hex[:5]}"
    org, email = _new_account(client, "Search Co")
    owner = _login(make_client, email)
    agent, contact, campaign, call_id = _seed(owner, org["id"], tag)

    body = owner.get("/api/search", params={"q": tag.lower()}).json()
    assert [c["id"] for c in body["contacts"]] == [contact["id"]]
    assert body["contacts"][0]["company"] == "Zephyr Labs" and body["contacts"][0]["phone"] == "+14155550111"
    assert [a["id"] for a in body["agents"]] == [agent["id"]]
    assert [c["id"] for c in body["campaigns"]] == [campaign["id"]]
    assert body["campaigns"][0]["status"] == "draft"
    assert [c["id"] for c in body["calls"]] == [call_id]
    call = body["calls"][0]
    assert call["contact_name"] == f"Jane {tag}" and call["outcome"] == "interested" and call["started_at"]

    # Company, email and phone match contacts; phone matches calls too.
    assert owner.get("/api/search", params={"q": "zephyr"}).json()["contacts"][0]["id"] == contact["id"]
    by_phone = owner.get("/api/search", params={"q": "5550111"}).json()
    assert by_phone["contacts"][0]["id"] == contact["id"] and by_phone["calls"][0]["id"] == call_id

    # Wildcards are literal.
    assert owner.get("/api/search", params={"q": "%%"}).json()["contacts"] == []


def test_search_caps_results(client, make_client):
    org, email = _new_account(client, "Many Contacts Co")
    owner = _login(make_client, email)
    csv = "name,phone\n" + "\n".join(f"Bulk Person {i},+1415555{2000 + i}" for i in range(12))
    assert owner.post("/api/contacts/import", json={"csv": csv}).status_code == 201
    assert len(owner.get("/api/search", params={"q": "bulk person"}).json()["contacts"]) == 8


def test_search_is_isolated_between_accounts(client, make_client):
    tag = f"Iso{uuid.uuid4().hex[:5]}"
    org_a, email_a = _new_account(client, "Alpha Co")
    org_b, email_b = _new_account(client, "Beta Co")
    a = _login(make_client, email_a)
    b = _login(make_client, email_b)
    _seed(a, org_a["id"], tag)

    assert any(a.get("/api/search", params={"q": tag}).json().values())
    assert b.get("/api/search", params={"q": tag}).json() == {"contacts": [], "agents": [], "campaigns": [], "calls": []}
    # The house account (super-admin, not impersonating) doesn't see it either.
    assert not any(client.get("/api/search", params={"q": tag}).json().values())
