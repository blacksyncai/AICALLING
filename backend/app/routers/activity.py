"""
Activity router — daily totals for the dashboard's AI Calling Activity heat map.

One square per calendar day in the organization's reporting time zone. Every
query is scoped to ctx.org (the signed-in organization, or the sub-account a
platform admin is viewing); an org id is never taken from the client.

Metric definitions (phone calls only — browser test calls are left out):
  calls         phone calls the agents placed (CallLog, call_type "outbound"),
                bucketed by when the call started.
  connected     of those, calls the contact picked up: answered_at is set, or the
                call has talk time (duration_seconds > 0).
  appointments  calls whose outcome is "meeting_booked". A call has exactly one
                outcome, so a booking is counted once; there is no separate
                appointments table.
  transfers     calls with outcome "transferred" whose transcript shows the
                agent's transfer_call tool ran — i.e. the phone system accepted
                the hand-off to your team. A "transferred" outcome picked by the
                AI or the post-call analyzer without a real hand-off isn't counted,
                and we can't see whether the teammate answered.
  credits       calling credits deducted, from the credit ledger
                (CreditTransaction kind "usage"), bucketed by when they were charged.

Aggregation is server-side: only the handful of columns needed for the org,
range and agent are read, then grouped by local day with zoneinfo — the same
code on SQLite and Postgres, with no dialect-specific time-zone SQL.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_, select

from app.models.account import CreditTransaction
from app.models.agent import Agent
from app.models.call_log import CallLog
from app.services.auth import CtxDep, DbDep
from app.services.reporting import local_date, local_day_bounds, org_timezone_name, org_zone

router = APIRouter(prefix="/api/activity", tags=["activity"])

Metric = Literal["calls", "connected", "appointments", "transfers", "credits"]
Range = Literal["30d", "90d", "12m"]

METRICS: tuple[str, ...] = ("calls", "connected", "appointments", "transfers", "credits")
RANGE_DAYS = {"30d": 30, "90d": 90, "12m": 365}
TOP_AGENTS = 5


def _is_connected(answered_at, duration_seconds) -> bool:
    return answered_at is not None or (duration_seconds or 0) > 0


def _is_real_transfer(transcript) -> bool:
    """The worker records a transfer_call tool entry before handing the call over,
    and resets the outcome if the phone system rejects the transfer."""
    for t in transcript or []:
        if isinstance(t, dict) and t.get("role") == "tool" and t.get("tool") == "transfer_call":
            return True
    return False


def _parse_agent(agent_id: str | None) -> uuid.UUID | None:
    if agent_id is None or not agent_id.strip():
        return None
    try:
        return uuid.UUID(agent_id.strip())
    except ValueError:
        raise HTTPException(status_code=422, detail="agent_id must be an agent id.")


@router.get("/daily")
async def daily_activity(
    ctx: CtxDep,
    db: DbDep,
    metric: Metric = Query(default="calls"),
    range_: Range = Query(default="12m", alias="range"),
    agent_id: str | None = Query(default=None),
):
    org = ctx.org
    tz = org_zone(org)
    aid = _parse_agent(agent_id)

    agent_names = {
        a_id: name for a_id, name in (await db.execute(
            select(Agent.id, Agent.name).where(Agent.org_id == org.id)
        )).all()
    }
    if aid is not None and aid not in agent_names:
        raise HTTPException(status_code=404, detail="Agent not found")

    today = datetime.now(timezone.utc).astimezone(tz).date()
    start_day = today - timedelta(days=RANGE_DAYS[range_] - 1)
    start_utc, _ = local_day_bounds(start_day, tz)
    _, end_utc = local_day_bounds(today, tz)

    # day -> totals, and day -> agent -> per-metric counts
    days: dict = defaultdict(lambda: {m: 0 for m in METRICS})
    per_agent: dict = defaultdict(lambda: defaultdict(lambda: {m: 0 for m in METRICS}))

    def bump(day, agent, field, n=1):
        days[day][field] += n
        per_agent[day][agent][field] += n

    # ── Calls, connected, appointments, transfers ────────────────────────────
    call_q = select(
        CallLog.id, CallLog.agent_id, CallLog.started_at, CallLog.answered_at,
        CallLog.duration_seconds, CallLog.outcome,
    ).where(
        CallLog.org_id == org.id,
        # Phone calls: outbound, plus older rows saved before call_type existed.
        or_(CallLog.call_type == "outbound", CallLog.call_type.is_(None)),
        CallLog.started_at >= start_utc,
        CallLog.started_at < end_utc,
    )
    if aid is not None:
        call_q = call_q.where(CallLog.agent_id == aid)
    transfer_ids: list[uuid.UUID] = []
    call_rows = (await db.execute(call_q)).all()
    call_day: dict[uuid.UUID, tuple] = {}
    for r in call_rows:
        day = local_date(r.started_at, tz)
        if not (start_day <= day <= today):
            continue
        bump(day, r.agent_id, "calls")
        if _is_connected(r.answered_at, r.duration_seconds):
            bump(day, r.agent_id, "connected")
        if r.outcome == "meeting_booked":
            bump(day, r.agent_id, "appointments")
        elif r.outcome == "transferred":
            transfer_ids.append(r.id)
            call_day[r.id] = (day, r.agent_id)

    # Transcripts only for the (few) calls marked transferred, to confirm a real hand-off.
    for i in range(0, len(transfer_ids), 500):
        chunk = transfer_ids[i:i + 500]
        for cid, transcript in (await db.execute(
            select(CallLog.id, CallLog.transcript).where(CallLog.org_id == org.id, CallLog.id.in_(chunk))
        )).all():
            if _is_real_transfer(transcript):
                day, agent = call_day[cid]
                bump(day, agent, "transfers")

    # ── Credits, from the ledger ─────────────────────────────────────────────
    credit_q = (
        select(CreditTransaction.amount, CreditTransaction.created_at, CallLog.agent_id)
        .outerjoin(CallLog, CallLog.id == CreditTransaction.call_id)
        .where(
            CreditTransaction.org_id == org.id,
            CreditTransaction.kind == "usage",
            CreditTransaction.created_at >= start_utc,
            CreditTransaction.created_at < end_utc,
        )
    )
    if aid is not None:
        credit_q = credit_q.where(CallLog.agent_id == aid)
    for amount, created_at, agent in (await db.execute(credit_q)).all():
        day = local_date(created_at, tz)
        if start_day <= day <= today and amount:
            bump(day, agent, "credits", -amount)

    credits_total = sum(d["credits"] for d in days.values())
    metric_available, note = True, None
    if metric == "credits" and org.unlimited_credits and credits_total == 0:
        metric_available = False
        note = ("This account has unlimited calling, so no credits are deducted per call "
                "and there's no credit usage to show.")

    def agent_name(a):
        if a is None:
            return "Removed agent"
        return agent_names.get(a, "Removed agent")

    out_days = []
    for day in sorted(days):
        d = days[day]
        if not any(d.values()):
            continue
        breakdown = sorted(
            ((a, v[metric]) for a, v in per_agent[day].items() if v[metric] > 0),
            key=lambda x: (-x[1], agent_name(x[0])),
        )[:TOP_AGENTS]
        out_days.append({
            "date": day.isoformat(),
            "value": d[metric] if metric_available else 0,
            **d,
            "agents": [{"id": str(a) if a else None, "name": agent_name(a), "value": v} for a, v in breakdown],
        })

    totals = {m: sum(d[m] for d in days.values()) for m in METRICS}
    totals["value"] = totals[metric] if metric_available else 0
    totals["active_days"] = sum(1 for d in out_days if d["value"] > 0)

    return {
        "metric": metric,
        "range": range_,
        "timezone": org_timezone_name(org),
        "start": start_day.isoformat(),
        "end": today.isoformat(),
        "agent": {"id": str(aid), "name": agent_names[aid]} if aid is not None else None,
        "days": out_days,
        "totals": totals,
        "metric_available": metric_available,
        "credits_tracked": not (org.unlimited_credits and credits_total == 0),
        "note": note,
    }
