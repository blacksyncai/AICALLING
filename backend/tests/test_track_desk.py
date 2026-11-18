"""Track Desk: check calls for freight brokers."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.database import AsyncSessionLocal
from app.models.account import Organization
from app.models.call_log import CallLog
from app.models.track_desk import CheckCall, FreightLoad, TrackAlert, TrackDeskSettings
from app.services import track_desk as td
from tests.test_phone_numbers import _account

UTC = timezone.utc
NOON = datetime(2026, 11, 19, 18, 0, tzinfo=UTC)  # 12:00 Central

CSV = """load_id,driver_name,driver_phone,pickup_city,pickup_state,pickup_window_start,delivery_city,delivery_state,delivery_window_start,delivery_window_end,shipper_name
L100,Mike Ross,(312) 555-0101,Chicago,IL,2026-11-19 08:00,Dallas,TX,2026-11-20 08:00,2026-11-20 12:00,Acme Foods
L101,Ana Diaz,312-555-0102,Joliet,IL,11/19/2026 9:00 AM,Memphis,TN,11/20/2026 10:00,11/20/2026 14:00,
L102,No Phone,,Chicago,IL,2026-11-19 08:00,Dallas,TX,2026-11-20 08:00,,
L103,Bad Phone,12345,Chicago,IL,2026-11-19 08:00,Dallas,TX,2026-11-20 08:00,,
L100,Dup Row,312-555-0109,Chicago,IL,2026-11-19 08:00,Dallas,TX,2026-11-20 08:00,,
L104,Backwards,312-555-0104,Chicago,IL,2026-11-21 08:00,Dallas,TX,2026-11-20 08:00,,
L105,Bad Time,312-555-0105,Chicago,IL,someday,Dallas,TX,2026-11-20 08:00,,
"""


def _cfg(**kw):
    base = dict(check_interval_hours=3, quiet_start_hour=22, quiet_end_hour=6, call_late_loads_in_quiet_hours=False,
                sms_only=False, time_zone="America/Chicago", plan="pilot", paused=False, broker_name="Lone Star Freight",
                agent_name="Alex", caller_number="", alert_emails=[], alert_phone="", agent_id=None)
    base.update(kw)
    return TrackDeskSettings(**base)


def _load(**kw):
    base = dict(org_id=uuid.uuid4(), external_id="L1", driver_name="Mike Ross", driver_phone="+13125550101",
                pickup_city="Chicago", pickup_state="IL", pickup_start=datetime(2026, 11, 19, 14, 0, tzinfo=UTC),
                delivery_city="Dallas", delivery_state="TX", delivery_start=datetime(2026, 11, 20, 14, 0, tzinfo=UTC),
                delivery_end=datetime(2026, 11, 20, 18, 0, tzinfo=UTC), status="active", milestones=[], loaded="unknown",
                sms_only=False, do_not_call=False, unresponsive=False, delay_reason="", last_location="",
                last_eta_text="", round_state=None)
    base.update(kw)
    return FreightLoad(**base)


# ── Import ────────────────────────────────────────────────────────────────────

def test_csv_import_validates_every_row_with_a_reason():
    report = td.parse_loads_csv(CSV, "America/Chicago")
    assert [r["external_id"] for r in report.rows] == ["L100", "L101"]
    assert report.rows[0]["driver_phone"] == "+13125550101"
    assert report.rows[0]["pickup_start"] == datetime(2026, 11, 19, 14, 0, tzinfo=UTC)  # 08:00 Central
    assert report.rows[1]["delivery_end"] == datetime(2026, 11, 20, 20, 0, tzinfo=UTC)
    reasons = {e["load_id"]: e["reason"] for e in report.errors}
    assert reasons["L102"] == "missing driver_phone"
    assert "isn't a valid number" in reasons["L103"]
    assert reasons["L100"] == "duplicate load_id in this file"
    assert reasons["L104"] == "delivery is before pickup"
    assert "couldn't read the time 'someday'" in reasons["L105"]


def test_column_names_are_matched_loosely_and_windows_can_share_a_cell():
    text = ("Load #,Driver,Cell,Origin City,Origin State,Pickup,Destination City,Destination State,Delivery\n"
            "77,Sam,4155550100,Fresno,CA,11/19/2026 8:00-12:00,Reno,NV,11/20/2026 9:00 AM - 1:00 PM\n")
    report = td.parse_loads_csv(text, "America/Los_Angeles")
    assert not report.errors, report.errors
    row = report.rows[0]
    assert row["external_id"] == "77" and row["driver_phone"] == "+14155550100"
    assert row["pickup_end"] - row["pickup_start"] == timedelta(hours=4)
    assert row["delivery_end"] - row["delivery_start"] == timedelta(hours=4)


# ── Schedule ──────────────────────────────────────────────────────────────────

def test_check_schedule_pickup_en_route_pre_delivery_delivery_then_stop():
    cfg, load = _cfg(), _load()
    when, kind = td.plan_next_check(load, cfg, NOON - timedelta(hours=6))
    assert (when, kind) == (load.pickup_start + timedelta(minutes=30), "pickup")

    load.milestones, load.last_check_at = ["pickup"], NOON
    assert td.plan_next_check(load, cfg, NOON, base=NOON) == (NOON + timedelta(hours=3), "en_route")

    late_evening = load.delivery_start - timedelta(hours=4)
    load.last_check_at = late_evening
    assert td.plan_next_check(load, cfg, late_evening, base=late_evening) == (
        load.delivery_start - timedelta(hours=2), "pre_delivery")

    load.milestones = ["pickup", "pre_delivery"]
    at = load.delivery_end - timedelta(minutes=10)
    assert td.plan_next_check(load, cfg, at, base=at) == (load.delivery_end + timedelta(minutes=30), "delivery")

    load.status = "delivered"
    assert td.plan_next_check(load, cfg, at) == (None, "")


def test_interval_is_clamped_to_two_to_four_hours():
    load = _load(milestones=["pickup"], last_check_at=NOON)
    assert td.plan_next_check(load, _cfg(check_interval_hours=1), NOON, base=NOON)[0] == NOON + timedelta(hours=2)
    assert td.plan_next_check(load, _cfg(check_interval_hours=9), NOON, base=NOON)[0] == NOON + timedelta(hours=4)


def test_quiet_hours_use_the_drivers_state_not_the_brokers():
    cfg = _cfg(time_zone="America/New_York")
    load = _load(pickup_state="CA", milestones=[])  # at pickup in California
    four_am_pacific = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)  # 7:00 Eastern
    assert td.in_quiet_hours(load, cfg, four_am_pacific) and not td.may_call(load, cfg, four_am_pacific)
    assert td.quiet_hours_end(load, cfg, four_am_pacific) == datetime(2026, 11, 19, 14, 0, tzinfo=UTC)
    load.status = "late"
    assert td.may_call(load, _cfg(call_late_loads_in_quiet_hours=True), four_am_pacific)
    assert not td.may_call(_load(sms_only=True), cfg, NOON)


# ── Scoring ───────────────────────────────────────────────────────────────────

def test_scoring_on_time_at_risk_late_unresponsive():
    end = datetime(2026, 11, 20, 18, 0, tzinfo=UTC)
    now = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    assert td.score(_load(), now) == "active"  # no check-in yet
    checked = dict(last_check_at=now)
    assert td.score(_load(**checked, last_eta=end - timedelta(hours=1)), now) == "active"
    assert td.score(_load(**checked, last_eta=end + timedelta(hours=1)), now) == "at_risk"
    assert td.score(_load(**checked, last_eta=end + timedelta(hours=3)), now) == "late"
    assert td.score(_load(**checked), now) == "at_risk"  # checked in, no ETA
    assert td.score(_load(**checked, delay_reason="broke down outside Tulsa"), now) == "late"
    assert td.score(_load(**checked, last_eta=end + timedelta(hours=1), delay_reason="detention at shipper"), now) == "late"
    assert td.score(_load(**checked, last_eta=end - timedelta(hours=2)), end + timedelta(hours=1)) == "late"  # window passed
    assert td.score(_load(**checked, unresponsive=True), now) == "unresponsive"
    assert td.score(_load(status="delivered"), now) == "delivered"


def test_reading_answers_handles_bad_eta_and_stop():
    now = NOON
    info = td._to_checkin({"location": "I-44 near Tulsa", "loaded": "Yes", "eta": "2026-11-20T09:30:00-06:00",
                           "confidence": "high"}, now)
    assert info.location == "I-44 near Tulsa" and info.loaded == "yes"
    assert info.eta == datetime(2026, 11, 20, 15, 30, tzinfo=UTC) and info.useful
    assert td._to_checkin({"eta": "2031-01-01T00:00:00Z"}, now).eta is None  # nonsense ETA is dropped
    assert td._to_checkin({"eta": "soon"}, now).eta is None
    stop = asyncio.run(td.read_checkin(_load(), _cfg(), "STOP", now, "sms"))
    assert stop.stop and not stop.useful


# ── Rounds against the database ───────────────────────────────────────────────

@pytest.fixture
def broker(client, make_client):
    org, owner = _account(client, make_client, f"Freight {uuid.uuid4().hex[:6]}")
    return uuid.UUID(org["id"]), owner


@pytest.fixture
def wire(monkeypatch):
    """Fake dialing, texting and the answer reader; record what happened."""
    sent, dialed, answers = [], [], {}

    async def fake_call(db, org, cfg, load, kind):
        call = CallLog(id=uuid.uuid4(), org_id=org.id, call_type="outbound", to_phone=load.driver_phone,
                       livekit_room_name=f"td-{uuid.uuid4().hex[:8]}", status="initiated", started_at=td_now[0])
        db.add(call)
        await db.flush()
        dialed.append((load.external_id, kind))
        return call

    async def fake_text(db, org_id, to, body):
        sent.append((to, body))
        return True

    async def fake_json(prompt):
        for key, value in answers.items():
            if key in prompt:
                return value
        return {"confidence": "low"}

    td_now = [NOON]
    monkeypatch.setattr(td, "_place_call", fake_call)
    monkeypatch.setattr(td, "send_text", fake_text)
    import app.services.llm as llm
    monkeypatch.setattr(llm, "_analysis_json", fake_json)
    return {"sent": sent, "dialed": dialed, "answers": answers, "now": td_now}


def _run(coro):
    return asyncio.run(coro)


async def _new_load(org_id, **kw):
    async with AsyncSessionLocal() as db:
        org = await db.get(Organization, org_id)
        cfg = await td.get_settings(db, org)
        load = _load(org_id=org_id, external_id=kw.pop("external_id", f"L{uuid.uuid4().hex[:5]}"), **kw)
        load.next_check_at, load.next_check_kind = td.plan_next_check(load, cfg, NOON - timedelta(hours=6))
        db.add(load)
        await db.commit()
        return load.id


async def _advance(load_id, now):
    async with AsyncSessionLocal() as db:
        load = await db.get(FreightLoad, load_id)
        org = await db.get(Organization, load.org_id)
        cfg = await td.get_settings(db, org)
        await td.advance(db, org, cfg, load, now)
        await db.commit()


async def _end_call(load_id, transcript, outcome="completed"):
    async with AsyncSessionLocal() as db:
        load = await db.get(FreightLoad, load_id)
        check = await db.get(CheckCall, uuid.UUID(load.round_state["check_id"]))
        call = await db.get(CallLog, check.call_log_id)
        call.ended_at, call.transcript, call.outcome, call.duration_seconds = NOON, transcript, outcome, 40
        call.status = "no_answer" if outcome in ("voicemail", "no_answer") else "completed"
        await db.commit()


async def _get(load_id):
    async with AsyncSessionLocal() as db:
        load = await db.get(FreightLoad, load_id)
        checks = (await db.execute(td.select(CheckCall).where(CheckCall.load_id == load_id)
                                   .order_by(CheckCall.attempted_at))).scalars().all()
        alerts = (await db.execute(td.select(TrackAlert).where(TrackAlert.load_id == load_id))).scalars().all()
        return load, checks, alerts


def test_answered_check_call_logs_location_eta_and_plans_the_next(broker, wire):
    org_id, _ = broker
    load_id = _run(_new_load(org_id, external_id="A1"))
    pickup_check = datetime(2026, 11, 19, 14, 30, tzinfo=UTC)
    _run(_advance(load_id, pickup_check))
    assert wire["dialed"] == [("A1", "pickup")]
    assert "automated assistant" in wire["sent"][0][1]  # first-load welcome text with opt-out
    wire["answers"]["Load A1"] = {"location": "I-55 south of Springfield", "loaded": "yes",
                                  "eta": "2026-11-20T09:00:00-06:00", "eta_text": "tomorrow 9am", "confidence": "high"}
    _run(_end_call(load_id, [{"role": "assistant", "text": "Where are you right now?"},
                             {"role": "user", "text": "I-55 south of Springfield, loaded, there by 9 tomorrow."}]))
    _run(_advance(load_id, pickup_check + timedelta(minutes=2)))
    load, checks, alerts = _run(_get(load_id))
    assert load.status == "active" and load.loaded == "yes" and load.last_location == "I-55 south of Springfield"
    assert td._aware(load.last_eta) == datetime(2026, 11, 20, 15, 0, tzinfo=UTC)
    assert load.round_state is None and load.next_check_kind == "en_route"
    assert td._aware(load.next_check_at) == pickup_check + timedelta(minutes=2) + timedelta(hours=3)
    assert [c.outcome for c in checks if c.kind != "welcome"] == ["answered"] and not alerts


def test_missed_call_texts_then_retries_then_flags_unresponsive(broker, wire):
    org_id, _ = broker
    load_id = _run(_new_load(org_id, external_id="B1", milestones=["pickup"], last_check_at=NOON - timedelta(hours=3),
                             last_eta=datetime(2026, 11, 20, 16, 0, tzinfo=UTC)))
    _run(_advance(load_id, NOON))
    assert wire["dialed"][-1] == ("B1", "en_route")
    _run(_end_call(load_id, [{"role": "assistant", "text": "Hi Mike..."}], outcome="voicemail"))
    _run(_advance(load_id, NOON + timedelta(minutes=1)))
    load, checks, _ = _run(_get(load_id))
    assert load.round_state["phase"] == "sms_pending" and checks[-1].outcome == "voicemail"

    texts = len(wire["sent"])
    _run(_advance(load_id, NOON + timedelta(minutes=10)))
    assert len(wire["sent"]) == texts  # waits 15 minutes before texting
    _run(_advance(load_id, NOON + timedelta(minutes=17)))
    assert "1) Where are you now?" in wire["sent"][-1][1] and "B1" in wire["sent"][-1][1]
    _run(_advance(load_id, NOON + timedelta(minutes=17 + 46)))  # no reply in 45 min: call once more
    assert wire["dialed"][-1] == ("B1", "en_route") and len(wire["dialed"]) == 2
    _run(_end_call(load_id, [], outcome="no_answer"))
    _run(_advance(load_id, NOON + timedelta(minutes=70)))
    load, checks, alerts = _run(_get(load_id))
    assert load.status == "unresponsive" and load.round_state is None
    assert [a.kind for a in alerts] == ["unresponsive"]
    assert td._aware(load.next_check_at) == NOON + timedelta(minutes=70) + timedelta(hours=3)  # keeps trying, not now


def test_a_text_reply_is_the_check_in_and_no_second_call_that_round(broker, wire):
    org_id, _ = broker
    load_id = _run(_new_load(org_id, external_id="C1", milestones=["pickup"], last_check_at=NOON - timedelta(hours=3),
                             last_eta=datetime(2026, 11, 20, 16, 0, tzinfo=UTC)))
    _run(_advance(load_id, NOON))
    _run(_end_call(load_id, [], outcome="no_answer"))
    _run(_advance(load_id, NOON + timedelta(minutes=1)))
    _run(_advance(load_id, NOON + timedelta(minutes=16)))  # texted
    wire["answers"]["Load C1"] = {"location": "Tulsa OK", "loaded": "yes", "eta": "2026-11-20T15:30:00-06:00",
                                  "delay_reason": "", "confidence": "high"}

    async def reply():
        async with AsyncSessionLocal() as db:
            cfg = (await db.execute(td.select(TrackDeskSettings).where(TrackDeskSettings.org_id == org_id))).scalar_one()
            await td.on_text_reply(db, cfg, "(312) 555-0101", "tulsa ok, loaded, eta 330 tomorrow", NOON + timedelta(minutes=30))
            await db.commit()
    _run(reply())
    _run(_advance(load_id, NOON + timedelta(minutes=90)))
    load, checks, alerts = _run(_get(load_id))
    assert len(wire["dialed"]) == 1  # no retry call
    assert checks[-1].outcome == "sms_reply" and checks[-1].location_text == "Tulsa OK"
    # ETA 15:30 Central = 21:30 UTC, after the 18:00 UTC window by 3.5 h: late, broker alerted.
    assert load.status == "late" and [a.kind for a in alerts] == ["late"]
    assert "Tulsa OK" in alerts[0].message


def test_stop_by_text_or_on_a_call_stops_all_contact_and_alerts(broker, wire):
    org_id, _ = broker
    load_id = _run(_new_load(org_id, external_id="D1", driver_phone="+13125550177"))

    async def reply(text):
        async with AsyncSessionLocal() as db:
            cfg = (await db.execute(td.select(TrackDeskSettings).where(TrackDeskSettings.org_id == org_id))).scalar_one()
            await td.on_text_reply(db, cfg, "+13125550177", text, NOON)
            await db.commit()
    _run(reply("STOP"))
    load, _, alerts = _run(_get(load_id))
    assert load.do_not_call and load.next_check_at is None and [a.kind for a in alerts] == ["dnc"]
    dialed = len(wire["dialed"])
    _run(_advance(load_id, NOON + timedelta(days=1)))
    assert len(wire["dialed"]) == dialed

    load2 = _run(_new_load(org_id, external_id="D2", driver_phone="+13125550178"))
    _run(_advance(load2, datetime(2026, 11, 19, 14, 30, tzinfo=UTC)))
    _run(_end_call(load2, [{"role": "assistant", "text": "Where are you?"},
                           {"role": "user", "text": "Stop calling me, I already told dispatch."}]))
    _run(_advance(load2, datetime(2026, 11, 19, 14, 32, tzinfo=UTC)))
    load, _, alerts = _run(_get(load2))
    assert load.do_not_call and "dnc" in [a.kind for a in alerts]


def test_quiet_hours_text_instead_of_call(broker, wire):
    org_id, _ = broker
    load_id = _run(_new_load(org_id, external_id="E1", milestones=["pickup"], loaded="yes",
                             last_check_at=NOON - timedelta(hours=6)))
    two_am_central = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)
    _run(_advance(load_id, two_am_central))
    load, checks, _ = _run(_get(load_id))
    assert not [d for d in wire["dialed"] if d[0] == "E1"]
    assert checks[-1].channel == "sms" and load.round_state["phase"] == "sms_wait"
    assert datetime.fromisoformat(load.round_state["until"]) == datetime(2026, 11, 20, 12, 0, tzinfo=UTC)  # 6 AM


# ── API ───────────────────────────────────────────────────────────────────────

def test_import_board_detail_and_broker_isolation(client, make_client):
    _, owner = _account(client, make_client, "Board Freight")
    _, other = _account(client, make_client, "Other Freight")
    files = {"file": ("loads.csv", CSV, "text/csv")}
    preview = owner.post("/api/track-desk/loads/import", files=files, data={"dry_run": "true"}).json()
    assert preview["dry_run"] and preview["valid"] == 2 and len(preview["errors"]) == 5
    res = owner.post("/api/track-desk/loads/import", files={"file": ("loads.csv", CSV, "text/csv")})
    assert res.status_code == 200, res.text
    assert res.json()["imported"] == 2 and res.json()["skipped"] == 5
    again = owner.post("/api/track-desk/loads/import", files={"file": ("loads.csv", CSV, "text/csv")}).json()
    assert again["imported"] == 0 and again["updated"] == 2  # deduped by load_id

    board = owner.get("/api/track-desk/loads").json()
    assert {l["load_id"] for l in board["items"]} == {"L100", "L101"}
    lid = next(l["id"] for l in board["items"] if l["load_id"] == "L100")
    assert other.get("/api/track-desk/loads").json()["items"] == []
    assert other.get(f"/api/track-desk/loads/{lid}").status_code == 404
    assert other.post(f"/api/track-desk/loads/{lid}/mark-delivered").status_code == 404

    r = owner.post(f"/api/track-desk/loads/{lid}/manual-check-in",
                   json={"location_text": "Springfield, MO", "loaded": "yes", "eta": "2026-11-20T09:00:00-06:00"})
    assert r.status_code == 200 and r.json()["last_location"] == "Springfield, MO"
    detail = owner.get(f"/api/track-desk/loads/{lid}").json()
    assert detail["timeline"][0]["channel"] == "manual" and detail["timeline"][0]["location"] == "Springfield, MO"
    assert owner.post(f"/api/track-desk/loads/{lid}/mark-delivered").json()["status"] == "delivered"
    assert owner.get(f"/api/track-desk/loads?status=delivered").json()["items"][0]["next_check_at"] is None

    stats = owner.get("/api/track-desk/stats?week=2026-11-19").json()
    assert stats["check_ins"] >= 0 and "answer_rate" in stats

    s = owner.get("/api/track-desk/settings").json()
    assert s["sms_webhook_url"].startswith("http") and s["agent_id"]
    assert owner.patch("/api/track-desk/settings", json={"check_interval_hours": 4, "alert_emails": ["ops@lsf.com"]}
                       ).json()["check_interval_hours"] == 4


def test_sms_webhook_needs_the_accounts_token(client, make_client):
    _, owner = _account(client, make_client, "Webhook Freight")
    url = owner.get("/api/track-desk/settings").json()["sms_webhook_url"]
    path = url[url.index("/api/"):]
    assert client.post("/api/track-desk/sms/not-a-real-token-xyz", data={"From": "+1", "Body": "x"}).status_code == 404
    r = make_client().post(path, data={"From": "+13125550199", "Body": "in Tulsa"})  # unknown driver: ignored
    assert r.status_code == 200 and "<Response>" in r.text


def test_worker_tick_picks_up_due_loads_only(broker, wire):
    org_id, _ = broker
    due = _run(_new_load(org_id, external_id="T1", milestones=["pickup"], last_check_at=NOON - timedelta(hours=4),
                         last_eta=datetime(2026, 11, 20, 16, 0, tzinfo=UTC)))
    later = _run(_new_load(org_id, external_id="T2", pickup_start=NOON + timedelta(hours=5)))

    async def fix_next():
        async with AsyncSessionLocal() as db:
            load = await db.get(FreightLoad, due)
            load.next_check_at = NOON - timedelta(minutes=1)
            await db.commit()
    _run(fix_next())
    before = len(wire["dialed"])
    _run(td.tick(NOON))
    names = [d[0] for d in wire["dialed"][before:]]
    assert "T1" in names and "T2" not in names
