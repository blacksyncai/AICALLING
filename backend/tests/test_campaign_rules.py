"""Campaign calling rules: calling hours, automatic retries and Do-Not-Call."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.routers.campaigns import dial_eligibility, next_window_start, within_calling_hours

UTC = timezone.utc


def _camp(**kw):
    base = dict(call_window_start=None, call_window_end=None, call_days=None, timezone=None,
                max_attempts=None, retry_delay_minutes=None, retry_schedule=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _lead(**kw):
    base = dict(status="new", attempts=None, next_attempt_at=None, do_not_call=None)
    base.update(kw)
    return SimpleNamespace(**base)


# ── Calling-hours helpers ─────────────────────────────────────────────────────


def test_defaults_are_weekday_business_hours_new_york():
    c = _camp()
    # Wed 2026-10-14 14:00 UTC = 10:00 EDT → inside.
    assert within_calling_hours(c, datetime(2026, 10, 14, 14, 0, tzinfo=UTC))
    # Wed 12:00 UTC = 08:00 EDT → before the window.
    assert not within_calling_hours(c, datetime(2026, 10, 14, 12, 0, tzinfo=UTC))
    # Wed 21:00 UTC = 17:00 EDT → the end is exclusive.
    assert not within_calling_hours(c, datetime(2026, 10, 14, 21, 0, tzinfo=UTC))
    # Sat 2026-10-17 15:00 UTC = 11:00 EDT → weekend.
    assert not within_calling_hours(c, datetime(2026, 10, 17, 15, 0, tzinfo=UTC))


def test_timezone_is_respected():
    c = _camp(timezone="Europe/London", call_window_start="09:00", call_window_end="12:00")
    # Wed 08:30 UTC = 09:30 BST → inside London's window, but before New York's.
    now = datetime(2026, 10, 14, 8, 30, tzinfo=UTC)
    assert within_calling_hours(c, now)
    assert not within_calling_hours(_camp(), now)
    # Naive datetimes are treated as UTC.
    assert within_calling_hours(c, now.replace(tzinfo=None))


def test_next_window_start():
    c = _camp()
    inside = datetime(2026, 10, 14, 14, 0, tzinfo=UTC)
    assert next_window_start(c, inside) == inside
    # Wed 06:00 EDT → same day 09:00 EDT (13:00 UTC).
    assert next_window_start(c, datetime(2026, 10, 14, 10, 0, tzinfo=UTC)) == datetime(2026, 10, 14, 13, 0, tzinfo=UTC)
    # Fri 18:00 EDT → Mon 09:00 EDT.
    assert next_window_start(c, datetime(2026, 10, 16, 22, 0, tzinfo=UTC)) == datetime(2026, 10, 19, 13, 0, tzinfo=UTC)
    # Across the DST change: Fri 2026-10-30 evening → Mon 2026-11-02 09:00 EST (14:00 UTC).
    assert next_window_start(c, datetime(2026, 10, 30, 22, 0, tzinfo=UTC)) == datetime(2026, 11, 2, 14, 0, tzinfo=UTC)
    # Weekend-only campaign, asked on a Monday.
    weekend = _camp(call_days=[5, 6], timezone="UTC", call_window_start="10:00", call_window_end="11:00")
    assert next_window_start(weekend, datetime(2026, 10, 12, 9, 0, tzinfo=UTC)) == datetime(2026, 10, 17, 10, 0, tzinfo=UTC)


# ── Retry eligibility ─────────────────────────────────────────────────────────


def test_dial_eligibility():
    now = datetime(2026, 10, 14, 14, 0, tzinfo=UTC)
    no_retry, retry3 = _camp(), _camp(max_attempts=3)

    assert dial_eligibility(_lead(), no_retry, now) == "now"
    assert dial_eligibility(_lead(do_not_call=True), no_retry, now) is None
    # Default is a single try: an unanswered contact is done.
    assert dial_eligibility(_lead(status="no_answer", attempts=1), no_retry, now) is None
    # With retries: due, not yet due, and out of tries.
    assert dial_eligibility(_lead(status="voicemail", attempts=1, next_attempt_at=now - timedelta(minutes=1)), retry3, now) == "now"
    assert dial_eligibility(_lead(status="no_answer", attempts=2, next_attempt_at=now + timedelta(hours=1)), retry3, now) == "later"
    assert dial_eligibility(_lead(status="failed", attempts=3, next_attempt_at=now - timedelta(hours=1)), retry3, now) is None
    # Answered outcomes are never retried; DNC beats everything.
    assert dial_eligibility(_lead(status="meeting_booked", attempts=1), retry3, now) is None
    assert dial_eligibility(_lead(status="no_answer", attempts=1, do_not_call=True), retry3, now) is None
    # Naive (SQLite) timestamps compare fine.
    naive_due = (now - timedelta(minutes=5)).replace(tzinfo=None)
    assert dial_eligibility(_lead(status="no_answer", attempts=1, next_attempt_at=naive_due), retry3, now) == "now"


# ── API ───────────────────────────────────────────────────────────────────────


def test_campaign_rules_create_update_and_validation(client):
    r = client.post("/api/campaigns/", json={"name": "Rules"})
    assert r.status_code == 201
    c = r.json()
    assert c["call_window_start"] == "09:00" and c["call_window_end"] == "17:00"
    assert c["call_days"] == [0, 1, 2, 3, 4] and c["timezone"] == "America/New_York"
    assert c["max_attempts"] == 1 and c["retry_delay_minutes"] == 60 and c["pending_retries"] == 0
    assert "within_calling_hours" in c and "next_window_at" in c

    r = client.post("/api/campaigns/", json={
        "name": "London", "call_window_start": "08:30", "call_window_end": "18:00", "call_days": [5, 0, 0],
        "timezone": "Europe/London", "max_attempts": 3, "retry_delay_minutes": 120})
    assert r.status_code == 201, r.text
    c2 = r.json()
    assert c2["call_days"] == [0, 5] and c2["timezone"] == "Europe/London" and c2["max_attempts"] == 3

    cid = c["id"]
    for bad in ({"call_window_start": "9am"}, {"call_window_start": "25:00"},
                {"call_window_start": "18:00"},  # after the default 17:00 end
                {"call_window_start": "10:00", "call_window_end": "10:00"},
                {"call_days": []}, {"call_days": [7]}, {"timezone": "Mars/Base"},
                {"max_attempts": 6}, {"max_attempts": 0}, {"retry_delay_minutes": 1}):
        r = client.patch(f"/api/campaigns/{cid}", json=bad)
        assert r.status_code == 400, (bad, r.text)
    assert client.post("/api/campaigns/", json={"name": "x", "timezone": "Nope/Nope"}).status_code == 400

    r = client.patch(f"/api/campaigns/{cid}", json={"call_window_end": "20:00", "call_days": [6],
                                                    "max_attempts": 5, "retry_delay_minutes": 1440})
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["call_window_end"] == "20:00" and c["call_days"] == [6] and c["max_attempts"] == 5
    assert client.get(f"/api/campaigns/{cid}").json()["retry_delay_minutes"] == 1440
    assert c["retry_schedule"] == [1440] * 4

    # A custom schedule: 15 min, 20 min, next day, then every other day.
    r = client.patch(f"/api/campaigns/{cid}", json={"retry_schedule": [15, 20, 1440, 2880, 2880]})
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["retry_schedule"] == [15, 20, 1440, 2880, 2880] and c["max_attempts"] == 6
    for bad in ({"retry_schedule": [1]}, {"retry_schedule": [60] * 11}, {"retry_schedule": [15 * 24 * 60]}):
        assert client.patch(f"/api/campaigns/{cid}", json=bad).status_code == 400, bad
    c = client.patch(f"/api/campaigns/{cid}", json={"retry_schedule": []}).json()
    assert c["max_attempts"] == 1 and c["retry_schedule"] == []
    # Going back to the simple fields drops the schedule.
    c = client.patch(f"/api/campaigns/{cid}", json={"max_attempts": 3, "retry_delay_minutes": 30}).json()
    assert c["retry_schedule"] == [30, 30]


def test_retry_schedule_spaces_each_try():
    from app.routers.campaigns import _record_attempt

    camp = _camp(max_attempts=4, retry_schedule=[15, 1440, 2880])
    lead = SimpleNamespace(attempts=0, last_called_at=None, next_attempt_at=None)
    now = datetime(2026, 1, 5, 15, tzinfo=UTC)
    waits = []
    for _ in range(3):
        _record_attempt(lead, camp, now)
        waits.append(lead.next_attempt_at - now)
    assert waits == [timedelta(minutes=15), timedelta(days=1), timedelta(days=2)]


@pytest.fixture
def dialing(monkeypatch):
    """Pretend phone calling is set up and capture dials instead of placing them."""
    from app.config import Settings, settings
    from app.services.outbound_call import call_service

    monkeypatch.setattr(settings, "livekit_sip_outbound_trunk_id", "ST_test")
    monkeypatch.setattr(Settings, "phone_ready", property(lambda self: True))
    dialed: list[str] = []

    async def fake_dispatch(lead, db, **kw):
        dialed.append(str(lead.id))
        return SimpleNamespace(id=uuid.uuid4(), status="initiated")

    monkeypatch.setattr(call_service, "dispatch_call", fake_dispatch)
    return dialed


def test_do_not_call_contacts(client, agent_id, dialing):
    camp = client.post("/api/campaigns/", json={"name": "DNC", "agent_id": agent_id}).json()
    ok = client.post("/api/contacts", json={"name": "Ok", "phone": "+14155550101", "campaign_id": camp["id"]}).json()
    dnc = client.post("/api/contacts", json={"name": "Nope", "phone": "+14155550102", "campaign_id": camp["id"]}).json()
    assert ok["do_not_call"] is False

    r = client.patch(f"/api/contacts/{dnc['id']}", json={"do_not_call": True})
    assert r.status_code == 200 and r.json()["do_not_call"] is True

    # The contacts list can filter on it.
    ids = {c["id"] for c in client.get("/api/contacts", params={"dnc": "true"}).json()["items"]}
    assert dnc["id"] in ids and ok["id"] not in ids
    ids = {c["id"] for c in client.get("/api/contacts", params={"dnc": "false", "campaign_id": camp["id"]}).json()["items"]}
    assert ids == {ok["id"]}

    # A direct call is refused.
    r = client.post(f"/api/contacts/{dnc['id']}/call", json={"agent_id": agent_id})
    assert r.status_code == 400 and r.json()["detail"] == "This contact is on your Do-Not-Call list."

    # Calling a selection skips them.
    r = client.post(f"/api/campaigns/{camp['id']}/call", json={"lead_ids": [ok["id"], dnc["id"]]})
    assert r.status_code == 200, r.text
    assert r.json()["lead_ids"] == [ok["id"]] and r.json()["skipped_dnc"] == 1
    assert dialing == [ok["id"]]
    r = client.post(f"/api/campaigns/{camp['id']}/call", json={"lead_ids": [dnc["id"]]})
    assert r.status_code == 400

    # The campaign's lead list shows the flag and the try count.
    leads = {l["id"]: l for l in client.get(f"/api/campaigns/{camp['id']}/leads").json()["leads"]}
    assert leads[dnc["id"]]["do_not_call"] is True and leads[ok["id"]]["attempts"] == 1

    # Bulk on/off.
    r = client.post("/api/contacts/bulk", json={"ids": [ok["id"], dnc["id"]], "action": "dnc_on"})
    assert r.status_code == 200 and r.json()["updated"] == 2
    assert client.get(f"/api/contacts/{ok['id']}").json()["do_not_call"] is True
    client.post("/api/contacts/bulk", json={"ids": [ok["id"], dnc["id"]], "action": "dnc_off"})
    assert client.get(f"/api/contacts/{dnc['id']}").json()["do_not_call"] is False


def test_queue_picks_due_retries_and_skips_dnc(client, agent_id):
    """The queue's lead picker: new first-come, due retries, and waits on pending ones."""
    import asyncio

    from app.database import AsyncSessionLocal
    from app.models.campaign import Campaign
    from app.models.lead import Lead
    from app.routers.campaigns import _next_lead

    camp = client.post("/api/campaigns/", json={"name": "Retry", "agent_id": agent_id, "max_attempts": 3}).json()
    org_id = uuid.UUID(client.get("/api/auth/me").json()["org"]["id"])
    cid = uuid.UUID(camp["id"])
    now = datetime.now(UTC)

    async def run():
        async with AsyncSessionLocal() as db:
            def add(name, **kw):
                lead = Lead(id=uuid.uuid4(), org_id=org_id, campaign_id=cid, name=name, phone="+14155550199",
                            created_at=now - timedelta(minutes=10 - len(name)), **kw)
                db.add(lead)
                return lead
            add("dnc", status="new", do_not_call=True)
            later = add("later", status="no_answer", attempts=1, next_attempt_at=now + timedelta(hours=1))
            add("done", status="no_answer", attempts=3)
            add("booked", status="meeting_booked", attempts=1)
            await db.commit()
            campaign = await db.get(Campaign, cid)

            lead, waiting, earliest = await _next_lead(db, campaign, now)
            assert lead is None and waiting == 1
            assert abs((earliest - later.next_attempt_at.replace(tzinfo=UTC)).total_seconds()) < 1

            due = add("due", status="voicemail", attempts=1, next_attempt_at=now - timedelta(minutes=1))
            await db.commit()
            lead, _, _ = await _next_lead(db, campaign, now)
            assert lead.id == due.id

    asyncio.run(run())
    assert client.get(f"/api/campaigns/{camp['id']}").json()["pending_retries"] == 2


