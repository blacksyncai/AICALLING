"""Minimum connected duration for agent-initiated voicemail hangups."""
import asyncio
import math
import time

DEFAULT_MIN_CONNECTED_SECONDS = 6.2


def minimum_connected_seconds(raw):
    value = (raw or {}).get('voicemail_min_connected_seconds', DEFAULT_MIN_CONNECTED_SECONDS)
    try:
        value = float(value)
    except (ValueError, TypeError):
        return DEFAULT_MIN_CONNECTED_SECONDS
    return min(60.0, max(0.0, value)) if math.isfinite(value) else DEFAULT_MIN_CONNECTED_SECONDS


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
