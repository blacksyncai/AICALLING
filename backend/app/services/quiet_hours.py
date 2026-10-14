"""
Never ring someone at an unreasonable hour where *they* are. Campaign calling hours are set in the
campaign's timezone; a list can still hold numbers from other zones (a New York campaign calling
California at 9 AM Eastern is 6 AM there). Automated dialing also checks the contact's own local time,
worked out from their number, against 8 AM – 9 PM (the usual legal calling window).

Only numbers whose timezone is known count: unknown numbers, and ones spanning many zones (toll-free),
are left to the campaign's own hours.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import phonenumbers
from phonenumbers import timezone as pn_timezone

EARLIEST, LATEST = 8, 21  # local hours, [8:00, 21:00)


@lru_cache(maxsize=4096)
def zones_for(phone: str) -> tuple[str, ...]:
    try:
        zones = pn_timezone.time_zones_for_number(phonenumbers.parse(phone or ""))
    except phonenumbers.NumberParseException:
        return ()
    zones = tuple(z for z in zones if z and not z.startswith("Etc/"))
    return zones if 0 < len(zones) <= 3 else ()


def ok_to_call(phone: str, now_utc: datetime) -> bool:
    """False only when it's before 8 AM or after 9 PM in (every) zone the number belongs to."""
    for zone in zones_for(phone):
        try:
            hour = now_utc.astimezone(ZoneInfo(zone)).hour
        except ZoneInfoNotFoundError:
            return True
        if not EARLIEST <= hour < LATEST:
            return False
    return True
