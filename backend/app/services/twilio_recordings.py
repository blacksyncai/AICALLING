"""
Call recordings through Twilio — no LiveKit egress (which is capped at a few at once and by monthly minutes).

Every call (outbound and inbound) crosses the platform's Twilio Elastic SIP trunk, so the trunk records it
(dual channel: caller and agent on separate sides) independently of LiveKit, which keeps running the AI.
After a call ends, BlackSync finds the matching Twilio call, copies its recording into the private
recordings bucket under the call's account (recordings/<org>/<call>.mp3) and plays it in the call log
through the same short-lived, account-checked links as before.

Each call is handled on its own with retries (a sweeper picks up anything pending), so many calls at
once can't lose recordings, and a restart mid-way just resumes.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx
import structlog
from sqlalchemy import or_, select, update

from app.config import settings
from app.models.call_log import CallLog

log = structlog.get_logger(__name__)

# Trunk recording mode: both legs, starting when the call is answered (no ringing).
TRUNK_MODE = "record-from-answer-dual"
# Wait this long after a call ends before looking (Twilio needs a moment to finish the file).
SETTLE = timedelta(seconds=40)
# Give up after this many tries (the sweeper runs every minute) — about half an hour.
MAX_ATTEMPTS = 30
# How far apart our call record and Twilio's can start and still be the same call.
MATCH_WINDOW = timedelta(minutes=3)

PENDING, READY, NONE, MISSING = "pending", "ready", "none", "missing"


def key_for(org_id: uuid.UUID, call_id: uuid.UUID) -> str:
    return f"recordings/{org_id}/{call_id}.mp3"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


def _twilio_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)  # Twilio uses RFC 2822 dates
    except (TypeError, ValueError):
        return None


# ── Trunk setting ─────────────────────────────────────────────────────────────


async def ensure_trunk_recording() -> str | None:
    """Turn recording on for the Twilio trunk (idempotent). Returns the mode now set, None if unavailable."""
    from app.services import telephony

    if not settings.recording_via_twilio or not settings.twilio_ready:
        return None
    sid = await telephony.trunk_sid()
    url = f"{telephony._TRUNKING}/Trunks/{sid}/Recording"
    current = await telephony._request("GET", url)
    if current.get("mode") == TRUNK_MODE:
        return TRUNK_MODE
    data = await telephony._request("POST", url, data={"Mode": TRUNK_MODE, "Trim": "do-not-trim"})
    log.info("twilio_trunk_recording_enabled", trunk=sid, previous=current.get("mode"), mode=data.get("mode"))
    return data.get("mode")


# ── Per call ─────────────────────────────────────────────────────────────────


def mark_pending(call: CallLog) -> None:
    """At dial / pickup: expect a Twilio recording for this call (shows as "processing" until it lands)."""
    call.recording_key = key_for(call.org_id, call.id)
    call.recording_status = PENDING
    call.recording_attempts = 0


async def find_call_sid(call: CallLog) -> str | None:
    """The Twilio call that carried this call: same numbers, started within a few minutes of ours."""
    from app.services import telephony

    to, frm = (call.to_phone or "").strip(), (call.from_phone or "").strip()
    if not to:
        return None
    ours = _aware(call.answered_at or call.started_at) or _now()
    params = {"To": to, "StartTime>": (ours - timedelta(days=1)).date().isoformat(), "PageSize": 50}
    if frm.startswith("+"):
        params["From"] = frm
    data = await telephony._request("GET", telephony._account_url("Calls.json"), params=params)
    best, best_gap = None, None
    for c in data.get("calls") or []:
        started = _twilio_time(c.get("start_time"))
        if started is None:
            continue
        gap = abs(started - ours)
        if gap <= MATCH_WINDOW and (best_gap is None or gap < best_gap):
            best, best_gap = c, gap
    return best["sid"] if best else None


async def _recording_for(call_sid: str) -> dict | None:
    from app.services import telephony

    data = await telephony._request("GET", telephony._account_url(f"Calls/{call_sid}/Recordings.json"))
    done = [r for r in data.get("recordings") or [] if r.get("status") == "completed"]
    return max(done, key=lambda r: int(r.get("duration") or 0)) if done else None


async def _download(recording_sid: str) -> bytes:
    from app.services import telephony

    async with telephony._client() as client:
        resp = await client.get(telephony._account_url(f"Recordings/{recording_sid}.mp3"), follow_redirects=True,
                                timeout=60.0)
    resp.raise_for_status()
    if not resp.content:
        raise RuntimeError("empty recording")
    return resp.content


def _upload(key: str, body: bytes) -> None:
    from app.services.recordings import _s3

    _s3().put_object(Bucket=settings.recordings_s3_bucket, Key=key, Body=body, ContentType="audio/mpeg")


async def process(db, call: CallLog) -> str:
    """One attempt for one call. Returns the call's recording status afterwards."""
    call.recording_attempts = (call.recording_attempts or 0) + 1
    # Calls that never connected have nothing to record.
    if call.status in ("failed", "no_answer") and not call.duration_seconds:
        call.recording_status, call.recording_key = NONE, None
        await db.commit()
        return NONE
    try:
        if not call.twilio_call_sid:
            call.twilio_call_sid = await find_call_sid(call)
        rec = await _recording_for(call.twilio_call_sid) if call.twilio_call_sid else None
        if rec is not None:
            key = call.recording_key or key_for(call.org_id, call.id)
            body = await _download(rec["sid"])
            await asyncio.to_thread(_upload, key, body)
            call.recording_key, call.recording_status = key, READY
            log.info("twilio_recording_saved", call_id=str(call.id), call_sid=call.twilio_call_sid,
                     recording_sid=rec["sid"], seconds=rec.get("duration"), bytes=len(body))
    except Exception as exc:  # retried on the next sweep
        log.warning("twilio_recording_attempt_failed", call_id=str(call.id), attempt=call.recording_attempts,
                    error=str(exc)[:200])
    if call.recording_status != READY and call.recording_attempts >= MAX_ATTEMPTS:
        call.recording_status, call.recording_key = MISSING, None
        log.warning("twilio_recording_missing", call_id=str(call.id), call_sid=call.twilio_call_sid)
    await db.commit()
    return call.recording_status


async def process_due(db, now: datetime | None = None, limit: int = 25) -> int:
    """Calls whose recording is still pending and that ended a little while ago (or long ago with no end)."""
    now = now or _now()
    rows = (await db.execute(select(CallLog).where(
        CallLog.recording_status == PENDING,
        or_(CallLog.ended_at <= now - SETTLE,
            CallLog.ended_at.is_(None) & (CallLog.started_at <= now - timedelta(hours=2))),
    ).order_by(CallLog.ended_at).limit(limit))).scalars().all()
    done = 0
    for call in rows:
        if await process(db, call) == READY:
            done += 1
    return done


def start_sweeper(interval: float = 60.0):
    """Every minute: make sure trunk recording is on (first run), then save any pending recordings."""
    from app.database import AsyncSessionLocal

    async def _loop() -> None:
        try:
            await ensure_trunk_recording()
        except Exception as exc:
            log.warning("twilio_trunk_recording_setup_failed", error=str(exc)[:200])
        while True:
            try:
                async with AsyncSessionLocal() as db:
                    await process_due(db)
            except Exception as exc:  # never let the loop die
                log.warning("twilio_recording_sweep_failed", error=str(exc)[:200])
            await asyncio.sleep(interval)

    return asyncio.create_task(_loop())
