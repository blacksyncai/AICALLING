"""
Reporting time zone — every organization reports "which day did this happen
on?" in one IANA time zone (Organization.timezone, default America/New_York),
so a 10:30 pm Eastern call never lands on tomorrow's square.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

DEFAULT_TIMEZONE = "America/New_York"


@lru_cache(maxsize=1)
def _zones() -> frozenset[str]:
    return frozenset(available_timezones())


def is_valid_timezone(name: str | None) -> bool:
    if not name or name not in _zones():
        return False
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def org_timezone_name(org) -> str:
    name = getattr(org, "timezone", None)
    return name if is_valid_timezone(name) else DEFAULT_TIMEZONE


def org_zone(org) -> ZoneInfo:
    return ZoneInfo(org_timezone_name(org))


def aware_utc(d: datetime | None) -> datetime | None:
    """SQLite hands datetimes back naive; they were stored in UTC."""
    if d is None:
        return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def local_day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """[start, end) of a calendar day in `tz`, as UTC datetimes (DST-safe: 23/25-hour days work)."""
    start = datetime.combine(day, time(0), tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz).astimezone(timezone.utc)
    return start, end


def local_date(d: datetime, tz: ZoneInfo) -> date:
    return aware_utc(d).astimezone(tz).date()
