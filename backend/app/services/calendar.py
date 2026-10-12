"""
Cal.com slot lookup + booking, shared by the API playground and the voice worker.
Falls back to realistic mock slots when Cal.com isn't configured, so booking
flows can be tested end-to-end without an account.
"""

from __future__ import annotations

import datetime as dt

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import structlog

from app.config import settings

log = structlog.get_logger(__name__)

def _event_type(event_type_id: str | None) -> str:
    return (event_type_id or settings.calcom_event_type_id or "").strip()


def _key(api_key: str | None) -> str:
    """The agent's own Cal.com key, else the server-wide one."""
    return (api_key or settings.calcom_api_key or "").strip()


def _zone(tz: str | None) -> ZoneInfo:
    try:
        return ZoneInfo((tz or "").strip() or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def valid_timezone(tz: str) -> bool:
    try:
        ZoneInfo(tz)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def _label(start_iso: str, tz: str | None = None) -> str:
    try:
        d = dt.datetime.fromisoformat(start_iso.replace("Z", "+00:00")).astimezone(_zone(tz))
        name = d.tzname() or "UTC"
        return d.strftime(f"%A, %B %-d at %-I:%M %p {name}")
    except Exception:
        return start_iso


def mock_slots(preferred_date: str = "", tz: str | None = None) -> list[dict]:
    """Two stable slots (3 PM and 6 PM UTC) on the requested day, or the next weekday."""
    today = dt.datetime.now(dt.timezone.utc).date()
    day = today + dt.timedelta(days=1)
    try:
        if preferred_date:
            d = dt.date.fromisoformat(preferred_date.strip()[:10])
            if d > today:
                day = d
    except ValueError:
        pass
    while day.weekday() >= 5:
        day += dt.timedelta(days=1)
    out = []
    for hour in (15, 18):
        start = dt.datetime.combine(day, dt.time(hour), tzinfo=dt.timezone.utc).isoformat()
        out.append({"start": start, "label": _label(start, tz)})
    return out


async def fetch_slots(preferred_date: str = "", event_type_id: str | None = None,
                      api_key: str | None = None, tz: str | None = None) -> list[dict]:
    """Return up to 2 open slots ({start, label}) from the requested date onward."""
    etype, key = _event_type(event_type_id), _key(api_key)
    if not key or not etype:
        return mock_slots(preferred_date, tz)

    today = dt.datetime.now(dt.timezone.utc).date()
    start = today
    try:
        if preferred_date:
            pd = dt.date.fromisoformat(preferred_date.strip()[:10])
            start = pd if pd >= today else today
    except ValueError:
        pass

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://api.cal.com/v2/slots",
                headers={"Authorization": f"Bearer {key}", "cal-api-version": "2024-09-04"},
                params={
                    "eventTypeId": etype,
                    "start": start.isoformat(),
                    "end": (start + dt.timedelta(days=10)).isoformat(),
                    "timeZone": _zone(tz).key,
                },
            )
            resp.raise_for_status()
            data = (resp.json() or {}).get("data") or {}
        picks: list[str] = []
        for day in sorted(data.keys()):
            starts = [(s.get("start") if isinstance(s, dict) else s) for s in data[day]]
            starts = [s for s in starts if s]
            if starts:
                picks.append(starts[len(starts) // 2])
            if len(picks) >= 2:
                break
        return [{"start": s, "label": _label(s, tz)} for s in picks]
    except Exception as exc:
        log.warning("calcom_fetch_failed", error=str(exc))
        return []


async def create_booking(start: str, email: str, name: str, event_type_id: str | None = None,
                         api_key: str | None = None, tz: str | None = None) -> str:
    """Book `start` for the attendee. Returns a booking link ('' on failure)."""
    etype, key = _event_type(event_type_id), _key(api_key)
    if not key or not etype:
        log.info("calcom_not_configured_mock_booking", email=email)
        return f"https://cal.com/mock-booking?start={start}&attendee={email}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.cal.com/v2/bookings",
                headers={"Authorization": f"Bearer {key}", "cal-api-version": "2024-08-13"},
                json={
                    "start": start,
                    "eventTypeId": int(etype),
                    "attendee": {"name": name or "Guest", "email": email, "timeZone": _zone(tz).key, "language": "en"},
                    "metadata": {"source": "closer"},
                },
            )
            resp.raise_for_status()
            data = (resp.json() or {}).get("data") or {}
        uid = data.get("uid") or data.get("id")
        return f"https://cal.com/booking/{uid}" if uid else ""
    except Exception as exc:
        log.warning("calcom_booking_failed", error=str(exc))
        return ""


_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _choice_hour(c: str) -> int | None:
    import re
    # Prefer an explicit time ("at 6", "6pm", "6:30"), not a day of the month ("October 13").
    cands = list(re.finditer(r"(?:\bat\s+)?\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.|o'?clock)?\b", c))
    timed = [m for m in cands if m.group(0).strip().startswith("at") or m.group(2) or m.group(3)]
    pool = timed or [m for m in cands if int(m.group(1)) <= 12]
    if not pool:
        return None
    m = pool[-1]
    hour = int(m.group(1))
    suffix = (m.group(3) or "").replace(".", "")
    if suffix == "pm" or (suffix != "am" and ("afternoon" in c or "evening" in c or "night" in c)):
        hour = hour % 12 + 12
    elif suffix == "am" and hour == 12:
        hour = 0
    elif suffix != "am" and 1 <= hour <= 7:
        hour += 12  # "at 3" / "at 6" on a business call means afternoon/evening
    return hour


def pick_slot(slots: list[dict], choice: str) -> dict | None:
    """
    Resolve 'first' / 'B' / 'Tuesday at 6 in the evening' / an ISO time to one of
    the offered slots. Returns None when the choice is ambiguous — never guesses.
    """
    if not slots:
        return None
    c = (choice or "").strip().lower()
    if c in ("a", "1", "first", "option a", "the first one", "the first"):
        return slots[0]
    if c in ("b", "2", "second", "option b", "the second one", "the second") and len(slots) > 1:
        return slots[1]
    exact = [s for s in slots if c and (c == s["start"].lower() or c == s["label"].lower())]
    if exact:
        return exact[0]

    import re
    day = next((d for d in _WEEKDAYS if d in c), None)
    iso = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", c)
    hour = _choice_hour(re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", c))
    scored = []
    for s in slots:
        try:
            when = dt.datetime.fromisoformat(s["start"].replace("Z", "+00:00"))
        except ValueError:
            continue
        if day and _WEEKDAYS[when.weekday()] != day:
            continue
        if iso and when.date().isoformat() != iso.group(1):
            continue
        if hour is not None and when.hour != hour:
            continue
        if day or iso or hour is not None:
            scored.append(s)
    if len(scored) == 1:
        return scored[0]
    if len(slots) == 1 and not c:
        return slots[0]
    return None


def remember_slots(known: list[dict], new: list[dict]) -> list[dict]:
    """Keep every slot offered during the call bookable (deduped by start time)."""
    seen = {s["start"] for s in known}
    return known + [s for s in new if s["start"] not in seen]
