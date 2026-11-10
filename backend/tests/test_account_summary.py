"""Admin sends an account its calling summary on demand."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from app.database import AsyncSessionLocal
from app.models.call_log import CallLog
from app.services import email
from tests.test_phone_numbers import _account


def test_admin_previews_and_sends_a_summary(client, make_client, monkeypatch):
    org, owner = _account(client, make_client, "Summary Email Co")
    sent = []

    async def fake_send(to, subject, html_body, sender=None, kind="other", idempotency_key=None):
        sent.append((to, subject, html_body, kind))
        return True

    monkeypatch.setattr(email, "send_email", fake_send)
    monkeypatch.setattr(email, "email_enabled", lambda: True)

    async def seed():
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            for outcome, secs, days in (("meeting_booked", 240, 1), ("interested", 120, 2), ("voicemail", 10, 2),
                                        ("no_answer", 0, 3), ("not_interested", 60, 20)):
                db.add(CallLog(id=uuid.uuid4(), org_id=uuid.UUID(org["id"]), call_type="outbound", to_phone="+16505550101",
                               livekit_room_name="r-" + uuid.uuid4().hex[:6], status="completed", outcome=outcome,
                               started_at=now - timedelta(days=days), duration_seconds=secs,
                               summary="Wants a 3 bed <b>home</b>." if outcome == "interested" else None))
            await db.commit()
    asyncio.run(seed())

    url = f"/api/admin/orgs/{org['id']}/summary-email"
    assert owner.get(url).status_code in (401, 403)  # platform admins only
    p = client.get(url, params={"period": "7d"}).json()
    s = p["stats"]
    assert (s["calls"], s["conversations"], s["meetings"], s["interested"], s["voicemails"]) == (4, 2, 1, 1, 1)
    assert p["default_recipients"] and "&lt;b&gt;home" in p["html"] and not sent  # preview sends nothing
    assert client.get(url, params={"period": "30d"}).json()["stats"]["calls"] == 5
    assert client.get(url, params={"period": "year"}).status_code == 400

    r = client.post(url, json={"period": "7d", "note": "Great week!", "recipients": ["Boss@Example.com", "not-an-email"]})
    assert r.status_code == 400 and not sent
    r = client.post(url, json={"period": "7d", "note": "Great week!", "recipients": ["Boss@Example.com"]})
    assert r.status_code == 200 and r.json()["sent"] == ["boss@example.com"]
    assert sent[0][0] == "boss@example.com" and "Great week!" in sent[0][2] and sent[0][3] == "account_summary"
    # No recipients given: it goes to the account's owner.
    r = client.post(url, json={"period": "today"})
    assert r.status_code == 200 and r.json()["sent"] == p["default_recipients"]
