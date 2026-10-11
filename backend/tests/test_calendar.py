import uuid
from datetime import datetime, timedelta, timezone

from tests.test_accounts import _login, _new_account
from tests.test_meetings_analytics import _seed


def test_meeting_time_parser():
    from app.services.meeting_time import parse

    monday = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)  # 10am in Chicago
    assert parse("Tuesday at 2pm", monday, "America/Chicago").isoformat() == "2026-10-13T14:00:00-05:00"
    assert parse("Monday 4pm", monday, "America/Chicago").date().isoformat() == "2026-10-12"  # later today
    assert parse("Monday 9am", monday, "America/Chicago").date().isoformat() == "2026-10-19"  # already passed
    assert parse("March 5 at 3 PM", monday, "UTC").year == 2027
    assert parse("next week sometime", monday, "UTC") is None
    assert parse("sometime Tuesday", monday, "UTC") is None  # no time → not confirmed


def test_set_meeting_time_and_google_not_configured(client, make_client):
    org, email = _new_account(client, name="Calendar Co")
    owner = _login(make_client, email)
    agent = owner.get("/api/agents/").json()[0]
    ids, *_ = _seed(org["id"], agent["id"], [
        {"outcome": "meeting_booked", "agreed_meeting_time": "sometime next week", "duration_seconds": 90},
    ])
    m = owner.get("/api/meetings?status=all").json()["items"][0]
    assert m["start"] is None and m["start_source"] is None and m["duration_minutes"] == 30

    start = "2026-11-03T15:30:00-06:00"
    r = owner.patch(f"/api/meetings/{ids[0]}", json={"start": start, "duration_minutes": 45})
    assert r.status_code == 200, r.text
    assert r.json()["start_source"] == "set" and r.json()["duration_minutes"] == 45
    assert datetime.fromisoformat(r.json()["start"]) == datetime.fromisoformat(start)
    assert r.json()["follow_up_status"] == "scheduled" and "calendar_error" not in r.json()

    assert owner.patch(f"/api/meetings/{ids[0]}", json={"start": "2026-11-03T15:30:00"}).status_code == 422
    assert owner.patch(f"/api/meetings/{ids[0]}", json={"start": None}).json()["start"] is None

    st = owner.get("/api/calendar/google").json()
    assert st["configured"] is False and st["connected"] is False
    assert owner.post("/api/calendar/google/connect").status_code == 409
    ev = owner.get("/api/calendar/events", params={"start": "2026-11-01T00:00:00+00:00", "end": "2026-11-08T00:00:00+00:00"})
    assert ev.json() == {"connected": False, "events": []}


def test_google_calendar_sync(client, make_client, monkeypatch):
    from app.config import settings
    from app.services import google_calendar as gcal

    monkeypatch.setattr(settings, "google_client_id", "cid")
    monkeypatch.setattr(settings, "google_client_secret", "csecret")
    from cryptography.fernet import Fernet

    monkeypatch.setattr(settings, "secrets_encryption_key", Fernet.generate_key().decode())
    org, email = _new_account(client, name="GCal Co")
    owner = _login(make_client, email)
    agent = owner.get("/api/agents/").json()[0]
    ids, *_ = _seed(org["id"], agent["id"], [{"outcome": "meeting_booked", "agreed_meeting_time": "tomorrow at 10am"}])

    url = owner.post("/api/calendar/google/connect").json()["url"]
    assert "calendar.events" in url and "access_type=offline" in url
    state = url.split("state=")[1].split("&")[0]
    from urllib.parse import unquote

    calls = []

    async def fake_exchange(code, base):
        return "refresh-123", "owner@example.com"

    async def fake_upsert(conn, event_id, m, start, minutes):
        calls.append(("upsert", event_id, start, minutes))
        return event_id or "evt_1"

    async def fake_delete(conn, event_id):
        calls.append(("delete", event_id))

    monkeypatch.setattr(gcal, "exchange_code", fake_exchange)
    monkeypatch.setattr(gcal, "upsert_event", fake_upsert)
    monkeypatch.setattr(gcal, "delete_event", fake_delete)

    r = owner.get("/api/calendar/google/callback", params={"code": "c", "state": unquote(state)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("google=connected")
    st = owner.get("/api/calendar/google").json()
    assert st["connected"] and st["email"] == "owner@example.com" and "refresh" not in str(st)

    # Another account can't use this account's state; a tampered state is refused.
    bad = owner.get("/api/calendar/google/callback", params={"code": "c", "state": "nope"}, follow_redirects=False)
    assert bad.headers["location"].endswith("google=failed")

    assert owner.post("/api/calendar/google/sync").json()["synced"] == 1
    r = owner.patch(f"/api/meetings/{ids[0]}", json={"start": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()})
    assert r.json()["calendar_synced"] is True
    assert [c[0] for c in calls] == ["upsert", "upsert"] and calls[1][1] == "evt_1"
    r = owner.patch(f"/api/meetings/{ids[0]}", json={"status": "cancelled"})
    assert calls[-1] == ("delete", "evt_1") and r.json()["calendar_synced"] is False

    async def no_revoke(conn):
        return None

    monkeypatch.setattr(gcal, "revoke", no_revoke)
    assert owner.delete("/api/calendar/google").status_code == 204
    assert owner.get("/api/calendar/google").json()["connected"] is False
