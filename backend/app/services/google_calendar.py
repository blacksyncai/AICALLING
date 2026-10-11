"""
Google Calendar for meetings: OAuth connection per account, reading busy events
for the meetings timeline, and mirroring booked meetings as calendar events.

Needs GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET (a Google Cloud "Web application"
OAuth client whose redirect URI is {APP_URL}/api/calendar/google/callback) and
SECRETS_ENCRYPTION_KEY, which encrypts the stored refresh token.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

import httpx
import structlog
from cryptography.fernet import InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.calendar import CalendarConnection
from app.services import secret_store

log = structlog.get_logger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/calendar/v3"
SCOPES = ["openid", "email", "https://www.googleapis.com/auth/calendar.events"]
STATE_TTL = 600

_tokens: dict[uuid.UUID, tuple[str, float]] = {}  # org → (access token, expiry)


class CalendarError(RuntimeError):
    pass


def configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret and secret_store.available())


def redirect_uri(base: str) -> str:
    return f"{(settings.app_url or base).rstrip('/')}/api/calendar/google/callback"


# ── OAuth ─────────────────────────────────────────────────────────────────────


def make_state(org_id: uuid.UUID, user_id: uuid.UUID, return_to: str) -> str:
    payload = json.dumps({"o": str(org_id), "u": str(user_id), "r": return_to, "n": uuid.uuid4().hex}).encode()
    return secret_store._fernet().encrypt(payload).decode()


def read_state(state: str) -> dict:
    try:
        return json.loads(secret_store._fernet().decrypt(state.encode(), ttl=STATE_TTL))
    except (InvalidToken, ValueError) as exc:
        raise CalendarError("This Google sign-in link expired. Please try connecting again.") from exc


def auth_url(state: str, base: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_id": settings.google_client_id, "redirect_uri": redirect_uri(base), "response_type": "code",
        "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true",
        "state": state,
    })


def _email_from_id_token(id_token: str) -> str:
    # Straight from Google's token endpoint over TLS, so the payload is trusted as-is.
    try:
        part = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("email", "")
    except (IndexError, ValueError):
        return ""


async def exchange_code(code: str, base: str) -> tuple[str, str]:
    """Returns (refresh token, email)."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(TOKEN_URL, data={
            "code": code, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
            "redirect_uri": redirect_uri(base), "grant_type": "authorization_code",
        })
    if r.status_code != 200:
        log.warning("gcal_exchange_failed", status=r.status_code, body=r.text[:300])
        raise CalendarError("Google didn't accept the sign-in. Please try again.")
    data = r.json()
    if not data.get("refresh_token"):
        raise CalendarError("Google didn't grant offline access. Remove BlackSync from your Google account's apps and connect again.")
    scopes = set((data.get("scope") or "").split())
    if "https://www.googleapis.com/auth/calendar.events" not in scopes:
        raise CalendarError("Calendar access wasn't granted. Tick the calendar permission when you connect.")
    return data["refresh_token"], _email_from_id_token(data.get("id_token", ""))


def encrypt(token: str) -> str:
    return secret_store._fernet().encrypt(token.encode()).decode()


def _refresh_token(conn: CalendarConnection) -> str:
    try:
        return secret_store._fernet().decrypt(conn.refresh_token_enc.encode()).decode()
    except InvalidToken as exc:
        raise CalendarError("The saved Google connection can't be read. Please reconnect Google Calendar.") from exc


async def _access_token(conn: CalendarConnection) -> str:
    cached = _tokens.get(conn.org_id)
    if cached and cached[1] > time.time() + 60:
        return cached[0]
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(TOKEN_URL, data={
            "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
            "refresh_token": _refresh_token(conn), "grant_type": "refresh_token",
        })
    if r.status_code != 200:
        _tokens.pop(conn.org_id, None)
        raise CalendarError("Google Calendar access was removed. Reconnect it on the Meetings page.")
    d = r.json()
    _tokens[conn.org_id] = (d["access_token"], time.time() + int(d.get("expires_in", 3600)))
    return d["access_token"]


