"""
Calls router — call history (phone, browser and campaign calls) with
transcripts and post-call analysis, plus the dashboard overview.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.agent import Agent
from app.models.call_log import CallLog
from app.models.campaign import Campaign
from app.models.lead import Lead

router = APIRouter(prefix="/api/calls", tags=["calls"])


def _iso(d: datetime | None) -> str | None:
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.isoformat()


def call_to_dict(c: CallLog, lead: Lead | None, agent: Agent | None, campaign: Campaign | None,
                 full: bool = False) -> dict:
    d = {
        "id": str(c.id),
        "call_type": c.call_type or "outbound",
        "status": c.status,
        "outcome": c.outcome,
        "sentiment": c.sentiment,
        "summary": c.summary,
        "duration_seconds": c.duration_seconds,
        "to_phone": c.to_phone or (lead.phone if lead else None),
        "contact_name": lead.name if lead else ("Browser test" if c.call_type == "web" else None),
        "contact_company": lead.company if lead else None,
        "agent_id": str(c.agent_id) if c.agent_id else None,
        "agent_name": agent.name if agent else None,
        "campaign_id": str(c.campaign_id) if c.campaign_id else None,
        "campaign_name": campaign.name if campaign else None,
        "meeting_link": c.meeting_link,
        "agreed_meeting_time": c.agreed_meeting_time,
        "started_at": _iso(c.started_at),
        "ended_at": _iso(c.ended_at),
    }
    if full:
        d["transcript"] = c.transcript or []
        d["extracted_data"] = c.extracted_data or {}
        d["metrics"] = c.metrics or None
        d["prospect_email"] = c.prospect_email
        d["livekit_room_name"] = c.livekit_room_name
        d["lead_id"] = str(c.lead_id) if c.lead_id else None
    return d


def _joined():
    return (
        select(CallLog, Lead, Agent, Campaign)
        .outerjoin(Lead, Lead.id == CallLog.lead_id)
        .outerjoin(Agent, Agent.id == CallLog.agent_id)
        .outerjoin(Campaign, Campaign.id == CallLog.campaign_id)
    )


@router.get("/")
async def list_calls(
    db: Annotated[AsyncSession, Depends(get_db)],
    agent_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
    outcome: str | None = None,
    call_type: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    stmt = _joined()
    count_stmt = select(func.count()).select_from(CallLog)
    filters = []
    if agent_id:
        filters.append(CallLog.agent_id == agent_id)
    if campaign_id:
        filters.append(CallLog.campaign_id == campaign_id)
    if outcome:
        filters.append(CallLog.outcome == outcome)
    if call_type:
        filters.append(CallLog.call_type == call_type)
    for f in filters:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)
    total = (await db.execute(count_stmt)).scalar_one()
    rows = await db.execute(
        stmt.order_by(CallLog.started_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return {
        "items": [call_to_dict(c, l, a, cp) for c, l, a, cp in rows.all()],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/overview")
async def overview(db: Annotated[AsyncSession, Depends(get_db)], days: int = Query(default=30, ge=1, le=365)):
    """Dashboard KPIs computed in Python so it works on SQLite and Postgres alike."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    calls = (await db.execute(
        select(CallLog.started_at, CallLog.outcome, CallLog.duration_seconds, CallLog.call_type,
               CallLog.agent_id, CallLog.sentiment)
        .where(CallLog.started_at >= since)
    )).all()

    outcomes = Counter(c.outcome or "in_progress" for c in calls)
    connected = [c for c in calls if (c.duration_seconds or 0) > 0]
    total_seconds = sum(c.duration_seconds or 0 for c in calls)
    positive = {"meeting_booked", "qualified", "interested", "transferred"}
    wins = sum(outcomes[o] for o in positive)

    per_day: dict[str, int] = {}
    for i in range(min(days, 30) - 1, -1, -1):
        per_day[(datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")] = 0
    for c in calls:
        if c.started_at:
            key = c.started_at.strftime("%Y-%m-%d")
            if key in per_day:
                per_day[key] += 1

    agents_n = (await db.execute(select(func.count()).select_from(Agent))).scalar_one()
    campaigns_n = (await db.execute(
        select(func.count()).select_from(Campaign).where(Campaign.status == "running")
    )).scalar_one()

    return {
        "total_calls": len(calls),
        "connected_calls": len(connected),
        "total_minutes": round(total_seconds / 60, 1),
        "avg_duration_seconds": round(total_seconds / len(connected)) if connected else 0,
        "meetings_booked": outcomes.get("meeting_booked", 0),
        "success_rate": round(wins / len(connected), 4) if connected else 0,
        "outcomes": dict(outcomes),
        "calls_per_day": [{"date": k, "calls": v} for k, v in per_day.items()],
        "agents": agents_n,
        "running_campaigns": campaigns_n,
    }


@router.get("/{call_id}")
async def get_call(call_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    row = (await db.execute(_joined().where(CallLog.id == call_id))).first()
    if not row:
        raise HTTPException(status_code=404, detail="Call not found")
    c, l, a, cp = row
    return call_to_dict(c, l, a, cp, full=True)


@router.post("/{call_id}/analyze")
async def reanalyze_call(call_id: uuid.UUID, background_tasks: BackgroundTasks,
                         db: Annotated[AsyncSession, Depends(get_db)]):
    """Re-run post-call analysis (e.g. after changing the agent's extraction fields)."""
    from app.services.outbound_call import analyze_and_store

    if not await db.get(CallLog, call_id):
        raise HTTPException(status_code=404, detail="Call not found")
    background_tasks.add_task(analyze_and_store, str(call_id))
    return {"queued": True}
