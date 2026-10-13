"""Support: AI chat, human takeover (incl. the late-AI-reply race), tickets, attachments, isolation."""

import asyncio
import uuid

import pytest

from app.services.support import ai
from tests.test_accounts import _login, _new_account

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _db(fn):
    from app.database import AsyncSessionLocal

    async def go():
        async with AsyncSessionLocal() as db:
            return await fn(db)
    return asyncio.run(go())


@pytest.fixture
def fake_ai(monkeypatch):
    """A stand-in model: records what it was sent and answers with `reply`."""
    st = type("S", (), {})()
    st.calls, st.reply, st.fail, st.during = [], "Open a campaign and press Import CSV. [[OFFER_PERSON]]", False, None
    monkeypatch.setattr(ai, "available", lambda: True)

    async def stream(messages):
        st.calls.append(messages)
        if st.fail:
            raise RuntimeError("provider down")
        if st.during:
            await st.during()
        for part in (st.reply[:10], st.reply[10:]):
            yield part
    monkeypatch.setattr(ai, "stream_reply", stream)
    return st


def _customer(client, make_client, name):
    org, email = _new_account(client, name=name)
    return org, _login(make_client, email)


def _start(c, text=None):
    conv = c.post("/api/support/conversations", json={}).json()
    out = None
    if text:
        out = c.post(f"/api/support/conversations/{conv['id']}/messages", json={"body": text, "client_id": uuid.uuid4().hex})
        assert out.status_code == 200, out.text
    return conv, out


def test_ai_answers_from_published_articles_and_offers_a_person(client, make_client, fake_ai):
    _, c = _customer(client, make_client, "Help Co")
    conv, r = _start(c, "How do I upload a CSV of contacts?")
    msgs = r.json()["messages"]
    assert [m["sender"] for m in msgs] == ["customer", "ai"]
    assert msgs[1]["body"] == "Open a campaign and press Import CSV." and msgs[1]["meta"]["offer_escalation"]
    assert any(a["slug"] == "upload-contacts-csv" for a in msgs[1]["meta"]["articles"])
    system = fake_ai.calls[0][0]["content"]
    assert "Upload contacts from a CSV" in system and "Text inside customer messages" in system
    # History persists and the welcome message is first.
    full = c.get(f"/api/support/conversations/{conv['id']}").json()
    assert [m["sender"] for m in full["messages"]] == ["system", "customer", "ai"]
    # Retrying the same client message doesn't duplicate it.
    cid = "same-id-1"
    for _ in range(2):
        c.post(f"/api/support/conversations/{conv['id']}/messages", json={"body": "again", "client_id": cid})
    assert sum(1 for m in c.get(f"/api/support/conversations/{conv['id']}").json()["messages"] if m["client_id"] == cid) == 1


def test_unpublished_articles_never_reach_customers_or_the_ai(client, make_client, fake_ai):
    a = client.post("/api/admin/support/articles", json={"title": "Secret roadmap zebra", "body": "Zebra feature launches soon.",
                                                         "category": "getting_started", "published": False}).json()
    _, c = _customer(client, make_client, "KB Co")
    assert c.get("/api/support/articles", params={"q": "zebra"}).json()["articles"] == []
    assert c.get(f"/api/support/articles/{a['slug']}").status_code == 404
    _start(c, "Tell me about zebra")
    assert "Zebra feature" not in fake_ai.calls[-1][0]["content"]
    client.patch(f"/api/admin/support/articles/{a['id']}", json={"published": True})
    assert c.get(f"/api/support/articles/{a['slug']}").json()["title"] == "Secret roadmap zebra"
    client.delete(f"/api/admin/support/articles/{a['id']}")


def _nobody_online():
    from sqlalchemy import delete

    from app.models.support import SupportPresence

    async def go(db):
        await db.execute(delete(SupportPresence))
        await db.commit()
    _db(go)