async def revoke(conn: CalendarConnection) -> None:
    _tokens.pop(conn.org_id, None)
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(REVOKE_URL, params={"token": _refresh_token(conn)})
    except (httpx.HTTPError, CalendarError) as exc:
        log.info("gcal_revoke_skipped", error=str(exc))


async def _call(conn: CalendarConnection, method: str, path: str, **kw) -> dict:
    token = await _access_token(conn)
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.request(method, API + path, headers={"Authorization": f"Bearer {token}"}, **kw)
    if r.status_code in (200, 201):
        return r.json()
    if r.status_code in (204, 410) or (method == "DELETE" and r.status_code == 404):
        return {}
    log.warning("gcal_api_error", path=path.split("?")[0], status=r.status_code, body=r.text[:300])
    raise CalendarError("Google Calendar returned an error. Try again in a moment.")


def _cal(conn: CalendarConnection) -> str:
    return quote(conn.calendar_id or "primary", safe="")


# ── Events ────────────────────────────────────────────────────────────────────


async def list_events(conn: CalendarConnection, start: datetime, end: datetime) -> list[dict]:
    data = await _call(conn, "GET", f"/calendars/{_cal(conn)}/events", params={
        "timeMin": start.isoformat(), "timeMax": end.isoformat(), "singleEvents": "true",
        "orderBy": "startTime", "maxResults": "250",
    })
    out = []
    for e in data.get("items", []):
        s, en = e.get("start", {}), e.get("end", {})
        if "dateTime" not in s:  # all-day events don't block a time slot
            continue
        if (e.get("extendedProperties") or {}).get("private", {}).get("blacksync_call"):
            continue  # our own meeting events are already on the timeline
        out.append({"id": e["id"], "title": e.get("summary") or "Busy", "start": s["dateTime"], "end": en.get("dateTime"),
                    "link": e.get("htmlLink")})
    return out


def _event_body(m: dict, start: datetime, minutes: int) -> dict:
    who = (m.get("contact") or {}).get("name") or m.get("to_phone") or "a contact"
    lines = [f"Booked by {m.get('agent_name') or 'your AI agent'} on BlackSync."]
    if m.get("summary"):
        lines += ["", m["summary"]]
    if m.get("to_phone"):
        lines += ["", f"Phone: {m['to_phone']}"]
    if m.get("prospect_email"):
        lines.append(f"Email: {m['prospect_email']}")
    body = {
        "summary": f"Meeting with {who}",
        "description": "\n".join(lines),
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": (start + timedelta(minutes=minutes)).isoformat()},
        "extendedProperties": {"private": {"blacksync_call": m["call_id"]}},
    }
    if m.get("meeting_link"):
        body["location"] = m["meeting_link"]
    return body


async def upsert_event(conn: CalendarConnection, event_id: str | None, m: dict, start: datetime, minutes: int) -> str:
    """Create or move the meeting's event. Guests are never emailed (sendUpdates=none)."""
    body = _event_body(m, start, minutes)
    if event_id:
        try:
            d = await _call(conn, "PATCH", f"/calendars/{_cal(conn)}/events/{quote(event_id, safe='')}?sendUpdates=none", json=body)
            if d.get("id"):
                return d["id"]
        except CalendarError:
            pass  # deleted in Google — create it again below
    d = await _call(conn, "POST", f"/calendars/{_cal(conn)}/events?sendUpdates=none", json=body)
    return d["id"]


async def delete_event(conn: CalendarConnection, event_id: str) -> None:
    await _call(conn, "DELETE", f"/calendars/{_cal(conn)}/events/{quote(event_id, safe='')}?sendUpdates=none")


async def connection(db: AsyncSession, org_id: uuid.UUID) -> CalendarConnection | None:
    if not configured():
        return None
    return await db.get(CalendarConnection, org_id)


def now() -> datetime:
    return datetime.now(timezone.utc)
