"""
Internal router — called only by the voice worker over the private network
(it is not under /api, so the web app never proxies it to browsers).
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runtime import agent_to_runtime
from app.database import get_db
from app.models.agent import Agent

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)


class CallOutcomePayload(BaseModel):
    outcome: str  # see app.models.call_log.CALL_OUTCOMES
    qualification_score: int | None = None
    q_team_size: str = ""
    q_current_process: str = ""
    q_decision_maker: str = ""
    agreed_meeting_time: str = ""
    meeting_link: str | None = None
    prospect_email: str = ""
    transcript: list[dict] | None = None
    metrics: dict | None = None
    ended_at: float | None = None  # unix time the caller actually left (the report can lag behind)


@router.get("/agents/{agent_id}/runtime")
async def agent_runtime(agent_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    """Agent config, when it was too large to inline in the room metadata."""
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent_to_runtime(agent, secrets=True)


@router.post("/calls/{call_log_id}/live-event")
async def live_event(call_log_id: str, body: dict):
    """Live transcript events from the legacy worker path — accepted and dropped."""
    return {"ok": True}


@router.patch("/leads/{lead_id}")
async def lead_answer(lead_id: str, body: dict):
    """Qualification answers from the legacy worker path — kept in the call transcript instead."""
    return {"ok": True}


class InboundCallIn(BaseModel):
    to: str = ""
    from_number: str = ""
    room: str = ""


@router.post("/inbound-call")
async def inbound_call(body: InboundCallIn, db: Annotated[AsyncSession, Depends(get_db)]):
    """The worker asks who answers a call to this number; we log the call and hand back the agent config."""
    from app.services.inbound import route_call

    routed = await route_call(db, body.to, body.from_number, body.room)
    if not routed:
        raise HTTPException(status_code=404, detail="No agent answers this number")
    return routed


@router.post("/calls/{call_log_id}/outcome")
async def call_outcome(
    call_log_id: str,
    body: CallOutcomePayload,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """The worker reports how a call ended; analysis, billing and webhooks follow."""
    from app.services.outbound_call import analyze_and_store, outbound_call_service

    log.info("call_outcome_reported", call_log_id=call_log_id, outcome=body.outcome)
    await outbound_call_service.update_call_outcome(
        call_log_id=call_log_id,
        outcome=body.outcome,
        transcript=body.transcript,
        meeting_link=body.meeting_link,
        qualification_score=body.qualification_score,
        agreed_meeting_time=body.agreed_meeting_time or None,
        prospect_email=body.prospect_email or None,
        metrics=body.metrics,
        ended_at=body.ended_at,
        db=db,
    )
    background_tasks.add_task(analyze_and_store, call_log_id)
    return {"message": "Outcome recorded", "call_log_id": call_log_id}
