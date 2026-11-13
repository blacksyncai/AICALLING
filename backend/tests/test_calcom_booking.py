"""Cal.com booking end to end with mocked Cal.com responses: nothing here reaches Cal.com or books a real time."""

import asyncio
import json
import uuid
from types import SimpleNamespace as NS

import httpx
import pytest

from app.services import calendar
from tests.test_voice_audit import context, tools

KEY, ETYPE, TZ = "cal_live_test", "4242", "America/New_York"
CFG = {"enable_booking": True, "calcom_api_key": KEY, "calcom_event_type_id": ETYPE, "calendar_timezone": TZ}
# What Cal.com's v2 slots endpoint returns for that calendar zone (offsets, not UTC).
MONDAY = ["2030-01-07T09:00:00.000-05:00", "2030-01-07T12:30:00.000-05:00", "2030-01-07T16:30:00.000-05:00"]
TUESDAY = ["2030-01-08T10:00:00.000-05:00", "2030-01-08T14:00:00.000-05:00"]


class FakeCal:
    """Cal.com v2 as far as BlackSync uses it. `booking` decides how POST /v2/bookings answers."""

    def __init__(self, booking=None, days=None):
        self.days = days if days is not None else {"2030-01-07": MONDAY, "2030-01-08": TUESDAY}
        self.booking = booking or (lambda body: httpx.Response(201, json={"status": "success", "data": {
            "uid": "bk_123", "start": body["start"], "status": "accepted"}}))
        self.posts: list[dict] = []
        self.keys: set[str] = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.keys.add(request.headers.get("authorization", ""))
        if request.method == "GET" and request.url.path == "/v2/slots":
            start = request.url.params["start"]
            data = {d: [{"start": x} for x in xs] for d, xs in self.days.items() if d >= start}
            return httpx.Response(200, json={"status": "success", "data": data})
        if request.method == "POST" and request.url.path == "/v2/bookings":
            body = json.loads(request.content)
            self.posts.append(body)
            return self.booking(body)
        return httpx.Response(404, json={"error": {"message": "not mocked"}})


@pytest.fixture
def cal(monkeypatch):
    fake = FakeCal()
    real = httpx.AsyncClient

    def client(*a, **kw):
        kw.pop("transport", None)
        return real(*a, transport=httpx.MockTransport(fake.handler), **kw)

    monkeypatch.setattr(calendar.httpx, "AsyncClient", client)
    return fake


def _contact(run, *lines):
    for line in lines:
        run.transcript.append({"role": "user", "text": line})


@pytest.mark.asyncio
async def test_availability_then_booking_creates_a_real_cal_booking(cal):
    run, ts = tools(CFG, {"full_name": "Jamie Seller", "phone": "+14155550123"})
    offer = await ts["check_availability"](context(), preferred_date="2030-01-07")
    assert "Monday" in offer and len(run.slots) == 3
    _contact(run, "Let's do four thirty.", "hamza at blacksync dot ai")
    out = await ts["book_appointment"]("Monday at 4:30", "hamza@blacksync.ai", context())
    assert out.startswith("Booked for") and run.meeting_link == "https://cal.com/booking/bk_123"
    body = cal.posts[-1]
    # The request Cal.com needs: UTC start, the event type as a number, the attendee with email, zone and phone.
    assert body["start"] == "2030-01-07T21:30:00Z" and body["eventTypeId"] == 4242
    assert body["attendee"] == {"name": "Jamie Seller", "email": "hamza@blacksync.ai", "timeZone": TZ,
                                "language": "en", "phoneNumber": "+14155550123"}
    assert cal.keys == {f"Bearer {KEY}"}
    rec = run.transcript[-1]
    assert rec["tool"] == "book_appointment" and rec["result"]["success"] and rec["result"]["output"]["link"]


@pytest.mark.asyncio
async def test_asking_for_other_times_on_a_full_day_offers_the_next_openings(cal):
    run, ts = tools(CFG)
    await ts["check_availability"](context(), preferred_date="2030-01-07")
    out = await ts["check_availability"](context(), preferred_date="2030-01-07")  # "any other times?"
    assert "Nothing else open on the day they asked for" in out and "Tuesday" in out
    assert len(run.slots) == 5  # Monday's three plus Tuesday's openings, all bookable


