"""Minimum connected duration for every agent-initiated hangup.

Carriers surcharge calls that connect for under ~6 seconds, so the agent never ends a call before
MIN_CONNECTED_FLOOR seconds after pickup (8 s: a safe margin over 6), whatever an agent's saved setting says."""
import asyncio
import math
import time

MIN_CONNECTED_FLOOR = 8.0
DEFAULT_MIN_CONNECTED_SECONDS = MIN_CONNECTED_FLOOR


def minimum_connected_seconds(raw):
    value = (raw or {}).get('voicemail_min_connected_seconds', DEFAULT_MIN_CONNECTED_SECONDS)
    try:
        value = float(value)
    except (ValueError, TypeError):
        return DEFAULT_MIN_CONNECTED_SECONDS
    return min(60.0, max(MIN_CONNECTED_FLOOR, value)) if math.isfinite(value) else DEFAULT_MIN_CONNECTED_SECONDS


async def wait_for_voicemail_minimum(connected_at, tuning, *, clock=time.monotonic, sleep=asyncio.sleep):
    # connected_at is set after SIP active, never while ringing. Wall clocks and
    # provider billing clocks are not used. Already-long calls get no extra wait.
    remaining = minimum_connected_seconds(tuning) - (clock() - connected_at)
    if remaining > 0:
        await sleep(remaining)


async def finish_voicemail(connected_at, tuning, *, hangup, report,
                           clock=time.monotonic, sleep=asyncio.sleep):
    """Finalization must follow the hold and hangup, not freeze duration at detection."""
    await wait_for_voicemail_minimum(connected_at, tuning, clock=clock, sleep=sleep)
    await hangup()
    await report()