def test_stuck_calling_contacts_get_their_retry(client, agent_id):
    """A contact left "calling" by a restart (its call never reported back) is redialed, not skipped forever."""
    import asyncio

    from app.database import AsyncSessionLocal
    from app.models.campaign import Campaign
    from app.models.call_log import CallLog
    from app.models.lead import Lead
    from app.routers.campaigns import _next_lead

    camp = client.post("/api/campaigns/", json={"name": "Stuck", "agent_id": agent_id, "max_attempts": 3}).json()
    org_id = uuid.UUID(client.get("/api/auth/me").json()["org"]["id"])
    cid = uuid.UUID(camp["id"])
    now = datetime.now(UTC)

    async def run():
        async with AsyncSessionLocal() as db:
            live = Lead(id=uuid.uuid4(), org_id=org_id, campaign_id=cid, name="live", phone="+14155550111",
                        status="calling", attempts=1, last_called_at=now - timedelta(minutes=2), created_at=now - timedelta(hours=2))
            stuck = Lead(id=uuid.uuid4(), org_id=org_id, campaign_id=cid, name="stuck", phone="+14155550112",
                         status="calling", attempts=1, last_called_at=now - timedelta(hours=1),
                         next_attempt_at=now - timedelta(minutes=30), created_at=now - timedelta(hours=1))
            talked = Lead(id=uuid.uuid4(), org_id=org_id, campaign_id=cid, name="talked", phone="+14155550113",
                          status="calling", attempts=1, last_called_at=now - timedelta(hours=1),
                          created_at=now - timedelta(hours=3))
            db.add_all([live, stuck, talked])
            db.add(CallLog(id=uuid.uuid4(), org_id=org_id, lead_id=talked.id, campaign_id=cid, call_type="outbound",
                           to_phone=talked.phone, livekit_room_name="call-talked", status="completed", started_at=now - timedelta(hours=1), ended_at=now - timedelta(minutes=55),
                           answered_at=now - timedelta(hours=1)))
            await db.commit()
            campaign = await db.get(Campaign, cid)
            lead, waiting, _ = await _next_lead(db, campaign, now)
            # The one who picked up is never redialed; the one who didn't gets their retry.
            assert talked.status == "completed"
            assert lead.id == stuck.id and lead.status == "no_answer" and waiting == 1  # live call still in progress

    asyncio.run(run())


