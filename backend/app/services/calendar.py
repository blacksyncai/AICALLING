"""
Cal.com slot lookup + booking, shared by the API playground and the voice worker.
Mock slots/receipts require an explicit playground-only allow_mock flag.
Voice calls fail closed if a real calendar is not configured.
"""

from __future__ import annotations

import datetime as dt
import asyncio

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import structlog

from app.config import settings

log = structlog.get_logger(__name__)


class CalendarUnavailable(RuntimeError):
    """No authoritative availability/booking result; distinct from zero openings."""

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


_NUM = ["twelve", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven"]
_MIN = {15: "fifteen", 30: "thirty", 45: "forty-five"}


def _say_time(d: dt.datetime) -> str:
    """10:00 → "10", 14:15 → "two fifteen", 19:00 → "7 in the evening": how a person says it on the phone."""
    h12 = d.hour % 12
    clock = str(h12 or 12) if not d.minute else f"{_NUM[h12]} {_MIN.get(d.minute) or f'{d.minute:02d}'}"
    if d.hour < 8:
        return clock + " in the morning"
    if d.hour >= 18:
        return clock + " in the evening"
    return clock


def say_day(d: dt.date, today: dt.date) -> str:
    gap = (d - today).days
    if gap == 0:
        return "today"
    if gap == 1:
        return "tomorrow"
    if 1 < gap < 7:
        return d.strftime("%A")
    n = d.day
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{d.strftime('%A')} the {n}{suffix}"


def spoken_offer(slots: list[dict], tz: str | None = None, now: dt.datetime | None = None) -> str:
    """The offered times the way a person says them: "tomorrow at 10, 11 or 1, or Thursday at two fifteen".
    No month, no year, no time zone."""
    zone = _zone(tz)
    today = (now or dt.datetime.now(dt.timezone.utc)).astimezone(zone).date()
    days: dict[str, list[str]] = {}
    for s in slots:
        try:
            d = dt.datetime.fromisoformat(s["start"].replace("Z", "+00:00")).astimezone(zone)
        except (ValueError, KeyError):
            continue
        days.setdefault(say_day(d.date(), today), []).append(_say_time(d))

    def join(xs: list[str]) -> str:
        return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " or " + xs[-1]

    return ", or ".join(f"{day} at {join(times)}" for day, times in days.items())


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


PARTS = {"morning": (0, 12), "afternoon": (12, 17), "evening": (17, 24)}


def _all_mock(start: dt.date, tz: str | None) -> list[str]:
    """Without Cal.com: hourly weekday openings 9 AM–5 PM (in the calendar's zone) for 10 days."""
    zone, out = _zone(tz), []
    for i in range(10):
        day = start + dt.timedelta(days=i)
        if day.weekday() >= 5:
            continue
        for hour in range(9, 17):
            out.append(dt.datetime.combine(day, dt.time(hour), tzinfo=zone).astimezone(dt.timezone.utc).isoformat())
    return out


def _spread(items: list, n: int) -> list:
    """n items evenly across the list (first, middle, last …) so options cover the day."""
    if len(items) <= n:
        return items
    if n == 1:
        return [items[len(items) // 2]]
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]


def choose_slots(starts: list[str], tz: str | None, preferred_date: str = "", time_of_day: str = "",
                 time: str = "", exclude: set[str] | None = None, count: int = 3) -> list[str]:
    """Pick what to offer from every open start time:
    - a preferred day → up to `count` times spread across that day (else the next days that have room)
    - time_of_day (morning/afternoon/evening) or an exact time ("15:00") narrows it
    - times already offered on this call are skipped, so asking again gives new options."""
    zone, exclude = _zone(tz), exclude or set()
    local = []
    for st in starts:
        try:
            d = dt.datetime.fromisoformat(st.replace("Z", "+00:00")).astimezone(zone)
        except ValueError:
            continue
        if st in exclude:
            continue
        local.append((d, st))
    local.sort()
    part = PARTS.get((time_of_day or "").strip().lower())
    if part:
        local = [x for x in local if part[0] <= x[0].hour < part[1]]
    want_day = None
    try:
        if preferred_date:
            want_day = dt.date.fromisoformat(preferred_date.strip()[:10])
    except ValueError:
        pass
    target = None
    m = __import__("re").match(r"^\s*(\d{1,2})(?::(\d{2}))?", time or "")
    if m:
        target = int(m.group(1)) * 60 + int(m.group(2) or 0)
    by_day: dict[dt.date, list] = {}
    for d, st in local:
        by_day.setdefault(d.date(), []).append((d, st))
    days = sorted(by_day)
    if want_day:
        days = [x for x in days if x >= want_day]
    if not days:
        return []
    first = days[0]
    todays = by_day[first]
    if target is not None:
        todays = sorted(todays, key=lambda x: abs(x[0].hour * 60 + x[0].minute - target))[:count]
        todays.sort()
        picks = todays
    else:
        picks = _spread(todays, count)
    out = [st for _, st in picks]
    # Not much room that day: add the next day's options so there's still a choice.
    for nxt in days[1:]:
        if len(out) >= 2:
            break
        out += [st for _, st in _spread(by_day[nxt], count - len(out))]
    return out[:count]


async def fetch_slots(preferred_date: str = "", event_type_id: str | None = None,
                      api_key: str | None = None, tz: str | None = None, *, time_of_day: str = "",
                      time: str = "", exclude: set[str] | None = None, count: int = 3,
                      allow_mock: bool = False) -> list[dict]:
    """Open slots ({start, label}) to offer, from Cal.com's full availability (see choose_slots)."""
    etype, key = _event_type(event_type_id), _key(api_key)
    today = dt.datetime.now(dt.timezone.utc).date()
    start = today
    try:
        if preferred_date:
            pd = dt.date.fromisoformat(preferred_date.strip()[:10])
            start = pd if pd >= today else today
    except ValueError:
        pass

    if not key or not etype:
        if not allow_mock:
            raise CalendarUnavailable("Calendar is not connected")
        starts = _all_mock(start if start > today else today + dt.timedelta(days=1), tz)
    else:
        try:
            async with asyncio.timeout(8.0), httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    "https://api.cal.com/v2/slots",
                    headers={"Authorization": f"Bearer {key}", "cal-api-version": "2024-09-04"},
                    params={
                        "eventTypeId": etype,
                        "start": start.isoformat(),
                        "end": (start + dt.timedelta(days=14)).isoformat(),
                        "timeZone": _zone(tz).key,
                    },
                )
                resp.raise_for_status()
                data = (resp.json() or {}).get("data") or {}
            starts = [(x.get("start") if isinstance(x, dict) else x) for day in data.values() for x in day]
            starts = [x for x in starts if x]
        except Exception as exc:
            log.warning("calcom_fetch_failed", error=type(exc).__name__)
            if allow_mock:
                return []
            raise CalendarUnavailable("Availability could not be verified") from exc
    picks = choose_slots(starts, tz, preferred_date, time_of_day, time, exclude, count)
    return [{"start": x, "label": _label(x, tz)} for x in picks]


async def create_booking(start: str, email: str, name: str, event_type_id: str | None = None,
                         api_key: str | None = None, tz: str | None = None, *, allow_mock: bool = False) -> str:
    """Return a provider booking receipt; raise on unverified real results.

    The playground may explicitly request simulated receipts and legacy empty
    failure results. Production voice never opts into that behavior.
    """
    etype, key = _event_type(event_type_id), _key(api_key)
    if not key or not etype:
        if not allow_mock:
            raise CalendarUnavailable("Calendar is not connected")
        return f"https://cal.com/mock-booking?start={start}&attendee={email}"
    try:
        async with asyncio.timeout(10.0), httpx.AsyncClient(timeout=10.0) as client:
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
        log.warning("calcom_booking_failed", error=type(exc).__name__)
        if allow_mock:
            return ""
        raise CalendarUnavailable("Booking result unavailable; do not retry automatically") from exc


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


def pick_slot(slots: list[dict], choice: str, tz: str | None = None, recent: list[dict] | None = None) -> dict | None:
    """
    Resolve 'first' / 'B' / 'Tuesday at 6 in the evening' / an ISO time to one of
    the offered slots. Returns None when the choice is ambiguous — never guesses.
    """
    if not slots:
        return None
    c = (choice or "").strip().lower()
    ordered = recent or slots  # "the first one" means the first of the times just offered
    if c in ("a", "1", "first", "option a", "the first one", "the first"):
        return ordered[0]
    if c in ("b", "2", "second", "option b", "the second one", "the second") and len(ordered) > 1:
        return ordered[1]
    exact = [s for s in slots if c and (c == s["start"].lower() or c == s["label"].lower())]
    if exact:
        return exact[0]

    import re
    day = next((d for d in _WEEKDAYS if d in c), None)
    if not day and ("today" in c or "tomorrow" in c):
        base = dt.datetime.now(dt.timezone.utc).astimezone(_zone(tz)).date()
        day = _WEEKDAYS[(base + dt.timedelta(days=1 if "tomorrow" in c else 0)).weekday()]
    iso = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", c)
    hour = _choice_hour(re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", c))
    scored = []
    for s in slots:
        try:
            when = dt.datetime.fromisoformat(s["start"].replace("Z", "+00:00"))
        except ValueError:
            continue
        if tz and when.tzinfo is not None:
            when = when.astimezone(_zone(tz))  # the contact picks by the calendar's local day and hour
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
