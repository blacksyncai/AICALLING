"""Resend open/click tracking: sends are recorded, signed webhook events update them, admins see the result."""

import asyncio
import base64
import hashlib
import hmac
import json
import time
import uuid

SECRET = "whsec_" + base64.b64encode(b"test-signing-key-0123456789abcdef").decode()


def _signed(body: dict, secret: str = SECRET, ts: int | None = None) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    msg_id, ts = f"msg_{uuid.uuid4().hex[:8]}", str(ts or int(time.time()))
    key = base64.b64decode(secret.split("_", 1)[1])
    sig = base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + raw, hashlib.sha256).digest()).decode()
    return raw, {"svix-id": msg_id, "svix-timestamp": ts, "svix-signature": f"v1,{sig}",
                 "content-type": "application/json"}


def _event(etype: str, email_id: str, **data) -> dict:
    return {"type": etype, "created_at": "2026-10-15T12:00:00.000Z", "data": {"email_id": email_id, **data}}


def _message(resend_id: str):
    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.email_message import EmailMessage

    async def go():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(EmailMessage).where(EmailMessage.resend_id == resend_id))).scalar_one_or_none()
    return asyncio.run(go())


def test_signature_check_refuses_forged_and_stale_events():
    from app.routers.resend_hooks import valid_signature

    raw, h = _signed({"type": "email.opened"})
    assert valid_signature(SECRET, h["svix-id"], h["svix-timestamp"], raw, h["svix-signature"])
    assert not valid_signature(SECRET, h["svix-id"], h["svix-timestamp"], raw + b" ", h["svix-signature"])
    other = "whsec_" + base64.b64encode(b"another-key").decode()
    assert not valid_signature(other, h["svix-id"], h["svix-timestamp"], raw, h["svix-signature"])
    raw, h = _signed({"type": "email.opened"}, ts=int(time.time()) - 3600)
    assert not valid_signature(SECRET, h["svix-id"], h["svix-timestamp"], raw, h["svix-signature"])
    # Several signatures (key rotation): any match is enough.
    raw, h = _signed({"type": "x"})
    assert valid_signature(SECRET, h["svix-id"], h["svix-timestamp"], raw, "v1,bogus " + h["svix-signature"])


def test_status_only_moves_forward_and_bounces_win():
    from datetime import datetime, timezone

    from app.models.email_message import EmailMessage
    from app.routers.resend_hooks import apply_event

    at = datetime.now(timezone.utc)
    m = EmailMessage(resend_id="r", to_email="a@b.co", status="sent", open_count=0, click_count=0)
    apply_event(m, "opened", at, {})
    apply_event(m, "delivered", at, {})  # arrives late: doesn't move it back
    assert m.status == "opened" and m.delivered_at and m.open_count == 1
    apply_event(m, "clicked", at, {"click": {"link": "https://blacksync.si/x"}})
    apply_event(m, "opened", at, {})
    assert m.status == "clicked" and m.open_count == 2 and m.last_link == "https://blacksync.si/x"
    apply_event(m, "complained", at, {})
    apply_event(m, "opened", at, {})
    assert m.status == "complained"


def test_sends_are_recorded_and_webhook_events_update_them(client, monkeypatch):
    from app.config import settings
    from app.services import email

    rid = f"re_{uuid.uuid4().hex[:12]}"

    class FakeResp:
        status_code = 200
        text = ""

        def json(self):
            return {"id": rid}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(email.httpx, "AsyncClient", FakeClient)
    to = f"Track-{uuid.uuid4().hex[:6]}@Example.com"
    assert asyncio.run(email.send_email(to, "Hello", "<p>hi</p>", kind="welcome"))
    m = _message(rid)
    assert m and m.to_email == to.lower() and m.kind == "welcome" and m.status == "sent"

    # Not set up yet: refused, nothing changes.
    monkeypatch.setattr(settings, "resend_webhook_secret", "")
    raw, h = _signed(_event("email.opened", rid))
    assert client.post("/api/webhooks/resend", content=raw, headers=h).status_code == 503

    monkeypatch.setattr(settings, "resend_webhook_secret", SECRET)
    raw, h = _signed(_event("email.opened", rid))
    assert client.post("/api/webhooks/resend", content=raw, headers={**h, "svix-signature": "v1,forged"}).status_code == 401
    for etype in ("email.delivered", "email.opened", "email.clicked"):
        raw, h = _signed(_event(etype, rid, click={"link": "https://blacksync.si/login"}))
        assert client.post("/api/webhooks/resend", content=raw, headers=h).json()["ok"]
    m = _message(rid)
    assert m.status == "clicked" and m.delivered_at and m.opened_at and m.click_count == 1

    # Unknown event types are acknowledged and ignored; unknown emails are still recorded.
    raw, h = _signed({"type": "contact.created", "data": {}})
    assert client.post("/api/webhooks/resend", content=raw, headers=h).json()["ignored"] == "contact.created"
    other = f"re_{uuid.uuid4().hex[:12]}"
    raw, h = _signed(_event("email.bounced", other, to=["x@y.co"], subject="Old"))
    assert client.post("/api/webhooks/resend", content=raw, headers=h).status_code == 200
    assert _message(other).status == "bounced" and _message(other).to_email == "x@y.co"

    t = client.get("/api/admin/emails/tracking").json()
    assert t["configured"] and t["webhook_url"].endswith("/api/webhooks/resend") and "email.opened" in t["events"]
    assert t["last_30_days"]["opened"] >= 1 and t["last_30_days"]["bounced"] >= 1
    items = client.get("/api/admin/emails/activity").json()["items"]
    assert any(i["to"] == to.lower() and i["status"] == "clicked" for i in items)


def test_admin_saves_signing_secret(client, monkeypatch):
    from cryptography.fernet import Fernet

    from app.config import settings
    from app.services import secret_store

    monkeypatch.setattr(settings, "resend_webhook_secret", "")
    monkeypatch.setattr(settings, "secrets_encryption_key", Fernet.generate_key().decode())
    assert client.put("/api/admin/emails/tracking", json={"secret": "not-a-secret-value"}).status_code == 400
    r = client.put("/api/admin/emails/tracking", json={"secret": SECRET})
    assert r.status_code == 200 and r.json()["configured"] is True
    assert SECRET not in r.text  # never echoed back
    assert secret_store.get("resend_webhook_secret") == SECRET
    asyncio.run(_forget())


async def _forget():
    from app.database import AsyncSessionLocal
    from app.services import secret_store

    async with AsyncSessionLocal() as db:
        await secret_store.remove(db, "resend_webhook_secret")
        await db.commit()


def test_tracking_endpoints_are_admin_only(make_client):
    anon = make_client()
    assert anon.get("/api/admin/emails/tracking").status_code in (401, 403)
    assert anon.put("/api/admin/emails/tracking", json={"secret": SECRET}).status_code in (401, 403)


def test_webhook_needs_no_login(make_client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "resend_webhook_secret", SECRET)
    raw, h = _signed({"type": "contact.created", "data": {}})
    assert make_client().post("/api/webhooks/resend", content=raw, headers=h).status_code == 200
