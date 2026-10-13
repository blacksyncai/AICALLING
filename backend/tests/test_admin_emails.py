import asyncio
import uuid


def _new_user(email, first="Dana", org_name="Late Signup Co", industry="real_estate"):
    from app.database import AsyncSessionLocal
    from app.models.account import Membership, Organization, User

    async def go():
        async with AsyncSessionLocal() as db:
            org = Organization(id=uuid.uuid4(), name=org_name, industry=industry)
            user = User(id=uuid.uuid4(), email=email, first_name=first, active_org_id=org.id)
            db.add_all([org, user])
            await db.flush()
            db.add(Membership(user_id=user.id, org_id=org.id, role="owner"))
            await db.commit()
            return str(user.id)
    return asyncio.run(go())


def test_admin_sends_catch_up_emails_once(client, monkeypatch):
    from app.config import settings
    from app.services import email

    sent = []

    async def fake_send(to, subject, html, sender=None):
        sent.append((to, subject, html))
        return True

    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(email, "send_email", fake_send)
    a = _new_user(f"late-{uuid.uuid4().hex[:6]}@example.com")
    b = _new_user(f"late-{uuid.uuid4().hex[:6]}@example.com", first="Sam", org_name="Second Co")

    data = client.get("/api/admin/emails").json()
    assert [k["key"] for k in data["kinds"]] == ["welcome", "catchup", "walkthrough"]
    row = next(u for u in data["users"] if u["id"] == a)
    assert row["account"] == "Late Signup Co" and row["sent"] == {"welcome": None, "catchup": None, "walkthrough": None}

    p = client.get("/api/admin/emails/preview", params={"kind": "catchup", "user_id": a}).json()
    assert p["subject"] == "Your BlackSync workspace is waiting"
    assert "Hi Dana, your workspace is waiting." in p["html"] and "Late Signup Co" in p["html"]
    assert "Real Estate" in p["html"]

    r = client.post("/api/admin/emails/send", json={"kind": "catchup", "user_ids": [a, b]}).json()
    assert len(r["sent"]) == 2 and not r["skipped"] and not r["failed"]
    # A second send skips them (no duplicates) unless the admin chooses to resend.
    r = client.post("/api/admin/emails/send", json={"kind": "catchup", "user_ids": [a]}).json()
    assert r["sent"] == [] and len(r["skipped"]) == 1
    r = client.post("/api/admin/emails/send", json={"kind": "catchup", "user_ids": [a], "resend": True}).json()
    assert len(r["sent"]) == 1
    assert len(sent) == 3
    row = next(u for u in client.get("/api/admin/emails").json()["users"] if u["id"] == a)
    assert row["sent"]["catchup"] and row["sent"]["welcome"] is None


def test_admin_emails_are_admin_only(make_client):
    anon = make_client()
    assert anon.get("/api/admin/emails").status_code in (401, 403)
