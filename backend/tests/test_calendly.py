"""Calendly as the agent's booking calendar: event types, availability, booking (fake Calendly API)."""

import asyncio
import datetime as dt
import json

import httpx
import pytest

from app.services import calendar

ET = "a1b2c3d4-0000-4000-8000-000000000001"


@pytest.fixture
def calendly(monkeypatch):
    state = {"calls": [], "location": "zoom_conference", "fail": None}
    soon = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)).replace(hour=16, minute=0, second=0, microsecond=0)

    def handler(req: httpx.Request):
        state["calls"].append((req.method, req.url.path, dict(req.url.params), json.loads(req.content or b"null")))
        if state["fail"]:
            return httpx.Response(state["fail"], json={"message": "nope"})
        assert req.headers["authorization"] == "Bearer pat_123"
        if req.url.path == "/users/me":
            return httpx.Response(200, json={"resource": {"uri": "https://api.calendly.com/users/U1"}})
        if req.url.path == "/event_types":
            return httpx.Response(200, json={"collection": [{"uri": f"https://api.calendly.com/event_types/{ET}",
                "name": "Intro call", "duration": 30, "scheduling_url": "https://calendly.com/x/intro",
                "locations": [{"kind": "outbound_call"}]}]})
        if req.url.path == "/event_type_available_times":
            start = dt.datetime.fromisoformat(req.url.params["start_time"].replace("Z", "+00:00"))
            if start > soon:
                return httpx.Response(200, json={"collection": []})
            return httpx.Response(200, json={"collection": [
                {"status": "available", "start_time": soon.strftime("%Y-%m-%dT%H:%M:%SZ")},
                {"status": "available", "start_time": (soon + dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}]})
        if req.url.path == f"/event_types/{ET}":
            return httpx.Response(200, json={"resource": {"locations": [{"kind": state["location"]}]}})
        if req.url.path == "/invitees":
            return httpx.Response(201, json={"resource": {"event": "https://api.calendly.com/scheduled_events/E1",
                                                          "reschedule_url": "https://calendly.com/reschedulings/R1"}})
        return httpx.Response(404)

    real = httpx.AsyncClient
    monkeypatch.setattr(calendar.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    state["soon"] = soon
    return state


def test_slots_and_booking(calendly):
    slots = asyncio.run(calendar.fetch_slots("", ET, "pat_123", "America/New_York", provider="calendly"))
    assert [s["start"] for s in slots][0] == calendly["soon"].strftime("%Y-%m-%dT%H:%M:%SZ")
    reads = [c for c in calendly["calls"] if c[1] == "/event_type_available_times"]
    assert len(reads) == 2 and reads[0][2]["event_type"] == f"https://api.calendly.com/event_types/{ET}"

    calendly["location"] = "outbound_call"
    link = asyncio.run(calendar.create_booking(slots[0]["start"], "jo@example.com", "Jo Lee", ET, "pat_123",
                                               "America/New_York", provider="calendly", phone="+14155550123"))
    assert link == "https://calendly.com/reschedulings/R1"
    body = calendly["calls"][-1][3]
    assert body["event_type"].endswith(ET) and body["start_time"] == slots[0]["start"]
    assert body["invitee"] == {"name": "Jo Lee", "email": "jo@example.com", "timezone": "America/New_York"}
    assert body["location"] == {"kind": "outbound_call", "location": "+14155550123"}

    # A host-calls-invitee event can't be booked without the contact's number.
    with pytest.raises(calendar.CalendarUnavailable):
        asyncio.run(calendar.create_booking(slots[0]["start"], "jo@example.com", "Jo", ET, "pat_123", None, provider="calendly"))
    # Zoom-style events just pass the location kind.
    calendly["location"] = "zoom_conference"
    asyncio.run(calendar.create_booking(slots[0]["start"], "jo@example.com", "Jo", ET, "pat_123", None, provider="calendly"))
    assert calendly["calls"][-1][3]["location"] == {"kind": "zoom_conference"}


def test_failures_never_pretend(calendly):
    calendly["fail"] = 500
    with pytest.raises(calendar.CalendarUnavailable):
        asyncio.run(calendar.fetch_slots("", ET, "pat_123", None, provider="calendly"))
    with pytest.raises(calendar.CalendarUnavailable):
        asyncio.run(calendar.create_booking("2030-01-01T16:00:00Z", "a@b.co", "A", ET, "pat_123", None, provider="calendly"))
    # Calendly never borrows the server's Cal.com account when its own token is missing.
    with pytest.raises(calendar.CalendarUnavailable):
        asyncio.run(calendar.fetch_slots("", ET, "", None, provider="calendly"))


def test_editor_loads_event_types_and_saves_calendly(client, calendly, monkeypatch):
    from cryptography.fernet import Fernet

    from app.config import settings

    monkeypatch.setattr(settings, "secrets_encryption_key", Fernet.generate_key().decode())
    agent = client.post("/api/agents/", json={"template": "sales_sdr"}).json()
    types = client.post(f"/api/agents/{agent['id']}/calendly/event-types", json={"api_key": "pat_123"})
    assert types.status_code == 200, types.text
    assert types.json()["event_types"][0] == {"id": ET, "name": "Intro call", "duration": 30,
                                              "scheduling_url": "https://calendly.com/x/intro", "locations": ["outbound_call"]}
    saved = client.patch(f"/api/agents/{agent['id']}", json={"enable_booking": True, "calendar_provider": "calendly",
                                                             "calcom_api_key": "pat_123", "calcom_event_type_id": ET}).json()
    assert saved["calendar_provider"] == "calendly" and saved["calcom_key_set"] and "pat_123" not in json.dumps(saved)
    # The saved token is reused when the editor reloads the list.
    assert client.post(f"/api/agents/{agent['id']}/calendly/event-types", json={}).status_code == 200
    ready = client.get(f"/api/agent-builder/agents/{agent['id']}/readiness").json()
    cal = next(c for c in ready["checks"] if c["key"] == "calendar")
    assert cal["status"] == "ok" and "Calendly" in cal["detail"]
    calendly["fail"] = 401
    bad = client.post(f"/api/agents/{agent['id']}/calendly/event-types", json={"api_key": "wrong"})
    assert bad.status_code == 400 and "token" in bad.json()["detail"]
