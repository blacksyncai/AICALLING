"""
Search router — one quick lookup across contacts, agents, campaigns and calls,
used by the ⌘K command palette. Everything is scoped to the current account.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query
from sqlalchemy import or_, select

from app.models.agent import Agent
from app.models.call_log import CallLog
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.services.auth import CtxDep, DbDep

router = APIRouter(prefix="/api/search", tags=["search"])

LIMIT = 8
EMPTY = {"contacts": [], "agents": [], "campaigns": [], "calls": []}


def _iso(d: datetime | None) -> str | None:
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()


def _escape(term: str) -> str:
    """Treat % and _ in what people type as literal characters."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("")
@router.get("/")
async def search(ctx: CtxDep, db: DbDep, q: str = Query(default="", max_length=100)):
    term = q.strip()
    if len(term) < 2:
        return EMPTY
    like = f"%{_escape(term)}%"
    org_id = ctx.org.id

    def ilike(col):
        return col.ilike(like, escape="\\")

    contacts = (await db.execute(
        select(Lead).where(Lead.org_id == org_id,
                           or_(ilike(Lead.name), ilike(Lead.company), ilike(Lead.email), ilike(Lead.phone)))
        .order_by(Lead.updated_at.desc()).limit(LIMIT)
    )).scalars().all()

    agents = (await db.execute(
        select(Agent).where(Agent.org_id == org_id, ilike(Agent.name)).order_by(Agent.name).limit(LIMIT)
    )).scalars().all()

    campaigns = (await db.execute(
        select(Campaign).where(Campaign.org_id == org_id, ilike(Campaign.name))
        .order_by(Campaign.created_at.desc()).limit(LIMIT)
    )).scalars().all()

    calls = (await db.execute(
        select(CallLog, Lead.name)
        .outerjoin(Lead, Lead.id == CallLog.lead_id)
        .where(CallLog.org_id == org_id, or_(ilike(Lead.name), ilike(CallLog.to_phone)))
        .order_by(CallLog.started_at.desc()).limit(LIMIT)
    )).all()

    return {
        "contacts": [{"id": str(l.id), "name": l.name, "company": l.company or "", "phone": l.phone}
                     for l in contacts],
        "agents": [{"id": str(a.id), "name": a.name} for a in agents],
        "campaigns": [{"id": str(c.id), "name": c.name, "status": c.status} for c in campaigns],
        "calls": [{"id": str(c.id), "contact_name": name or c.to_phone or "Unknown caller",
                   "to_phone": c.to_phone or "", "outcome": c.outcome, "started_at": _iso(c.started_at)}
                  for c, name in calls],
    }
