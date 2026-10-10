"""
CallService — starts LiveKit-backed calls for configurable agents.

Three entry points share one flow:
  • web call    — browser test call: room + agent dispatch + a join token for the browser
  • phone call  — LiveKit SIP outbound through the configured trunk
  • campaign    — phone call for a campaign lead (uses the campaign's agent)

Call flow (phone):
1. Create the LiveKit room carrying call metadata (read by the agent worker).
2. Explicitly dispatch the agent worker (agent_name=pounce) to that room —
   agent_name workers do NOT auto-join rooms.
3. `create_sip_participant` dials the number via the outbound trunk. The worker
   waits for sip.callStatus="active" before speaking so the opener isn't lost.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from livekit import api
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runtime import agent_to_runtime, lead_variables
from app.config import settings
from app.models.agent import Agent
from app.models.call_log import CallLog
from app.models.campaign import Campaign
from app.models.lead import Lead

log = structlog.get_logger(__name__)

# Keep room metadata comfortably small; big knowledge bases are fetched by the worker.
_MAX_INLINE_METADATA = 48_000


class CallSetupError(RuntimeError):
    """Raised when a call can't be placed because something isn't configured."""


def _lk() -> api.LiveKitAPI:
    if not settings.livekit_ready:
        raise CallSetupError("LiveKit is not configured (LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET).")
    return api.LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )


def validate_e164(phone: str) -> str:
    phone = (phone or "").strip().replace(" ", "").replace("-", "")
    digits = phone.lstrip("+")
    if not phone.startswith("+") or not digits.isdigit() or len(digits) < 10 or set(digits) == {"0"}:
        raise ValueError(f"{phone!r} is not a valid E.164 phone number (e.g. +14155550123).")
    return phone


def _build_metadata(call_log: CallLog, agent: Agent | None, variables: dict, call_type: str,
                    lead: Lead | None) -> str:
    meta: dict = {
        "call_log_id": str(call_log.id),
        "call_type": call_type,
        "lead_id": str(lead.id) if lead else "",
        "variables": variables,
        # Legacy fields read by the original Paul agent.
        "name": (lead.name if lead else variables.get("name", "")) or "there",
        "company": (lead.company if lead else variables.get("company", "")) or "",
        "phone": (lead.phone if lead else variables.get("phone", "")) or "",
        "role": (lead.role if lead else "") or "",
        "email": (lead.email if lead else "") or "",
    }
    if agent is not None:
        meta["agent_id"] = str(agent.id)
        meta["agent"] = agent_to_runtime(agent)
    raw = json.dumps(meta)
    if len(raw) > _MAX_INLINE_METADATA and agent is not None:
        meta["agent"]["knowledge_base"] = ""
        meta["fetch_config"] = True
        raw = json.dumps(meta)
    return raw


class CallService:

    async def _create_room_and_dispatch(self, lk: api.LiveKitAPI, room_name: str, metadata: str) -> None:
        await lk.room.create_room(api.CreateRoomRequest(
            name=room_name, metadata=metadata, empty_timeout=120, max_participants=5,
        ))
        agent_name = settings.livekit_agent_name or "pounce"
        dispatch = await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
            agent_name=agent_name, room=room_name, metadata=metadata,
        ))
        log.info("agent_dispatched", room=room_name, agent_name=agent_name,
                 dispatch_id=getattr(dispatch, "id", ""))

    async def start_web_call(self, agent: Agent, db: AsyncSession, variables: dict | None = None) -> dict:
        """Browser voice test: returns {url, token, room, call_id} for livekit-client."""
        if not settings.voice_ready:
            raise CallSetupError(
                "Voice isn't configured. Set LIVEKIT_URL/API_KEY/API_SECRET, OPENAI_API_KEY, "
                "DEEPGRAM_API_KEY and CARTESIA_API_KEY on the backend, and run the agent worker."
            )
        room_name = f"web-{agent.id.hex[:8]}-{int(time.time())}"
        call_log = CallLog(
            id=uuid.uuid4(), agent_id=agent.id, call_type="web", livekit_room_name=room_name,
            status="connected", started_at=datetime.now(timezone.utc),
        )
        db.add(call_log)
        await db.flush()
        variables = {"name": "there", **(variables or {})}
        metadata = _build_metadata(call_log, agent, variables, "web", None)
        await db.commit()

        lk = _lk()
        try:
            await self._create_room_and_dispatch(lk, room_name, metadata)
        except Exception:
            call_log.status, call_log.outcome = "failed", "failed"
            call_log.ended_at = datetime.now(timezone.utc)
            await db.commit()
            raise
        finally:
            await lk.aclose()

        identity = f"web-user-{uuid.uuid4().hex[:6]}"
        token = (
            api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
            .with_identity(identity)
            .with_name("Tester")
            .with_grants(api.VideoGrants(room_join=True, room=room_name))
            .with_ttl(timedelta(hours=1))
            .to_jwt()
        )
        return {"url": settings.livekit_url, "token": token, "room": room_name, "call_id": str(call_log.id)}

    async def dispatch_call(self, lead: Lead | None, db: AsyncSession, *, agent: Agent | None = None,
                            to_phone: str | None = None, campaign_id: uuid.UUID | None = None) -> CallLog:
        """Dial a phone number via LiveKit SIP outbound with the given agent."""
        if not settings.livekit_sip_outbound_trunk_id:
            raise CallSetupError(
                "Phone calling isn't configured — set LIVEKIT_SIP_OUTBOUND_TRUNK_ID "
                "(a LiveKit outbound SIP trunk, e.g. via Twilio Elastic SIP)."
            )
        phone = validate_e164(to_phone or (lead.phone if lead else ""))
        campaign_id = campaign_id or (lead.campaign_id if lead else None)

        if agent is None and campaign_id:
            campaign = await db.get(Campaign, campaign_id)
            if campaign and campaign.agent_id:
                agent = await db.get(Agent, campaign.agent_id)

        room_name = f"call-{(lead.id.hex[:8] if lead else 'test')}-{int(time.time())}"
        call_log = CallLog(
            id=uuid.uuid4(),
            lead_id=lead.id if lead else None,
            campaign_id=campaign_id,
            agent_id=agent.id if agent else None,
            call_type="outbound",
            to_phone=phone,
            livekit_room_name=room_name,
            status="initiated",
            started_at=datetime.now(timezone.utc),
        )
        db.add(call_log)
        await db.flush()

        variables = lead_variables(lead) if lead else {"phone": phone}
        metadata = _build_metadata(call_log, agent, variables, "outbound", lead)

        if lead:
            await db.execute(update(Lead).where(Lead.id == lead.id)
                             .values(status="calling", updated_at=datetime.now(timezone.utc)))
        await db.commit()
        log.info("dispatching_call", lead_id=str(lead.id) if lead else None, phone=phone,
                 room=room_name, agent=str(agent.id) if agent else "legacy")

        lk = _lk()
        try:
            await self._create_room_and_dispatch(lk, room_name, metadata)
            sip_resp = await lk.sip.create_sip_participant(api.CreateSIPParticipantRequest(
                sip_trunk_id=settings.livekit_sip_outbound_trunk_id,
                sip_call_to=phone,
                room_name=room_name,
                participant_identity=f"sip_{phone.lstrip('+')}",
                participant_name=(lead.name if lead else phone) or phone,
                play_dialtone=False,
                ringing_timeout=timedelta(seconds=45),
                wait_until_answered=False,
                krisp_enabled=True,
            ))
            log.info("livekit_sip_dialed", room=room_name, to=phone,
                     sip_call_id=getattr(sip_resp, "sip_call_id", ""))
        except Exception as exc:
            log.error("dispatch_call_failed", error=str(exc), room=room_name)
            now = datetime.now(timezone.utc)
            await db.execute(update(CallLog).where(CallLog.id == call_log.id)
                             .values(status="failed", outcome="failed", ended_at=now))
            if lead:
                await db.execute(update(Lead).where(Lead.id == lead.id).values(status="failed", updated_at=now))
            await db.commit()
            raise
        finally:
            await lk.aclose()

        return call_log

    async def update_call_outcome(
        self,
        call_log_id: str,
        outcome: str,
        transcript: list[dict] | None,
        meeting_link: str | None,
        qualification_score: int | None,
        db: AsyncSession,
        agreed_meeting_time: str | None = None,
        prospect_email: str | None = None,
        metrics: dict | None = None,
    ) -> CallLog | None:
        call_log = (await db.execute(
            select(CallLog).where(CallLog.id == uuid.UUID(call_log_id))
        )).scalar_one_or_none()
        if not call_log:
            log.warning("update_call_outcome_not_found", call_log_id=call_log_id)
            return None

        now = datetime.now(timezone.utc)
        started = call_log.started_at
        if started and started.tzinfo is None:  # SQLite drops tzinfo
            started = started.replace(tzinfo=timezone.utc)
        duration = int((now - started).total_seconds()) if started else None

        status = {"no_answer": "no_answer", "voicemail": "no_answer", "failed": "failed"}.get(outcome, "completed")
        await db.execute(update(CallLog).where(CallLog.id == call_log.id).values(
            status=status,
            outcome=outcome,
            transcript=transcript,
            meeting_link=meeting_link,
            agreed_meeting_time=agreed_meeting_time or None,
            prospect_email=prospect_email or None,
            duration_seconds=duration,
            ended_at=now,
            **({"metrics": metrics} if metrics else {}),
        ))

        if call_log.lead_id:
            lead_values: dict = {"status": outcome if outcome != "completed" else "completed", "updated_at": now}
            if qualification_score is not None:
                lead_values["qualification_score"] = qualification_score
            if meeting_link:
                lead_values["notes"] = f"Meeting: {meeting_link}"
            await db.execute(update(Lead).where(Lead.id == call_log.lead_id).values(**lead_values))

        if call_log.campaign_id:
            inc: dict = {}
            if outcome == "meeting_booked":
                inc = {"total_booked": Campaign.total_booked + 1, "total_qualified": Campaign.total_qualified + 1}
            elif outcome in ("qualified", "interested"):
                inc = {"total_qualified": Campaign.total_qualified + 1}
            if inc:
                await db.execute(update(Campaign).where(Campaign.id == call_log.campaign_id).values(**inc))

        await db.commit()
        log.info("call_outcome_updated", call_log_id=call_log_id, outcome=outcome, duration=duration)
        return call_log


async def analyze_and_store(call_log_id: str) -> None:
    """Background: run post-call analysis and save summary/sentiment/extracted fields."""
    from app.database import AsyncSessionLocal
    from app.services.llm import analyze_call

    async with AsyncSessionLocal() as db:
        call_log = await db.get(CallLog, uuid.UUID(call_log_id))
        if not call_log or not call_log.transcript:
            return
        agent = await db.get(Agent, call_log.agent_id) if call_log.agent_id else None
        result = await analyze_call(
            call_log.transcript,
            agent.extraction_fields if agent else None,
            agent.success_criteria if agent else "",
        )
        if not result:
            return
        call_log.summary = result.get("summary")
        call_log.sentiment = result.get("sentiment")
        call_log.extracted_data = {**(result.get("extracted") or {}), "_successful": result.get("successful")}
        # The analyzer's outcome only fills in when the agent didn't pick a specific one.
        if call_log.outcome in (None, "completed", "failed") and result.get("outcome"):
            if call_log.duration_seconds or call_log.outcome != "failed":
                call_log.outcome = result["outcome"]
        await db.commit()
        log.info("call_analyzed", call_log_id=call_log_id, outcome=call_log.outcome)


# Singleton (name kept for existing imports)
call_service = CallService()
outbound_call_service = call_service
