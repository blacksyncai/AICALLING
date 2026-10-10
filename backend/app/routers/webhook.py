"""
Pounce — /api/webhook router

Receives real-time intent signals (e.g. pricing page visit) and triggers outbound calls.
Also receives call outcome updates from the agent's fire-and-forget task.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.models.lead import Lead

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/webhook", tags=["webhook"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class LeadIntentPayload(BaseModel):
    lead_token: str
    page: str


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


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/lead-intent")
async def lead_intent(
    body: LeadIntentPayload,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Receives a lead intent signal (e.g. pricing page visit).
    Looks up the lead by token and triggers an outbound call.
    """
    result = await db.execute(
        select(Lead).where(Lead.lead_token == body.lead_token)
    )
    lead = result.scalar_one_or_none()

    if not lead:
        log.warning("lead_intent_token_not_found", token=body.lead_token, page=body.page)
        raise HTTPException(status_code=404, detail="Lead token not found")

    if lead.status not in ("new", "no_answer"):
        log.info(
            "lead_intent_skipped",
            lead_id=str(lead.id),
            status=lead.status,
            reason="already contacted or in progress",
        )
        return {
            "message": "Lead already contacted",
            "lead_id": str(lead.id),
            "status": lead.status,
        }

    log.info(
        "lead_intent_received",
        lead_id=str(lead.id),
        name=lead.name,
        page=body.page,
    )

    # Fire call in background so we return immediately
    background_tasks.add_task(_dispatch_intent_call, str(lead.id))

    return {
        "message": "Call dispatch queued",
        "lead_id": str(lead.id),
        "name": lead.name,
    }


@router.post("/calls/{call_log_id}/live-event")
async def push_live_event(call_log_id: str, body: dict):
    """
    Called by the agent_worker (fire-and-forget) to push a real-time event to
    all connected Live Monitor SSE clients. Accepts any LiveEvent JSON payload.
    """
    from app.routers.live import broadcast
    broadcast(body)
    return {"ok": True}


@router.post("/calls/{call_log_id}/outcome")
async def call_outcome(
    call_log_id: str,
    body: CallOutcomePayload,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Endpoint called by the agent's fire-and-forget task when a call ends.
    Updates CallLog and Lead in the database.
    """
    from app.services.outbound_call import outbound_call_service

    log.info(
        "call_outcome_webhook",
        call_log_id=call_log_id,
        outcome=body.outcome,
        score=body.qualification_score,
    )

    await outbound_call_service.update_call_outcome(
        call_log_id=call_log_id,
        outcome=body.outcome,
        transcript=body.transcript,
        meeting_link=body.meeting_link,
        qualification_score=body.qualification_score,
        agreed_meeting_time=body.agreed_meeting_time or None,
        prospect_email=body.prospect_email or None,
        metrics=body.metrics,
        db=db,
    )

    from app.services.outbound_call import analyze_and_store
    background_tasks.add_task(analyze_and_store, call_log_id)
    return {"message": "Outcome recorded", "call_log_id": call_log_id}


# ── Background helper ─────────────────────────────────────────────────────────


async def _dispatch_intent_call(lead_id: str) -> None:
    """Background task: fetch lead from DB and dispatch outbound call."""
    from app.services.outbound_call import outbound_call_service

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Lead).where(Lead.id == uuid.UUID(lead_id)))
        lead = result.scalar_one_or_none()
        if not lead:
            log.error("dispatch_intent_call_lead_missing", lead_id=lead_id)
            return

        try:
            await outbound_call_service.dispatch_call(lead, db)
        except Exception as exc:
            log.error("dispatch_intent_call_failed", lead_id=lead_id, error=str(exc))
