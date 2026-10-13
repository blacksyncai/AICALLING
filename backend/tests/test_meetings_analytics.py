import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_accounts import _login, _new_account


@pytest.fixture(scope="module", autouse=True)
def _routers():
    # main.py registers these once the lead wires them up; until then, add them here.
    import main
    from app.routers import analytics, meetings

    paths = {getattr(r, "path", "") for r in main.app.routes}
    if not any(p.startswith("/api/meetings") for p in paths):
        main.app.include_router(meetings.router)
    if not any(p.startswith("/api/analytics") for p in paths):
        main.app.include_router(analytics.router)


def _seed(org_id: str, agent_id: str, calls: list[dict], lead: dict | None = None, campaign: str | None = None):
    """Insert a lead/campaign (optional) and CallLogs for an org; returns (call ids, lead id, campaign id)."""
    from app.database import AsyncSessionLocal
    from app.models.call_log import CallLog
    from app.models.campaign import Campaign
    from app.models.lead import Lead

    org = uuid.UUID(org_id)
    lead_id = uuid.uuid4() if lead else None
    campaign_id = uuid.uuid4() if campaign else None
    ids = [uuid.uuid4() for _ in calls]

    async def go():
        async with AsyncSessionLocal() as db:
            if campaign:
                db.add(Campaign(id=campaign_id, org_id=org, name=campaign, agent_id=uuid.UUID(agent_id)))
            if lead:
                db.add(Lead(id=lead_id, org_id=org, **lead))
            await db.flush()
            now = datetime.now(timezone.utc)
            for cid, spec in zip(ids, calls):
                spec = dict(spec)
                ago = spec.pop("ago", timedelta(hours=1))
                db.add(CallLog(id=cid, org_id=org, agent_id=uuid.UUID(agent_id), lead_id=lead_id,
                               campaign_id=campaign_id, call_type=spec.pop("call_type", "outbound"),
                               livekit_room_name=f"room-{cid.hex[:6]}", status="completed",
                               started_at=now - ago, ended_at=now - ago + timedelta(minutes=3), **spec))
            await db.commit()

    asyncio.run(go())
    return ids, lead_id, campaign_id


def test_meetings_list_and_status(client, make_client):
    org, email = _new_account(client, name="Meetings Co")
    owner = _login(make_client, email)
    agent = owner.get("/api/agents/").json()[0]

    ids, lead_id, _ = _seed(org["id"], agent["id"], [
        {"outcome": "meeting_booked", "agreed_meeting_time": "Tuesday 2pm", "meeting_link": "https://cal.com/x",
         "prospect_email": "dana@globex.dev", "summary": "Booked a demo.", "duration_seconds": 180},
        {"outcome": "meeting_booked", "agreed_meeting_time": "Friday 10am", "duration_seconds": 120,
         "ago": timedelta(days=2)},
        {"outcome": "not_interested", "duration_seconds": 40},
    ], lead={"name": "Dana Scully", "company": "Globex", "phone": "+14155550111", "email": "dana@globex.dev"},
        campaign="Q4 outreach")

    r = owner.get("/api/meetings?status=all")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] == 2
    first = data["items"][0]
    assert first["call_id"] == str(ids[0])
    assert first["contact"]["name"] == "Dana Scully" and first["contact"]["id"] == str(lead_id)
    assert first["meeting_time"] == "Tuesday 2pm" and first["meeting_link"] == "https://cal.com/x"
    assert first["campaign_name"] == "Q4 outreach" and first["agent_name"] == agent["name"]
    assert first["follow_up_status"] == "scheduled"
    assert data["stats"]["show_rate"] is None

    r = owner.patch(f"/api/meetings/{ids[0]}", json={"status": "completed"})
    assert r.status_code == 200 and r.json()["follow_up_status"] == "completed"
    assert owner.patch(f"/api/meetings/{ids[1]}", json={"status": "no_show"}).status_code == 200
    assert owner.patch(f"/api/meetings/{ids[1]}", json={"status": "bogus"}).status_code == 422
    # Only booked calls are meetings.
    assert owner.patch(f"/api/meetings/{ids[2]}", json={"status": "completed"}).status_code == 404

    data = owner.get("/api/meetings").json()
    assert data["stats"]["by_status"]["completed"] == 1 and data["stats"]["by_status"]["no_show"] == 1
    assert data["stats"]["show_rate"] == 0.5
    assert owner.get("/api/meetings?status=upcoming").json()["total"] == 0
    # The status survives alongside other extracted data on the call.
    assert owner.get(f"/api/calls/{ids[0]}").json()["extracted_data"]["_meeting_status"] == "completed"

    # Another account can't see or change these meetings.
    _, other_email = _new_account(client, name="Other Co")
    other = _login(make_client, other_email)
    assert other.get("/api/meetings").json()["total"] == 0
    assert other.patch(f"/api/meetings/{ids[0]}", json={"status": "cancelled"}).status_code == 404
    assert owner.get("/api/meetings").json()["items"][0]["follow_up_status"] == "completed"