@pytest.mark.asyncio
async def test_slot_taken_is_not_booked_and_the_agent_rechecks(cal):
    cal.booking = lambda body: httpx.Response(400, json={"status": "error", "error": {
        "code": "BadRequestException", "message": "User either already has booking at this time or is not available"}})
    run, ts = tools(CFG)
    await ts["check_availability"](context(), preferred_date="2030-01-07")
    _contact(run, "Nine works.", "a@b.co")
    out = await ts["book_appointment"]("Monday at 9:00", "a@b.co", context())
    assert out.startswith("Not booked: that time was just taken") and "check_availability" in out
    assert not run.meeting_time and len(run.slots) == 2  # the taken time isn't offered again
    rec = run.transcript[-1]
    assert rec["result"]["success"] is False and "already has booking" in rec["result"]["output"]["error"]


@pytest.mark.asyncio
async def test_calendar_rejection_keeps_its_reason_and_claims_nothing(cal):
    cal.booking = lambda body: httpx.Response(400, json={"status": "error", "error": {
        "code": "BadRequestException", "message": "Missing required booking field: attendeePhoneNumber"}})
    run, ts = tools(CFG)
    await ts["check_availability"](context(), preferred_date="2030-01-07")
    _contact(run, "Nine.", "a@b.co")
    out = await ts["book_appointment"]("Monday at 9:00", "a@b.co", context())
    assert out.startswith("Not booked: the calendar didn't accept") and "Do not say it's booked" in out
    assert not run.meeting_time
    assert "attendeePhoneNumber" in run.transcript[-1]["result"]["output"]["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [
    lambda body: httpx.Response(500, json={"error": {"message": "boom"}}),
    lambda body: httpx.Response(201, json={"status": "success", "data": {}}),  # no booking id: no receipt
])
async def test_server_errors_and_missing_receipts_are_never_success(cal, answer):
    cal.booking = answer
    run, ts = tools(CFG)
    await ts["check_availability"](context(), preferred_date="2030-01-07")
    _contact(run, "Nine.", "a@b.co")
    out = await ts["book_appointment"]("Monday at 9:00", "a@b.co", context())
    assert "not confirmed" in out and not run.meeting_time and not run.meeting_link


@pytest.mark.asyncio
async def test_timeout_is_uncertain_and_not_retried(cal, monkeypatch):
    def slow(body):
        raise httpx.ReadTimeout("timed out")
    cal.booking = slow
    run, ts = tools(CFG)
    await ts["check_availability"](context(), preferred_date="2030-01-07")
    _contact(run, "Nine.", "a@b.co")
    for _ in range(2):
        assert "not confirmed" in await ts["book_appointment"]("Monday at 9:00", "a@b.co", context())
    assert len(cal.posts) == 1 and not run.meeting_time


@pytest.mark.asyncio
async def test_missing_details_never_reach_cal(cal):
    run, ts = tools(CFG)
    # No times offered yet.
    assert "check_availability first" in await ts["book_appointment"]("Monday at 9:00", "a@b.co", context())
    await ts["check_availability"](context(), preferred_date="2030-01-07")
    # An email the contact never said.
    assert "hasn't given that email" in await ts["book_appointment"]("Monday at 9:00", "guess@b.co", context())
    # A time that wasn't offered.
    _contact(run, "a@b.co")
    assert (await ts["book_appointment"]("Friday at 7", "a@b.co", context())).startswith("Which slot?")
    assert cal.posts == []


@pytest.mark.asyncio
async def test_bad_event_type_id_is_a_clear_rejection(cal):
    with pytest.raises(calendar.BookingRejected):
        await calendar.create_booking("2030-01-07T14:00:00Z", "a@b.co", "", "not-a-number", KEY, TZ)


@pytest.mark.asyncio
async def test_second_booking_on_the_same_call_is_refused(cal):
    run, ts = tools(CFG)
    await ts["check_availability"](context(), preferred_date="2030-01-07")
    _contact(run, "Nine.", "a@b.co")
    assert (await ts["book_appointment"]("Monday at 9:00", "a@b.co", context())).startswith("Booked")
    assert "Already booked" in await ts["book_appointment"]("Monday at 12:30", "a@b.co", context())
    assert len(cal.posts) == 1