def test_running_campaigns_resume_after_restart(client, agent_id, monkeypatch):
    import asyncio

    from app.database import AsyncSessionLocal
    from app.models.campaign import Campaign
    from app.routers import campaigns as c

    started: list[str] = []

    async def fake_queue(cid):
        started.append(cid)
        await asyncio.sleep(0.2)

    monkeypatch.setattr(c, "_process_call_queue", fake_queue)
    run_id = client.post("/api/campaigns/", json={"name": "Was running", "agent_id": agent_id}).json()["id"]
    idle_id = client.post("/api/campaigns/", json={"name": "Paused", "agent_id": agent_id}).json()["id"]

    async def go():
        async with AsyncSessionLocal() as db:
            (await db.get(Campaign, uuid.UUID(run_id))).status = "running"
            (await db.get(Campaign, uuid.UUID(idle_id))).status = "paused"
            await db.commit()
        await c.resume_running_campaigns()
        assert c.ensure_queue(run_id) is False  # already has a dialer — never two at once
        await asyncio.sleep(0.05)

    asyncio.run(go())
    assert run_id in started and idle_id not in started and started.count(run_id) == 1


def test_call_selected_leaves_the_campaign_status_alone(client, agent_id, dialing):
    camp = client.post("/api/campaigns/", json={"name": "Pick", "agent_id": agent_id}).json()
    a = client.post("/api/contacts", json={"name": "A", "phone": "+14155550111", "campaign_id": camp["id"]}).json()
    r = client.post(f"/api/campaigns/{camp['id']}/call", json={"lead_ids": [a["id"]]})
    assert r.status_code == 200 and dialing == [a["id"]]
    # A draft stays a draft — otherwise a restart would dial the whole list.
    assert client.get(f"/api/campaigns/{camp['id']}").json()["status"] == "draft"


