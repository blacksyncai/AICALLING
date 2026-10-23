"""Per-number health for outbound caller IDs: how often each number gets picked up, how hard it's being
dialed, and which numbers to rest. A number whose pickups fall well below the account's other numbers is
usually being labeled "Spam Likely" — resting it stops it burning leads while it's disputed."""
import statistics
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import case, func, select

from app.models.billing import PhoneNumber
from app.models.call_log import CallLog

log = structlog.get_logger(__name__)

DEFAULT_DAILY_CAP = 75  # calls per number per rolling 24 h in a rotation pool
WINDOW_DAYS = 7
MIN_DIALS = 20  # too few calls to judge a number's pickup rate
LOW_RATIO = 0.5  # flagged when its pickup rate is under half the account's typical number
REST_DAYS = 3
# Not a person on the line.
NOT_PICKED_UP = ("no_answer", "voicemail", "screened", "failed")

# Numbers the campaign dialer can't use for this call (still resting after their last warm-up call).
# Set by the dialer around a dispatch; read by the caller-ID pick in the same task.
pacing_blocked: ContextVar[frozenset] = ContextVar("pacing_blocked", default=frozenset())


class CallersResting(Exception):
    """Every number in the rotation pool is capped, resting or pacing. Try again at `retry_at`."""

    def __init__(self, retry_at: datetime, reason: str):
        super().__init__(reason)
        self.retry_at = retry_at
        self.reason = reason


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


async def stats(db, org_id: uuid.UUID, numbers: list[str] | None = None) -> dict[str, dict]:
    """Per-number outbound stats over the last WINDOW_DAYS, plus dials in the last 24 h."""
    now = _now()
    since, day = now - timedelta(days=WINDOW_DAYS), now - timedelta(hours=24)
    picked = (CallLog.answered_at.is_not(None)) & (func.coalesce(CallLog.outcome, "") .notin_(NOT_PICKED_UP))
    q = (select(CallLog.from_phone,
                func.count(),
                func.sum(case((picked, 1), else_=0)),
                func.sum(case((CallLog.started_at >= day, 1), else_=0)),
                func.avg(case((picked, CallLog.duration_seconds), else_=None)))
         .where(CallLog.org_id == org_id, CallLog.call_type == "outbound", CallLog.from_phone.is_not(None),
                CallLog.started_at >= since)
         .group_by(CallLog.from_phone))
    if numbers is not None:
        q = q.where(CallLog.from_phone.in_(numbers))
    out: dict[str, dict] = {}
    for number, dials, pickups, today, avg_secs in (await db.execute(q)).all():
        dials, pickups = int(dials or 0), int(pickups or 0)
        out[number] = {"dials_7d": dials, "pickups_7d": pickups, "dials_24h": int(today or 0),
                       "pickup_rate": round(pickups / dials, 3) if dials else None,
                       "avg_talk_seconds": int(avg_secs) if avg_secs else 0}
    return out


def low_pickup(per_number: dict[str, dict]) -> set[str]:
    """Numbers picking up far less than the account's typical number (needs two numbers with enough calls)."""
    judged = {n: s["pickup_rate"] for n, s in per_number.items() if s["dials_7d"] >= MIN_DIALS and s["pickup_rate"] is not None}
    if len(judged) < 2:
        return set()
    typical = statistics.median(judged.values())
    if typical <= 0:
        return set()
    return {n for n, rate in judged.items() if rate < typical * LOW_RATIO}


async def pick_caller(db, campaign, org_id: uuid.UUID, pool: list[str], avoid: str | None) -> str:
    """The next number in the campaign's rotation that may dial now: under its daily cap, not resting for
    low pickups, and done with its warm-up rest. Advances the campaign's round-robin cursor."""
    from sqlalchemy import update
    from app.models.campaign import Campaign

    now = _now()
    rows = {p.number: p for p in (await db.execute(select(PhoneNumber).where(
        PhoneNumber.org_id == org_id, PhoneNumber.number.in_(pool), PhoneNumber.status == "active"))).scalars()}
    per = await stats(db, org_id, pool)
    # Rest numbers whose pickups have dropped off (never every number: it's a comparison between them).
    for number in low_pickup(per):
        row = rows.get(number)
        if row is not None and not (_aware(row.rest_until) and _aware(row.rest_until) > now):
            row.rest_until = now + timedelta(days=REST_DAYS)
            row.rest_reason = "low_pickups"
            log.info("number_auto_rested", org_id=str(org_id), number=number,
                     pickup_rate=per[number]["pickup_rate"], dials=per[number]["dials_7d"])
    cap = getattr(campaign, "max_calls_per_number_day", None) or DEFAULT_DAILY_CAP
    blocked = pacing_blocked.get()
    resting = {n for n, r in rows.items() if _aware(r.rest_until) and _aware(r.rest_until) > now}
    capped = {n for n in pool if per.get(n, {}).get("dials_24h", 0) >= cap}
    eligible = [n for n in pool if n not in resting | capped | blocked]
    if not eligible:
        # Everyone is resting: try again when the soonest one frees up (a cap frees within the hour).
        soon = [_aware(rows[n].rest_until) for n in resting if n in rows] + [now + timedelta(minutes=30)] * bool(capped)
        raise CallersResting(min(soon) if soon else now + timedelta(minutes=1),
                             "capped" if capped and not resting else "resting" if resting else "pacing")
    choices = [n for n in eligible if n != avoid] or eligible
    for _ in range(len(pool)):
        cursor = (await db.execute(update(Campaign).where(Campaign.id == campaign.id, Campaign.org_id == org_id)
                                   .values(caller_rotation_cursor=func.coalesce(Campaign.caller_rotation_cursor, 0) + 1)
                                   .returning(Campaign.caller_rotation_cursor))).scalar_one()
        chosen = pool[(cursor - 1) % len(pool)]
        if chosen in choices:
            return chosen
    return choices[0]
