"""
Calendar router — connect a Google Calendar to the account, show its busy
events next to booked meetings, and push meetings onto it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app.models.calendar import CalendarConnection
from app.routers.meetings import _joined, meeting_to_dict, sync_calendar
from app.services import google_calendar as gcal
from app.services.auth import CtxDep, DbDep, ManagerDep

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/calendar", tags=["calendar"])


def _base(request: Request) -> str:
    return f"{request.headers.get('x-forwarded-proto', request.url.scheme)}://{request.headers.get('x-forwarded-host', request.url.netloc)}"


@router.get("/google")
async def google_status(ctx: CtxDep, db: DbDep):
    conn = await gcal.connection(db, ctx.org.id)
    return {
        "configured": gcal.configured(),
        "connected": conn is not None,
        "email": conn.email if conn else None,
        "connected_at": conn.created_at.isoformat() if conn and conn.created_at else None,
        "can_manage": ctx.can_manage,
    }


@router.post("/google/connect")
async def google_connect(request: Request, ctx: ManagerDep):
    if not gcal.configured():
        raise HTTPException(status_code=409, detail="Google Calendar isn't set up on this server yet.")
    state = gcal.make_state(ctx.org.id, ctx.user.id, "/meetings")
    return {"url": gcal.auth_url(state, _base(request))}


@router.get("/google/callback")
async def google_callback(request: Request, db: DbDep, code: str = "", state: str = "", error: str = ""):
    """Google redirects the browser here after consent. The signed state says which account it's for."""
    def back(result: str) -> RedirectResponse:
        return RedirectResponse(f"/meetings?google={result}", status_code=303)

    if error or not code or not state:
        return back("cancelled")
    try:
        st = gcal.read_state(state)
        refresh, email = await gcal.exchange_code(code, _base(request))
    except gcal.CalendarError as exc:
        log.warning("gcal_connect_failed", error=str(exc))
        return back("failed")
    org_id = uuid.UUID(st["o"])
    conn = await db.get(CalendarConnection, org_id)
    if conn is None:
        conn = CalendarConnection(org_id=org_id, refresh_token_enc="")
        db.add(conn)
    conn.refresh_token_enc = gcal.encrypt(refresh)
    conn.email = email[:255]
    conn.calendar_id = "primary"
    conn.connected_by = uuid.UUID(st["u"])
    conn.created_at = datetime.now(timezone.utc)
    gcal._tokens.pop(org_id, None)
    await db.commit()
    log.info("gcal_connected", org_id=str(org_id))
    return back("connected")


@router.delete("/google", status_code=204)
async def google_disconnect(ctx: ManagerDep, db: DbDep):
    conn = await db.get(CalendarConnection, ctx.org.id)
    if conn is None:
        return
    await gcal.revoke(conn)
    await db.delete(conn)
    await db.commit()


@router.get("/events")
async def calendar_events(ctx: CtxDep, db: DbDep, start: datetime = Query(...), end: datetime = Query(...)):
    """Busy events from the connected Google Calendar between start and end (max 31 days)."""
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(status_code=422, detail="start and end need a time zone offset.")
    if end <= start or end - start > timedelta(days=31):
        raise HTTPException(status_code=422, detail="Pick a range of up to 31 days.")
    conn = await gcal.connection(db, ctx.org.id)
    if conn is None:
        return {"connected": False, "events": []}
    try:
        return {"connected": True, "events": await gcal.list_events(conn, start, end)}
    except gcal.CalendarError as exc:
        return {"connected": True, "events": [], "error": str(exc)}


@router.post("/google/sync")
async def google_sync(ctx: ManagerDep, db: DbDep):
    """Put every upcoming scheduled meeting that has a time onto the connected calendar."""
    if await gcal.connection(db, ctx.org.id) is None:
        raise HTTPException(status_code=409, detail="Connect Google Calendar first.")
    rows = (await db.execute(_joined(ctx.org.id))).all()
    now = datetime.now(timezone.utc)
    synced, errors = 0, []
    for c, lead, agent, campaign in rows:
        m = meeting_to_dict(c, lead, agent, campaign, ctx.org.timezone)
        if m["follow_up_status"] != "scheduled" or not m["start"] or datetime.fromisoformat(m["start"]) < now:
            continue
        err = await sync_calendar(db, ctx.org.id, c, m)
        if err:
            errors.append(err)
            break  # the same error would repeat for every meeting
        synced += 1
    return {"synced": synced, "error": errors[0] if errors else None}

