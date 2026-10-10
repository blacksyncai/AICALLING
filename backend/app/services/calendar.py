"""
Cal.com slot lookup + booking, shared by the API playground and the voice worker.
Falls back to realistic mock slots when Cal.com isn't configured, so booking
flows can be tested end-to-end without an account.
"""

from __future__ import annotations

import datetime as dt

import httpx
import structlog

from app.config import settings

log = structlog.get_logger(__name__)

_TZ_LABEL = "UTC"


def _event_type(event_type_id: str | None) -> str:
    return (event_type_id or settings.calcom_event_type_id or "").strip()


def _label(start_iso: str) -> str:
    try:
        d = dt.datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        return d.strftime(f"%A, %B %-d at %-I:%M %p {_TZ_LABEL}")
    except Exception:
        return start_iso


def mock_slots(preferred_date: str = "") -> list[dict]:
    base = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    try:
        if preferred_date:
            d = dt.date.fromisoformat(preferred_date.strip()[:10])
            if d >= base.date():
                base = dt.datetime.combine(d, dt.time(0), tzinfo=dt.timezone.utc) - dt.timedelta(days=1)
    except ValueError:
        pass
    a = (base + dt.timedelta(days=1)).replace(hour=15)
    b = (base + dt.timedelta(days=2)).replace(hour=18)
    return [{"start": s.isoformat(), "label": _label(s.isoformat())} for s in (a, b)]


async def fetch_slots(preferred_date: str = "", event_type_id: str | None = None) -> list[dict]:
    """Return up to 2 open slots ({start, label}) from the requested date onward."""
    etype = _event_type(event_type_id)
    if not settings.calcom_api_key or not etype:
        return mock_slots(preferred_date)

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
                headers={"Authorization": f"Bearer {settings.calcom_api_key}", "cal-api-version": "2024-09-04"},
                params={
                    "eventTypeId": etype,
                    "start": start.isoformat(),
                    "end": (start + dt.timedelta(days=10)).isoformat(),
                    "timeZone": "UTC",
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
        return [{"start": s, "label": _label(s)} for s in picks] or mock_slots(preferred_date)
    except Exception as exc:
        log.warning("calcom_fetch_failed", error=str(exc))
        return mock_slots(preferred_date)


async def create_booking(start: str, email: str, name: str, event_type_id: str | None = None) -> str:
    """Book `start` for the attendee. Returns a booking link ('' on failure)."""
    etype = _event_type(event_type_id)
    if not settings.calcom_api_key or not etype:
        log.info("calcom_not_configured_mock_booking", email=email)
        return f"https://cal.com/mock-booking?start={start}&attendee={email}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.cal.com/v2/bookings",
                headers={"Authorization": f"Bearer {settings.calcom_api_key}", "cal-api-version": "2024-08-13"},
                json={
                    "start": start,
                    "eventTypeId": int(etype),
                    "attendee": {"name": name or "Guest", "email": email, "timeZone": "UTC", "language": "en"},
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


def pick_slot(slots: list[dict], choice: str) -> dict | None:
    """Resolve 'first' / 'B' / 'Tuesday' / an ISO string to one of the offered slots."""
    if not slots:
        return None
    c = (choice or "").strip().lower()
    if c in ("a", "1", "first", "option a", "the first one"):
        return slots[0]
    if c in ("b", "2", "second", "option b", "the second one") and len(slots) > 1:
        return slots[1]
    for s in slots:
        if c and (c in s["label"].lower() or c == s["start"].lower()):
            return s
    return slots[0]