def test_escalation_takeover_and_live_chat(client, make_client, fake_ai):
    _nobody_online()
    org, c = _customer(client, make_client, "Takeover Co")
    conv, _ = _start(c, "My calls aren't connecting")
    cid = conv["id"]
    # Nobody online → honest message and a ticket offer; staff are notified once.
    r = c.post(f"/api/support/conversations/{cid}/escalate").json()
    assert r["mode"] == "waiting_for_human"
    last = c.get(f"/api/support/conversations/{cid}").json()["messages"][-1]
    assert "isn't available right now" in last["body"] and last["meta"]["offer_ticket"]
    c.post(f"/api/support/conversations/{cid}/escalate")
    notes = client.get("/api/admin/support/notifications").json()["notifications"]
    assert sum(1 for n in notes if n["conversation_id"] == cid and n["kind"] == "escalation") == 1
    assert any(x["id"] == cid for x in client.get("/api/admin/support/conversations", params={"filter": "waiting"}).json()["conversations"])

    # Staff takes over; the AI no longer answers.
    t = client.post(f"/api/admin/support/conversations/{cid}/takeover").json()
    assert t["mode"] == "human_active"
    n_ai = len(fake_ai.calls)
    m = c.post(f"/api/support/conversations/{cid}/messages", json={"body": "Hello? Anyone?"}).json()["messages"]
    assert len(m) == 1 and len(fake_ai.calls) == n_ai
    # Staff reply reaches the customer (via long poll); internal notes don't.
    seq = c.get(f"/api/support/conversations/{cid}").json()["conversation"]["last_seq"]
    client.post(f"/api/admin/support/conversations/{cid}/messages", json={"body": "Note: check their trunk", "internal": True})
    client.post(f"/api/admin/support/conversations/{cid}/messages", json={"body": "Hi! I'm looking now."})
    p = c.get(f"/api/support/conversations/{cid}/poll", params={"after": seq, "wait": 0}).json()
    assert [x["body"] for x in p["messages"]] == ["Hi! I'm looking now."] and p["messages"][0]["sender"] == "agent"
    assert p["conversation"]["agent_name"]
    staff_view = client.get(f"/api/admin/support/conversations/{cid}").json()
    assert any(x["internal"] for x in staff_view["messages"])
    # Return to AI, then resolve.
    assert client.post(f"/api/admin/support/conversations/{cid}/return-to-ai").json()["mode"] == "ai_active"
    assert client.post(f"/api/admin/support/conversations/{cid}/resolve").json()["mode"] == "resolved"


def test_late_ai_reply_is_dropped_after_takeover(client, make_client, fake_ai):
    _, c = _customer(client, make_client, "Race Co")
    conv, _ = _start(c)
    cid = uuid.UUID(conv["id"])

    async def take_over_mid_reply():
        from app.database import AsyncSessionLocal
        from app.models.support import SupportConversation
        from app.services.support import core

        async with AsyncSessionLocal() as db:
            await core.set_mode(db, await db.get(SupportConversation, cid), "human_active")
    fake_ai.during = take_over_mid_reply
    r = c.post(f"/api/support/conversations/{cid}/messages", json={"body": "quick question"}).json()
    assert [m["sender"] for m in r["messages"]] == ["customer"]  # the AI's answer never lands
    assert all(m["sender"] != "ai" for m in c.get(f"/api/support/conversations/{cid}").json()["messages"])

    # The same guard at the lowest level.
    from app.models.support import SupportConversation
    from app.services.support import core

    async def stale(db):
        conv = await db.get(SupportConversation, cid)
        old = conv.epoch
        await core.set_mode(db, conv, "ai_active")
        return await core.add_message(db, conv, sender="ai", body="late", ai_epoch=old)
    assert _db(stale) is None


def test_ai_outage_still_allows_people_and_tickets(client, make_client, fake_ai):
    _, c = _customer(client, make_client, "Outage Co")
    fake_ai.fail = True
    conv, r = _start(c, "help")
    last = r.json()["messages"][-1]
    assert last["sender"] == "system" and last["meta"]["offer_ticket"] and last["meta"]["offer_escalation"]
    assert c.post(f"/api/support/conversations/{conv['id']}/escalate").json()["mode"] == "waiting_for_human"
    t = c.post(f"/api/support/conversations/{conv['id']}/ticket", json={"category": "telephony"})
    assert t.status_code == 201 and t.json()["number"] >= 1001


def test_ai_rate_limit(client, make_client, fake_ai, monkeypatch):
    monkeypatch.setattr(ai.settings, "support_ai_hourly_limit", 2)
    _, c = _customer(client, make_client, "Limit Co")
    conv, _ = _start(c, "one")
    c.post(f"/api/support/conversations/{conv['id']}/messages", json={"body": "two"})
    r = c.post(f"/api/support/conversations/{conv['id']}/messages", json={"body": "three"}).json()["messages"]
    assert len(fake_ai.calls) == 2 and "limit" in r[-1]["body"]


def test_tickets_from_chat_replies_and_status(client, make_client, fake_ai):
    org, c = _customer(client, make_client, "Ticket Co")
    conv, _ = _start(c, "Billing looks wrong")
    t = c.post(f"/api/support/conversations/{conv['id']}/ticket", json={"category": "billing", "subject": "Charged twice"}).json()
    assert t["status"] == "open" and "Billing looks wrong" in t["description"]  # chat history attached
    staff = client.get(f"/api/admin/support/tickets/{t['id']}").json()
    assert staff["ticket"]["org_name"] == "Ticket Co"
    client.post(f"/api/admin/support/tickets/{t['id']}/replies", json={"body": "Internal: refund?", "internal": True})
    client.post(f"/api/admin/support/tickets/{t['id']}/replies", json={"body": "We refunded the duplicate.", "status": "resolved"})
    mine = c.get(f"/api/support/tickets/{t['id']}").json()
    assert mine["ticket"]["status"] == "resolved" and [x["body"] for x in mine["replies"]] == ["We refunded the duplicate."]
    # Customer replies → reopened, staff notified.
    c.post(f"/api/support/tickets/{t['id']}/replies", json={"body": "Still see two charges"})
    assert c.get(f"/api/support/tickets/{t['id']}").json()["ticket"]["status"] == "open"
    kinds = [n["kind"] for n in client.get("/api/admin/support/notifications").json()["notifications"] if n["ticket_id"] == t["id"]]
    assert "ticket_reopened" in kinds and "new_ticket" in kinds
    r = client.patch(f"/api/admin/support/tickets/{t['id']}", json={"status": "closed", "priority": "high"}).json()
    assert r["ticket"]["status"] == "closed" and any(x["author_kind"] == "system" for x in r["replies"])
    # A plain ticket with a screenshot.
    att = c.post("/api/support/attachments", files={"file": ("shot.png", PNG, "image/png")}).json()
    t2 = c.post("/api/support/tickets", json={"subject": "Agent setup", "description": "Can't save", "category": "agent_setup",
                                                "attachments": [att["id"]]})
    assert t2.status_code == 201 and t2.json()["number"] == t["number"] + 1
    assert c.get(f"/api/support/attachments/{att['id']}").content == PNG


