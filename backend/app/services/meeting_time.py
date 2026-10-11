"""
Best-effort reading of the meeting time an agent agreed on the call ("Tuesday at
2pm", "tomorrow 10:30 am", "March 5 at 3 PM", an ISO timestamp) into a datetime.

The words are read in the account's (or campaign's) time zone, relative to when
the call happened. Anything unclear returns None and the meeting stays "time not
confirmed" until someone sets it.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december"]
_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)(?![a-z])|\b(\d{1,2}):(\d{2})\b|\b(noon|midday)\b", re.I)
_MONTH_DAY = re.compile(r"\b(" + "|".join(m[:3] for m in _MONTHS) + r")[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.I)
_DAY_MONTH = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + "|".join(m[:3] for m in _MONTHS) + r")[a-z]*\b", re.I)
_NUMERIC = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")


def zone(name: str | None) -> ZoneInfo | timezone:
    try:
        return ZoneInfo(name) if name else timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def _time(text: str) -> time | None:
    m = _TIME.search(text)
    if not m:
        return None
    if m.group(6):
        return time(12, 0)
    if m.group(1):
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower().replace(".", "")
        if not 1 <= h <= 12 or mi > 59:
            return None
        h = (h % 12) + (12 if ap == "pm" else 0)
        return time(h, mi)
    h, mi = int(m.group(4)), int(m.group(5))
    return time(h, mi) if h < 24 and mi < 60 else None


def _future(d: date, base: date) -> date:
    """A month/day without a year: this year, or next year if it has already passed."""
    return d if d >= base else d.replace(year=d.year + 1)


def _day(text: str, base: date) -> date | None:
    t = text.lower()
    if "today" in t or "tonight" in t or "this afternoon" in t or "this evening" in t:
        return base
    if "tomorrow" in t:
        return base + timedelta(days=1)
    m = _MONTH_DAY.search(t) or None
    if m:
        mon = [x[:3] for x in _MONTHS].index(m.group(1)[:3].lower()) + 1
        try:
            return _future(date(base.year, mon, int(m.group(2))), base)
        except ValueError:
            return None
    m = _DAY_MONTH.search(t)
    if m:
        mon = [x[:3] for x in _MONTHS].index(m.group(2)[:3].lower()) + 1
        try:
            return _future(date(base.year, mon, int(m.group(1))), base)
        except ValueError:
            return None
    m = _NUMERIC.search(t)
    if m:
        y = int(m.group(3)) if m.group(3) else base.year
        y = y + 2000 if y < 100 else y
        try:
            d = date(y, int(m.group(1)), int(m.group(2)))  # US order: month/day
        except ValueError:
            return None
        return d if m.group(3) else _future(d, base)
    for i, name in enumerate(_WEEKDAYS):
        if re.search(rf"\b{name}s?\b|\b{name[:3]}\b", t):
            ahead = (i - base.weekday()) % 7
            if "next " + name in t and ahead < 7:
                ahead = ahead or 7
            return base + timedelta(days=ahead or 7)  # "Tuesday" said on a Tuesday means next week
    return None


def parse(text: str | None, booked_at: datetime | None, tz_name: str | None) -> datetime | None:
    if not text or not text.strip():
        return None
    s = text.strip()
    try:  # ISO timestamps from tools/integrations
        iso = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return iso if iso.tzinfo else iso.replace(tzinfo=zone(tz_name))
    except ValueError:
        pass
    tz = zone(tz_name)
    booked = (booked_at or datetime.now(timezone.utc)).astimezone(tz)
    base = booked.date()
    t, d = _time(s), _day(s, base)
    if t is None or d is None:
        return None
    # "Monday at 4pm" said on a Monday morning is later today, not next week.
    if d == base + timedelta(days=7) and "next" not in s.lower() and datetime.combine(base, t, tzinfo=tz) > booked:
        d = base
    return datetime.combine(d, t, tzinfo=tz)