# ── What counts as a booked meeting ─────────────────────────────────────────

def _tool(name, success=True, output=None):
    return {"role": "tool", "tool": name, "args": {}, "result": {"output": output, "success": success}}


def test_only_a_calendar_receipt_counts_as_booked():
    from app.agent.runtime import booking_state, reconcile_outcome

    agreed = [{"role": "assistant", "text": "I've got 4:30."}, {"role": "user", "text": "Let's do four thirty."}]
    offered = agreed + [_tool("check_availability", output={"slots": ["Mon 4:30 PM"]})]
    failed = offered + [_tool("book_appointment", False, {"error": "confirmation unavailable"})]
    booked = offered + [_tool("book_appointment", True, {"booked": "Mon 4:30 PM", "link": "https://cal.com/booking/x"})]
    assert booking_state(agreed) is None and booking_state(offered) == "tentative"
    assert booking_state(failed) == "failed" and booking_state(booked) == "confirmed"
    assert reconcile_outcome("meeting_booked", failed) == "interested"
    assert reconcile_outcome("meeting_booked", offered) == "interested"
    assert reconcile_outcome("meeting_booked", booked) == "meeting_booked"
    assert reconcile_outcome("meeting_booked", agreed) == "meeting_booked"  # no calendar on this call


def test_analysis_never_stores_an_unconfirmed_booking(client, agent_id, monkeypatch):
    """The three William Raveis test calls: the agent offered real times, the booking failed, and the analysis
    still scored "meeting_booked". Stored now as interested, with the booking status and a human follow-up."""
    from datetime import datetime, timezone

    from app.database import AsyncSessionLocal
    from app.models.agent import Agent
    from app.models.call_log import CallLog
    from app.services import llm, outbound_call

    async def fake_analyze(*a, **kw):
        return {"summary": "Agreed to 4:30 and gave an email.", "sentiment": "positive", "extracted": {},
                "outcome": "meeting_booked", "successful": True,
                "response_analysis": {"next_action": "meeting_booked", "meeting_response": "accepted"}}
    monkeypatch.setattr(llm, "analyze_call", fake_analyze)
    org_id = uuid.UUID(client.get("/api/auth/me").json()["org"]["id"])
    transcript = [{"role": "user", "text": "Let's do four thirty."},
                  _tool("check_availability", output={"slots": ["Mon 4:30 PM"]}),
                  {"role": "user", "text": "hamza at blacksync dot ai"},
                  _tool("book_appointment", False, {"error": "confirmation unavailable"})]

    async def run():
        async with AsyncSessionLocal() as db:
            agent = await db.get(Agent, uuid.UUID(agent_id))
            agent.enable_booking, agent.calcom_event_type_id, agent.calcom_api_key_enc = True, "4242", "enc"
            ids = []
            for link in (None, "https://cal.com/booking/bk_9"):
                t = transcript if not link else transcript[:-1] + [_tool("book_appointment", True, {"booked": "Mon 4:30 PM", "link": link})]
                c = CallLog(id=uuid.uuid4(), org_id=org_id, agent_id=agent.id, call_type="web", status="completed",
                            outcome="meeting_booked", transcript=t, meeting_link=link,
                            livekit_room_name=f"web-{uuid.uuid4().hex[:8]}", started_at=datetime.now(timezone.utc),
                            response_analysis={"_review_schema": 1})
                db.add(c)
                ids.append(c.id)
            await db.commit()
        for cid in ids:
            await outbound_call._analyze(str(cid))
        async with AsyncSessionLocal() as db:
            failed, ok = [await db.get(CallLog, i) for i in ids]
            assert failed.outcome == "interested" and failed.extracted_data["_booking_status"] == "failed"
            assert failed.response_analysis["next_action"] == "human_review"
            assert ok.outcome == "meeting_booked" and ok.extracted_data["_booking_status"] == "confirmed"

        return ids

    failed_id, ok_id = asyncio.run(run())
    listed = {m["call_id"] for m in client.get("/api/meetings").json()["items"]}
    assert str(ok_id) in listed and str(failed_id) not in listed  # only the confirmed one is a meeting  # only the confirmed one is a meeting
