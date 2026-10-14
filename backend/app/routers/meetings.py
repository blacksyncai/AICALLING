"""
Meetings router — every call where an agent booked a meeting, plus a small
follow-up status the team tracks per meeting (scheduled / completed / no-show /
cancelled). The status lives in the call's extracted_data["_meeting_status"], so
no schema change is needed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.models.agent import Agent
from app.services.public_errors import public_summary
from app.models.call_log import CallLog
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.services import google_calendar as gcal
from app.services import meeting_time
from app.services.auth import CtxDep, DbDep

router = APIRouter(prefix="/api/meetings", tags=["meetings"])

MEETING_STATUSES = ("scheduled", "completed", "no_show", "cancelled")
STATUS_KEY = "_meeting_status"
START_KEY = "_meeting_start"        # ISO time someone set (or confirmed) in BlackSync
DURATION_KEY = "_meeting_minutes"
EVENT_KEY = "_gcal_event_id"        # the meeting's Google Calendar event, when synced
DEFAULT_MINUTES = 30


def _aware(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


def _iso(d: datetime | None) -> str | None:
    d = _aware(d)
    return d.isoformat() if d else None


def _status(c: CallLog) -> str:
    s = (c.extracted_data or {}).get(STATUS_KEY)
    return s if s in MEETING_STATUSES else "scheduled"


def _booked_at(c: CallLog) -> datetime | None:
    return _aware(c.ended_at or c.started_at)


def meeting_start(c: CallLog, tz_name: str | None) -> tuple[datetime | None, str | None]:
    """(start, source): "set" when someone picked the time, "parsed" when read from what the agent agreed."""
    raw = (c.extracted_data or {}).get(START_KEY)
    if raw:
        try:
            return _aware(datetime.fromisoformat(raw)), "set"
        except ValueError:
            pass
    parsed = meeting_time.parse(c.agreed_meeting_time, _booked_at(c), tz_name)
    return (parsed, "parsed") if parsed else (None, None)


def meeting_to_dict(c: CallLog, lead: Lead | None, agent: Agent | None, campaign: Campaign | None,
                    tz_name: str | None = None) -> dict:
    # A time booked through the calendar tool was spoken in the agent's calendar time zone.
    booked_tz = agent.calendar_timezone if (agent and c.meeting_link and getattr(agent, "calendar_timezone", None)) else None
    start, source = meeting_start(c, booked_tz or (campaign.timezone if campaign else None) or tz_name)
    data = c.extracted_data or {}
    return {
        "start": start.isoformat() if start else None,
        "start_source": source,
        "duration_minutes": int(data.get(DURATION_KEY) or DEFAULT_MINUTES),
        "calendar_synced": bool(data.get(EVENT_KEY)),
        "call_id": str(c.id),
        "contact": {
            "id": str(lead.id), "name": lead.name, "company": lead.company,
            "phone": lead.phone, "email": lead.email,
        } if lead else None,
        "to_phone": c.to_phone or (lead.phone if lead else None),
        "prospect_email": c.prospect_email or (lead.email if lead and lead.email else None),
        "meeting_time": c.agreed_meeting_time,
        "meeting_link": c.meeting_link,
        "agent_id": str(c.agent_id) if c.agent_id else None,
        "agent_name": agent.name if agent else None,
        "campaign_id": str(c.campaign_id) if c.campaign_id else None,
        "campaign_name": campaign.name if campaign else None,
        "call_type": c.call_type or "outbound",
        "summary": public_summary(getattr(c, "status", None), c.summary),
        "booked_at": _iso(_booked_at(c)),
        "follow_up_status": _status(c),
    }


def _joined(org_id):
    return (
        select(CallLog, Lead, Agent, Campaign)
        .where(CallLog.org_id == org_id, CallLog.outcome == "meeting_booked")
        .outerjoin(Lead, Lead.id == CallLog.lead_id)
        .outerjoin(Agent, Agent.id == CallLog.agent_id)
        .outerjoin(Campaign, Campaign.id == CallLog.campaign_id)
    )


@router.get("")
@router.get("/", include_in_schema=False)
async def list_meetings(
    ctx: CtxDep, db: DbDep,
    status: Literal["upcoming", "all"] = Query(default="all"),
    limit: int = Query(default=500, ge=1, le=2000),
):
    """Booked meetings, newest first. `upcoming` keeps only the ones still scheduled.
    `stats` always covers every booked meeting so the header counts stay stable."""
    rows = (await db.execute(_joined(ctx.org.id).order_by(CallLog.started_at.desc()))).all()
    items = [meeting_to_dict(c, l, a, cp, ctx.org.timezone) for c, l, a, cp in rows]
    items.sort(key=lambda m: m["booked_at"] or "", reverse=True)

    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    booked = [_booked_at(c) for c, *_ in rows]
    counts = {s: sum(1 for m in items if m["follow_up_status"] == s) for s in MEETING_STATUSES}
    attended = counts["completed"] + counts["no_show"]
    stats = {
        "this_week": sum(1 for d in booked if d and d >= week_start),
        "this_month": sum(1 for d in booked if d and d >= month_start),
        "by_status": counts,
        "show_rate": round(counts["completed"] / attended, 4) if attended else None,
    }

    if status == "upcoming":
        items = [m for m in items if m["follow_up_status"] == "scheduled"]
    return {"items": items[:limit], "total": len(items), "stats": stats}


class MeetingUpdate(BaseModel):
    status: Literal["scheduled", "completed", "no_show", "cancelled"] | None = None
    # ISO 8601 with an offset; null clears a time set here (falls back to what the agent agreed).
    start: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=480)


async def sync_calendar(db, org_id, c: CallLog, m: dict) -> str | None:
    """Mirror one meeting onto the connected Google Calendar. Returns an error message, or None."""
    conn = await gcal.connection(db, org_id)
    if conn is None:
        return None
    data = dict(c.extracted_data or {})
    event_id = data.get(EVENT_KEY)
    try:
        if m["follow_up_status"] == "cancelled" or not m["start"]:
            if event_id:
                await gcal.delete_event(conn, event_id)
                data.pop(EVENT_KEY, None)
        else:
            data[EVENT_KEY] = await gcal.upsert_event(conn, event_id, m, datetime.fromisoformat(m["start"]),
                                                      m["duration_minutes"])
    except gcal.CalendarError as exc:
        return str(exc)
    if data != (c.extracted_data or {}):
        c.extracted_data = data
        await db.commit()
    return None


@router.patch("/{call_id}")
async def update_meeting(call_id: uuid.UUID, body: MeetingUpdate, ctx: CtxDep, db: DbDep):
    row = (await db.execute(_joined(ctx.org.id).where(CallLog.id == call_id))).first()
    if not row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    c, lead, agent, campaign = row
    sent = body.model_dump(exclude_unset=True)
    data = dict(c.extracted_data or {})
    if body.status is not None:
        data[STATUS_KEY] = body.status
    if "start" in sent:
        if body.start is None:
            data.pop(START_KEY, None)
        else:
            if body.start.tzinfo is None:
                raise HTTPException(status_code=422, detail="Send the time with its time zone offset.")
            data[START_KEY] = body.start.isoformat()
    if body.duration_minutes is not None:
        data[DURATION_KEY] = body.duration_minutes
    # Assign a fresh dict so the JSON column is marked dirty.
    c.extracted_data = data
    await db.commit()
    await db.refresh(c)
    m = meeting_to_dict(c, lead, agent, campaign, ctx.org.timezone)
    error = await sync_calendar(db, ctx.org.id, c, m)
    m = meeting_to_dict(c, lead, agent, campaign, ctx.org.timezone)
    return {**m, "calendar_error": error} if error else m
