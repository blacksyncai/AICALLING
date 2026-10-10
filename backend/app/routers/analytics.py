"""
Analytics router — how phone calls turn into meetings: the funnel, outcome mix,
per-agent and per-campaign performance, best hours to call and sentiment.
Computed in Python so it works on SQLite and Postgres alike.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.models.agent import Agent
from app.models.call_log import CallLog
from app.models.campaign import Campaign
from app.services.auth import CtxDep, DbDep

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

QUALIFIED = {"qualified", "interested", "meeting_booked", "transferred"}
CONVERSATION_SECONDS = 30


def _aware(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


def _connected(c) -> bool:
    return (c.duration_seconds or 0) > 0 or c.answered_at is not None


def _rate(n: int, d: int) -> float:
    return round(n / d, 4) if d else 0


@router.get("")
@router.get("/", include_in_schema=False)
async def analytics(ctx: CtxDep, db: DbDep, days: int = Query(default=30, ge=1, le=365)):
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    rows = (await db.execute(
        select(
            CallLog.started_at, CallLog.answered_at, CallLog.outcome, CallLog.duration_seconds,
            CallLog.sentiment, CallLog.credits_charged, CallLog.agent_id, CallLog.campaign_id,
        ).where(
            CallLog.org_id == ctx.org.id,
            CallLog.call_type == "outbound",
            CallLog.started_at >= since - timedelta(days=1),  # widened; exact cut below (naive SQLite dates)
        )
    )).all()
    calls = [c for c in rows if c.started_at and _aware(c.started_at) >= since]

    connected = [c for c in calls if _connected(c)]
    funnel = {
        "dialed": len(calls),
        "connected": len(connected),
        "conversations": sum(1 for c in calls if (c.duration_seconds or 0) >= CONVERSATION_SECONDS),
        "qualified": sum(1 for c in calls if c.outcome in QUALIFIED),
        "booked": sum(1 for c in calls if c.outcome == "meeting_booked"),
    }

    # Names for every agent/campaign that appears in the window.
    agent_ids = {c.agent_id for c in calls if c.agent_id}
    campaign_ids = {c.campaign_id for c in calls if c.campaign_id}
    agent_names = dict((await db.execute(
        select(Agent.id, Agent.name).where(Agent.org_id == ctx.org.id, Agent.id.in_(agent_ids))
    )).all()) if agent_ids else {}
    campaign_names = dict((await db.execute(
        select(Campaign.id, Campaign.name).where(Campaign.org_id == ctx.org.id, Campaign.id.in_(campaign_ids))
    )).all()) if campaign_ids else {}

    by_agent: dict = {}
    by_campaign: dict = {}
    for c in calls:
        a = by_agent.setdefault(c.agent_id, {"calls": 0, "connected": 0, "booked": 0, "seconds": 0})
        a["calls"] += 1
        a["connected"] += _connected(c)
        a["booked"] += c.outcome == "meeting_booked"
        a["seconds"] += c.duration_seconds or 0
        if c.campaign_id:
            cp = by_campaign.setdefault(c.campaign_id, {"calls": 0, "connected": 0, "booked": 0})
            cp["calls"] += 1
            cp["connected"] += _connected(c)
            cp["booked"] += c.outcome == "meeting_booked"

    agents_out = sorted((
        {
            "agent_id": str(aid) if aid else None,
            "name": agent_names.get(aid) or ("Deleted agent" if aid else "No agent"),
            "calls": s["calls"],
            "connected": s["connected"],
            "booked": s["booked"],
            "minutes": round(s["seconds"] / 60, 1),
            "connect_rate": _rate(s["connected"], s["calls"]),
            "book_rate": _rate(s["booked"], s["connected"]),
        } for aid, s in by_agent.items()
    ), key=lambda r: (-r["booked"], -r["calls"]))
    campaigns_out = sorted((
        {
            "campaign_id": str(cid),
            "name": campaign_names.get(cid) or "Deleted campaign",
            "calls": s["calls"],
            "connected": s["connected"],
            "booked": s["booked"],
            "book_rate": _rate(s["booked"], s["connected"]),
        } for cid, s in by_campaign.items()
    ), key=lambda r: (-r["booked"], -r["calls"]))

    by_hour = [{"hour": h, "calls": 0, "connected": 0} for h in range(24)]
    for c in calls:
        h = by_hour[_aware(c.started_at).hour]
        h["calls"] += 1
        h["connected"] += _connected(c)

    sentiment = {"positive": 0, "neutral": 0, "negative": 0}
    for c in calls:
        s = (c.sentiment or "").strip().lower()
        if s in sentiment:
            sentiment[s] += 1

    talk = sum(c.duration_seconds or 0 for c in connected)
    return {
        "days": days,
        "funnel": funnel,
        "outcomes": dict(Counter(c.outcome or "in_progress" for c in calls)),
        "by_agent": agents_out,
        "by_campaign": campaigns_out,
        "by_hour": by_hour,
        "sentiment": sentiment,
        "avg_talk_seconds": round(talk / len(connected)) if connected else 0,
        "total_minutes": round(talk / 60, 1),
        "credits_used": sum(c.credits_charged or 0 for c in calls),
    }
