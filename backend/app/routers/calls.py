"""
Calls router — call history (phone, browser and campaign calls) with
transcripts and post-call analysis, plus the dashboard overview.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import date as Date, datetime, timedelta, timezone
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from sqlalchemy import func, select

from app.models.agent import Agent
from app.models.call_log import CallLog
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.services.auth import CtxDep, DbDep
from app.services.reporting import local_day_bounds, org_zone

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
        "credits_charged": c.credits_charged,
        "lead_id": str(c.lead_id) if c.lead_id else None,
    }
    if full:
        d["transcript"] = c.transcript or []
        d["extracted_data"] = c.extracted_data or {}
        d["metrics"] = c.metrics or None
        d["prospect_email"] = c.prospect_email
        d["livekit_room_name"] = c.livekit_room_name
    return d


def _joined(org_id):
    return (
        select(CallLog, Lead, Agent, Campaign)
        .where(CallLog.org_id == org_id)
        .outerjoin(Lead, Lead.id == CallLog.lead_id)
        .outerjoin(Agent, Agent.id == CallLog.agent_id)
        .outerjoin(Campaign, Campaign.id == CallLog.campaign_id)
    )


@router.get("/")
async def list_calls(
    ctx: CtxDep, db: DbDep,
    agent_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
    outcome: str | None = None,
    call_type: str | None = None,
    # A calendar day (YYYY-MM-DD) in the organization's reporting time zone.
    day: Date | None = Query(default=None, alias="date"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    stmt = _joined(ctx.org.id)
    count_stmt = select(func.count()).select_from(CallLog).where(CallLog.org_id == ctx.org.id)
    filters = []
    if agent_id:
        filters.append(CallLog.agent_id == agent_id)
    if campaign_id:
        filters.append(CallLog.campaign_id == campaign_id)
    if outcome:
        filters.append(CallLog.outcome == outcome)
    if call_type:
        filters.append(CallLog.call_type == call_type)
    if day:
        start, end = local_day_bounds(day, org_zone(ctx.org))
        filters += [CallLog.started_at >= start, CallLog.started_at < end]
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
async def overview(ctx: CtxDep, db: DbDep, days: int = Query(default=30, ge=1, le=365)):
    """Dashboard KPIs for the window plus the previous window (for trends), computed in
    Python so it works on SQLite and Postgres alike."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    prev_since = since - timedelta(days=days)
    rows = (await db.execute(
        select(CallLog.started_at, CallLog.outcome, CallLog.duration_seconds)
        .where(CallLog.org_id == ctx.org.id, CallLog.started_at >= prev_since)
    )).all()

    def _aware(d: datetime | None) -> datetime | None:
        return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d

    cur = [r for r in rows if r.started_at and _aware(r.started_at) >= since]
    prev = [r for r in rows if r.started_at and _aware(r.started_at) < since]
    positive = {"meeting_booked", "qualified", "interested", "transferred"}
    # A "meaningful conversation": a real back-and-forth (30s+) that wasn't voicemail,
    # or any call that ended with a positive outcome or a follow-up.
    follow_up = {"callback", "interested"}
    dead = {"voicemail", "no_answer", "failed"}

    def meaningful(c) -> bool:
        if c.outcome in positive or c.outcome in follow_up:
            return True
        return (c.duration_seconds or 0) >= 30 and c.outcome not in dead

    def summarize(calls: list) -> dict:
        connected = [c for c in calls if (c.duration_seconds or 0) > 0]
        seconds = sum(c.duration_seconds or 0 for c in calls)
        wins = sum(1 for c in calls if c.outcome in positive)
        return {
            "total_calls": len(calls),
            "connected_calls": len(connected),
            "total_minutes": round(seconds / 60, 1),
            "avg_duration_seconds": round(seconds / len(connected)) if connected else 0,
            "meetings_booked": sum(1 for c in calls if c.outcome == "meeting_booked"),
            "success_rate": round(wins / len(connected), 4) if connected else 0,
            "connect_rate": round(len(connected) / len(calls), 4) if calls else 0,
            "meaningful_calls": sum(1 for c in calls if meaningful(c)),
            "follow_ups": sum(1 for c in calls if c.outcome in follow_up),
        }

    per_day: dict[str, dict] = {}
    for i in range(min(days, 90) - 1, -1, -1):
        key = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        per_day[key] = {"date": key, "calls": 0, "connected": 0, "booked": 0}
    for c in cur:
        key = _aware(c.started_at).strftime("%Y-%m-%d")
        if key in per_day:
            per_day[key]["calls"] += 1
            if (c.duration_seconds or 0) > 0:
                per_day[key]["connected"] += 1
            if c.outcome == "meeting_booked":
                per_day[key]["booked"] += 1

    org_id = ctx.org.id
    agents_n = (await db.execute(select(func.count()).select_from(Agent).where(Agent.org_id == org_id))).scalar_one()
    campaigns_n = (await db.execute(
        select(func.count()).select_from(Campaign).where(Campaign.org_id == org_id, Campaign.status == "running")
    )).scalar_one()
    lead_dates = (await db.execute(select(Lead.created_at).where(Lead.org_id == org_id))).scalars().all()
    new_leads = sum(1 for d in lead_dates if d and _aware(d) >= since)
    prev_new_leads = sum(1 for d in lead_dates if d and prev_since <= _aware(d) < since)

    return {
        **summarize(cur),
        "previous": summarize(prev),
        "outcomes": dict(Counter(c.outcome or "in_progress" for c in cur)),
        "calls_per_day": list(per_day.values()),
        "agents": agents_n,
        "running_campaigns": campaigns_n,
        "total_leads": len(lead_dates),
        "new_leads": new_leads,
        "previous_new_leads": prev_new_leads,
        "credits_balance": ctx.org.credits_balance,
        "unlimited_credits": ctx.org.unlimited_credits,
        "days": days,
    }


@router.get("/{call_id}")
async def get_call(call_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    row = (await db.execute(_joined(ctx.org.id).where(CallLog.id == call_id))).first()
    if not row:
        raise HTTPException(status_code=404, detail="Call not found")
    c, l, a, cp = row
    return call_to_dict(c, l, a, cp, full=True)


@router.post("/{call_id}/analyze")
async def reanalyze_call(call_id: uuid.UUID, background_tasks: BackgroundTasks,
                         ctx: CtxDep, db: DbDep):
    """Re-run post-call analysis (e.g. after changing the agent's extraction fields)."""
    from app.services.outbound_call import analyze_and_store

    call = await db.get(CallLog, call_id)
    if not call or call.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Call not found")
    background_tasks.add_task(analyze_and_store, str(call_id))
    return {"queued": True}