def test_a_contact_already_on_a_call_is_never_dialed_again():
    import asyncio

    from app.services.outbound_call import LeadBusy, _IN_DIAL, call_service

    on_call = SimpleNamespace(id=uuid.uuid4(), status="calling", last_called_at=datetime.now(UTC))
    with pytest.raises(LeadBusy):
        asyncio.run(call_service.dispatch_call(on_call, None))
    dialing_now = SimpleNamespace(id=uuid.uuid4(), status="new", last_called_at=None)
    _IN_DIAL.add(dialing_now.id)
    try:
        with pytest.raises(LeadBusy):
            asyncio.run(call_service.dispatch_call(dialing_now, None))
    finally:
        _IN_DIAL.discard(dialing_now.id)


def test_queue_pauses_instead_of_burning_the_list_when_calls_cannot_be_placed(client, agent_id, monkeypatch):
    import asyncio

    from app.config import Settings
    from app.routers import campaigns as cr
    from app.services.outbound_call import outbound_call_service

    monkeypatch.setattr(Settings, "phone_ready", property(lambda self: True))
    monkeypatch.setattr(cr, "within_calling_hours", lambda c, now: True)
    tried: list[str] = []

    async def broken(lead, db, **kw):
        tried.append(str(lead.id))
        raise RuntimeError("room service unavailable")

    async def no_sleep(_s):
        return None

    monkeypatch.setattr(outbound_call_service, "dispatch_call", broken)
    monkeypatch.setattr(cr.asyncio, "sleep", no_sleep)
    camp = client.post("/api/campaigns/", json={"name": "Outage", "agent_id": agent_id}).json()
    for i in range(6):
        client.post("/api/contacts", json={"name": f"L{i}", "phone": f"+1415555013{i}", "campaign_id": camp["id"]})

    async def run():
        from app.database import AsyncSessionLocal
        from app.models.campaign import Campaign

        async with AsyncSessionLocal() as db:
            c = await db.get(Campaign, uuid.UUID(camp["id"]))
            c.status = "running"
            await db.commit()
        await cr._process_call_queue(camp["id"])

    asyncio.run(run())
    assert len(tried) == 3
    got = client.get(f"/api/campaigns/{camp['id']}").json()
    assert got["status"] == "paused" and got["pause_reason"] == "setup"
    statuses = [l["status"] for l in client.get(f"/api/campaigns/{camp['id']}/leads").json()["leads"]]
    assert statuses.count("new") >= 4