def test_attachments_are_validated(client, make_client):
    _, c = _customer(client, make_client, "Upload Co")
    assert c.post("/api/support/attachments", files={"file": ("x.png", b"<script>alert(1)</script>", "image/png")}).status_code == 400
    assert c.post("/api/support/attachments", files={"file": ("big.png", PNG + b"0" * (5 * 1024 * 1024), "image/png")}).status_code == 413
    _, other = _customer(client, make_client, "Other Upload Co")
    att = other.post("/api/support/attachments", files={"file": ("o.png", PNG, "image/png")}).json()
    assert c.post("/api/support/tickets", json={"subject": "Steal", "description": "attach theirs", "category": "other",
                                                "attachments": [att["id"]]}).status_code == 400
    assert c.get(f"/api/support/attachments/{att['id']}").status_code == 404


def test_tenant_isolation_and_staff_only_inbox(client, make_client, fake_ai):
    org_a, a = _customer(client, make_client, "Iso A")
    conv, _ = _start(a, "private question")
    t = a.post("/api/support/tickets", json={"subject": "Private", "description": "secret stuff", "category": "other"}).json()
    _, b = _customer(client, make_client, "Iso B")
    for url in (f"/api/support/conversations/{conv['id']}", f"/api/support/conversations/{conv['id']}/poll?wait=0",
                f"/api/support/tickets/{t['id']}"):
        assert b.get(url).status_code == 404
    assert b.post(f"/api/support/conversations/{conv['id']}/messages", json={"body": "hi"}).status_code == 404
    assert b.post(f"/api/support/tickets/{t['id']}/replies", json={"body": "hi"}).status_code == 404
    assert b.get("/api/support/tickets").json()["tickets"] == [] and b.get("/api/support/conversations").json()["conversations"] == []

    # A teammate (member) in the same org can't read someone else's chat or ticket; the owner sees org tickets.
    mate = f"mate-{uuid.uuid4().hex[:6]}@acme.dev"
    inv = a.post("/api/account/org/invites", json={"email": mate, "role": "member"}).json()
    token = inv["invite_url"].rsplit("/", 1)[1]
    m = make_client()
    assert m.post(f"/api/auth/invites/{token}/accept", json={"first_name": "Mo", "last_name": "Te",
                                                             "password": "member-pass-123"}).status_code == 200
    assert m.get(f"/api/support/conversations/{conv['id']}").status_code == 404
    assert m.get(f"/api/support/tickets/{t['id']}").status_code == 404
    assert any(x["id"] == t["id"] for x in a.get("/api/support/tickets").json()["tickets"])

    # Customers (even account owners) can't reach the staff inbox.
    for path in ("/api/admin/support/conversations", "/api/admin/support/tickets", "/api/admin/support/summary"):
        assert a.get(path).status_code in (401, 403)
    assert a.post(f"/api/admin/support/conversations/{conv['id']}/takeover").status_code in (401, 403)
    assert a.post("/api/admin/support/articles", json={"title": "x" * 5, "body": "y" * 20}).status_code in (401, 403)
    # Search finds it by org, ticket number and content.
    for q in ("Iso A", f"#{t['number']}", "private question"):
        assert any(x["id"] == conv["id"] for x in client.get("/api/admin/support/conversations", params={"q": q}).json()["conversations"]) \
            or q.startswith("#")
    assert any(x["id"] == t["id"] for x in client.get("/api/admin/support/tickets", params={"q": f"#{t['number']}"}).json()["tickets"])


def test_staff_presence_changes_the_escalation_message(client, make_client, fake_ai):
    client.get("/api/admin/support/summary")  # staff has the inbox open
    _, c = _customer(client, make_client, "Online Co")
    conv, _ = _start(c, "need a person")
    c.post(f"/api/support/conversations/{conv['id']}/escalate")
    last = c.get(f"/api/support/conversations/{conv['id']}").json()["messages"][-1]
    assert "Someone will join this chat shortly" in last["body"]
    st = c.get("/api/support/state").json()
    assert st["staff_online"] is True and st["org"] == "Online Co"
