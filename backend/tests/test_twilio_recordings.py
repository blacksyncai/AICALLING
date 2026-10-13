import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime


def _rfc(d):
    return format_datetime(d.astimezone(timezone.utc), usegmt=True)


def _fake_twilio(monkeypatch, calls_by_to, recordings, uploads, fail_downloads=()):
    from app.services import telephony, twilio_recordings

    async def request(method, url, **kw):
        if url.endswith("/Calls.json"):
            return {"calls": calls_by_to.get(kw["params"]["To"], [])}
        if "/Recordings.json" in url:
            sid = url.split("/Calls/")[1].split("/")[0]
            return {"recordings": recordings.get(sid, [])}
        raise AssertionError(url)

    async def download(rec_sid):
        if rec_sid in fail_downloads:
            raise RuntimeError("boom")
        return f"mp3-{rec_sid}".encode()

    monkeypatch.setattr(telephony, "_request", request)
    monkeypatch.setattr(telephony, "_account_url", lambda p: f"https://api.twilio.test/{p}")
    monkeypatch.setattr(twilio_recordings, "_download", download)
    monkeypatch.setattr(twilio_recordings, "_upload", lambda key, body: uploads.append((key, body)))


def _call(org, to, ended_ago, status="completed", duration=60, frm="+15550001111"):
    from app.models.call_log import CallLog
    from app.services import twilio_recordings

    now = datetime.now(timezone.utc)
    c = CallLog(id=uuid.uuid4(), org_id=org, call_type="outbound", to_phone=to, from_phone=frm,
                livekit_room_name=f"call-{uuid.uuid4()}", status=status, duration_seconds=duration,
                started_at=now - ended_ago - timedelta(seconds=duration + 10),
                answered_at=now - ended_ago - timedelta(seconds=duration), ended_at=now - ended_ago)
    twilio_recordings.mark_pending(c)
    return c


def test_concurrent_calls_get_their_own_recordings(client, monkeypatch):
    from app.database import AsyncSessionLocal
    from app.models.call_log import CallLog
    from app.services import twilio_recordings as tr

    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    a = _call(org_a, "+14155550101", timedelta(minutes=2))
    b = _call(org_b, "+14155550102", timedelta(minutes=2))
    fresh = _call(org_a, "+14155550103", timedelta(seconds=5))  # just ended: not due yet
    lost = _call(org_a, "+14155550104", timedelta(minutes=2))  # nothing at Twilio
    unanswered = _call(org_b, "+14155550105", timedelta(minutes=2), status="no_answer", duration=0)
    ans = a.answered_at
    calls = {
        # Two Twilio calls to the same number: the one that started with ours wins.
        "+14155550101": [{"sid": "CAold", "start_time": _rfc(ans - timedelta(hours=2))},
                         {"sid": "CAa", "start_time": _rfc(ans + timedelta(seconds=2))}],
        "+14155550102": [{"sid": "CAb", "start_time": _rfc(b.answered_at)}],
    }
    recs = {"CAa": [{"sid": "REa", "status": "completed", "duration": "60"}],
            "CAold": [{"sid": "REold", "status": "completed", "duration": "90"}],
            "CAb": [{"sid": "REb", "status": "completed", "duration": "60"}]}
    uploads = []
    _fake_twilio(monkeypatch, calls, recs, uploads)

    async def run():
        async with AsyncSessionLocal() as db:
            db.add_all([a, b, fresh, lost, unanswered])
            await db.commit()
            await tr.process_due(db)
        async with AsyncSessionLocal() as db:
            return {k: await db.get(CallLog, c.id) for k, c in
                    {"a": a, "b": b, "fresh": fresh, "lost": lost, "un": unanswered}.items()}

    got = asyncio.run(run())
    assert sorted(uploads) == sorted([(f"recordings/{org_a}/{a.id}.mp3", b"mp3-REa"),
                                      (f"recordings/{org_b}/{b.id}.mp3", b"mp3-REb")])
    assert got["a"].recording_status == "ready" and got["a"].twilio_call_sid == "CAa"
    assert got["b"].recording_key == f"recordings/{org_b}/{b.id}.mp3"
    assert got["fresh"].recording_status == "pending" and got["fresh"].recording_attempts == 0
    assert got["lost"].recording_status == "pending" and got["lost"].recording_attempts == 1
    assert got["un"].recording_status == "none" and got["un"].recording_key is None


def test_retries_then_gives_up(client, monkeypatch):
    from app.database import AsyncSessionLocal
    from app.services import twilio_recordings as tr

    c = _call(uuid.uuid4(), "+14155550199", timedelta(minutes=5))
    calls = {"+14155550199": [{"sid": "CAx", "start_time": _rfc(c.answered_at)}]}
    recs = {"CAx": [{"sid": "REx", "status": "completed", "duration": "60"}]}
    uploads = []
    _fake_twilio(monkeypatch, calls, recs, uploads, fail_downloads={"REx"})

    async def run():
        async with AsyncSessionLocal() as db:
            db.add(c)
            await db.commit()
            statuses = [await tr.process(db, c) for _ in range(tr.MAX_ATTEMPTS)]
            return statuses, c.recording_key

    statuses, key = asyncio.run(run())
    assert statuses[0] == "pending" and statuses[-1] == "missing" and key is None and not uploads


def test_playback_content_type(monkeypatch):
    from app.services import recordings

    seen = {}

    class S3:
        def generate_presigned_url(self, _op, Params, ExpiresIn):
            seen[Params["Key"]] = Params["ResponseContentType"]
            return "u"

    monkeypatch.setattr(recordings, "_s3", lambda: S3())
    recordings._presign("recordings/o/c.mp3")
    recordings._presign("recordings/o/c.ogg")
    assert seen == {"recordings/o/c.mp3": "audio/mpeg", "recordings/o/c.ogg": "audio/ogg"}