def test_a_greeting_ended_as_a_conversation_still_gets_its_retry(client, agent_id, monkeypatch):
    import asyncio

    from app.database import AsyncSessionLocal
    from app.models.call_log import CallLog
    from app.models.lead import Lead
    from app.services import llm, outbound_call

    camp = client.post("/api/campaigns/", json={"name": "VM", "agent_id": agent_id}).json()
    lead = client.post("/api/contacts", json={"name": "Vm", "phone": "+14155550191", "campaign_id": camp["id"]}).json()
    org_id = uuid.UUID(client.get("/api/auth/me").json()["org"]["id"])
    call_id = uuid.uuid4()
    greeting = [{"role": "assistant", "text": "Hey, is this Sam?"},
                {"role": "user", "text": "Hi, you've reached Sam. I can't take your call, please leave a message."}]

    async def fake_analyze(*a, **k):
        return {"summary": "Reached voicemail.", "outcome": "voicemail", "sentiment": "neutral", "extracted": {}}

    monkeypatch.setattr(llm, "analyze_call", fake_analyze)

    async def run():
        async with AsyncSessionLocal() as db:
            db.add(CallLog(id=call_id, org_id=org_id, agent_id=uuid.UUID(agent_id), lead_id=uuid.UUID(lead["id"]),
                           campaign_id=uuid.UUID(camp["id"]), call_type="outbound", livekit_room_name="r",
                           status="completed", outcome="completed", transcript=greeting, duration_seconds=20))
            row = await db.get(Lead, uuid.UUID(lead["id"]))
            row.status = "completed"
            await db.commit()
        await outbound_call._analyze(str(call_id))
        async with AsyncSessionLocal() as db:
            return (await db.get(Lead, uuid.UUID(lead["id"]))).status

    assert asyncio.run(run()) == "voicemail"
