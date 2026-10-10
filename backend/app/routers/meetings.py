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
from pydantic import BaseModel
from sqlalchemy import select

from app.models.agent import Agent
from app.models.call_log import CallLog
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.services.auth import CtxDep, DbDep

router = APIRouter(prefix="/api/meetings", tags=["meetings"])

MEETING_STATUSES = ("scheduled", "completed", "no_show", "cancelled")
STATUS_KEY = "_meeting_status"


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


def meeting_to_dict(c: CallLog, lead: Lead | None, agent: Agent | None, campaign: Campaign | None) -> dict:
    return {
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
        "summary": c.summary,
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
    items = [meeting_to_dict(c, l, a, cp) for c, l, a, cp in rows]
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


class MeetingStatusIn(BaseModel):
    status: Literal["scheduled", "completed", "no_show", "cancelled"]


@router.patch("/{call_id}")
async def update_meeting(call_id: uuid.UUID, body: MeetingStatusIn, ctx: CtxDep, db: DbDep):
    row = (await db.execute(_joined(ctx.org.id).where(CallLog.id == call_id))).first()
    if not row:
        raise HTTPException(status_code=404, detail="Meeting not found")
    c, lead, agent, campaign = row
    # Assign a fresh dict so the JSON column is marked dirty.
    c.extracted_data = {**(c.extracted_data or {}), STATUS_KEY: body.status}
    await db.commit()
    await db.refresh(c)
    return meeting_to_dict(c, lead, agent, campaign)