def test_analytics_funnel(client, make_client):
    org, email = _new_account(client, name="Analytics Co")
    owner = _login(make_client, email)
    agent = owner.get("/api/agents/").json()[0]

    _seed(org["id"], agent["id"], [
        {"outcome": "no_answer", "duration_seconds": 0},
        {"outcome": "voicemail", "duration_seconds": 0},
        {"outcome": "not_interested", "duration_seconds": 12, "sentiment": "negative", "credits_charged": 1},
        {"outcome": "callback", "duration_seconds": 45, "sentiment": "neutral", "credits_charged": 1},
        {"outcome": "interested", "duration_seconds": 90, "sentiment": "positive", "credits_charged": 2},
        {"outcome": "meeting_booked", "duration_seconds": 240, "sentiment": "positive", "credits_charged": 4},
        # Outside the 7-day window and browser tests don't count.
        {"outcome": "meeting_booked", "duration_seconds": 200, "ago": timedelta(days=20)},
        {"outcome": "meeting_booked", "duration_seconds": 100, "call_type": "web"},
    ], campaign="Spring push")

    r = owner.get("/api/analytics?days=7")
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["funnel"] == {"dialed": 6, "connected": 4, "conversations": 3, "qualified": 2, "booked": 1}
    assert a["outcomes"]["meeting_booked"] == 1 and a["outcomes"]["no_answer"] == 1
    assert a["sentiment"] == {"positive": 2, "neutral": 1, "negative": 1}
    assert a["credits_used"] == 8
    assert a["avg_talk_seconds"] == round((12 + 45 + 90 + 240) / 4)
    assert len(a["by_hour"]) == 24 and sum(h["calls"] for h in a["by_hour"]) == 6
    assert sum(h["connected"] for h in a["by_hour"]) == 4
    [row] = a["by_agent"]
    assert row["name"] == agent["name"] and row["calls"] == 6 and row["booked"] == 1
    assert row["connect_rate"] == round(4 / 6, 4) and row["book_rate"] == 0.25
    [camp] = a["by_campaign"]
    assert camp["name"] == "Spring push" and camp["calls"] == 6 and camp["booked"] == 1

    assert owner.get("/api/analytics?days=30").json()["funnel"]["dialed"] == 7

    # Org-scoped: a fresh account sees nothing.
    _, other_email = _new_account(client, name="Empty Analytics Co")
    other = _login(make_client, other_email)
    assert other.get("/api/analytics?days=90").json()["funnel"]["dialed"] == 0


def test_calendar_booked_meeting_uses_agent_calendar_timezone():
    from types import SimpleNamespace

    from app.agent.runtime import build_instructions
    from app.routers.meetings import meeting_to_dict

    booked = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
    call = SimpleNamespace(
        id=uuid.uuid4(), extracted_data={}, agreed_meeting_time="Wed Oct 14 at 3:00 PM",
        meeting_link="https://cal.com/booking/x", ended_at=booked, started_at=booked, to_phone=None,
        prospect_email=None, agent_id=None, campaign_id=None, call_type="outbound", summary=None,
        follow_up_status=None,
    )
    agent = SimpleNamespace(name="A", calendar_timezone="America/New_York")
    # Org is in Jordan; the agent booked in New York time → 3 PM New York = 19:00 UTC.
    m = meeting_to_dict(call, None, agent, None, "Asia/Amman")
    assert datetime.fromisoformat(m["start"]).astimezone(timezone.utc).hour == 19

    text = build_instructions({"calendar_timezone": "America/New_York"}, {}, channel="phone")
    assert "(America/New_York)" in text
