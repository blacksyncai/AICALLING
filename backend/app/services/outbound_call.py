"""
CallService — starts LiveKit-backed calls for configurable agents.

Three entry points share one flow:
  • web call    — browser test call: room + agent dispatch + a join token for the browser
  • phone call  — LiveKit SIP outbound through the configured trunk
  • campaign    — phone call for a campaign lead (uses the campaign's agent)

Call flow (phone):
1. Create the LiveKit room carrying call metadata (read by the agent worker).
2. Explicitly dispatch the agent worker (agent_name=closer) to that room —
   agent_name workers do NOT auto-join rooms.
3. `create_sip_participant` dials the number via the outbound trunk. The worker
   waits for sip.callStatus="active" before speaking so the opener isn't lost.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from livekit import api
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runtime import agent_to_runtime, lead_variables
from app.services.public_errors import public_summary
from app.config import settings
from app.models.account import Organization
from app.models.agent import Agent
from app.models.call_log import CallLog
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.services.accounts import charge_call, emit_event, ensure_can_call

log = structlog.get_logger(__name__)

# Keep room metadata comfortably small; big knowledge bases are fetched by the worker.
_MAX_INLINE_METADATA = 48_000


class CallSetupError(RuntimeError):
    """Raised when a call can't be placed because something isn't configured."""


class LeadBusy(CallSetupError):
    """The contact is already being dialed or is on a call — never ring someone twice at once."""


# Contacts being dialed right now in this process (one API process runs every dialer).
_IN_DIAL: set = set()


def _lk() -> api.LiveKitAPI:
    if not settings.livekit_ready:
        raise CallSetupError("LiveKit is not configured (LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET).")
    return api.LiveKitAPI(
        url=settings.livekit_http_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )


def validate_e164(phone: str) -> str:
    """Normalize to E.164: strips formatting, and assumes US/Canada (+1) for bare 10-digit numbers."""
    raw = (phone or "").strip()
    has_plus = raw.startswith("+") or raw.startswith("00")
    digits = "".join(ch for ch in raw if ch.isdigit())
    if raw.startswith("00"):
        digits = digits[2:]
    if not has_plus:
        if len(digits) == 10:
            digits = "1" + digits
        elif not (len(digits) == 11 and digits.startswith("1")):
            digits = ""
    if not (10 <= len(digits) <= 15) or set(digits) == {"0"} or digits.startswith("0"):
        raise ValueError(f"{phone!r} is not a valid E.164 phone number (e.g. +14155550123).")
    if has_plus and len(digits) == 10 and _us_number_missing_1(digits):
        digits = "1" + digits  # "+4157075948": a US number typed with + but no 1 (would dial Switzerland)
    return "+" + digits


def _us_number_missing_1(digits: str) -> bool:
    """True when +<digits> isn't a real number anywhere but +1<digits> is a valid US/Canada number."""
    import phonenumbers

    try:
        as_typed = phonenumbers.parse("+" + digits)
        as_us = phonenumbers.parse("+1" + digits)
    except phonenumbers.NumberParseException:
        return False
    return not phonenumbers.is_valid_number(as_typed) and phonenumbers.is_valid_number(as_us)


def _build_metadata(call_log: CallLog, agent: Agent | None, variables: dict, call_type: str,
                    lead: Lead | None, max_seconds: int | None = None) -> str:
    meta: dict = {
        "call_log_id": str(call_log.id),
        "call_type": call_type,
        "lead_id": str(lead.id) if lead else "",
        "variables": variables,
        "phone_number": variables.get("phone", "") or (lead.phone if lead else ""),
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
        if max_seconds:
            meta["agent"]["max_duration_seconds"] = min(meta["agent"].get("max_duration_seconds") or 600, max_seconds)
    raw = json.dumps(meta)
    if len(raw) > _MAX_INLINE_METADATA and agent is not None:
        meta["agent"]["knowledge_base"] = ""
        meta["fetch_config"] = True
        raw = json.dumps(meta)
    return raw


_BACKGROUND: set = set()

# SIP codes that mean "nobody picked up" rather than a setup problem.
_NO_ANSWER_CODES = {408, 480, 486, 487, 600, 603}

_SIP_HINTS = {
    401: "the phone carrier refused the call. If this keeps happening, message us in the chat",
    403: "the phone carrier refused the call. If this keeps happening, message us in the chat",
    404: "the number was not found",
    484: "the number looks incomplete",
}


async def _mark_call_failed(call_id: uuid.UUID, lead_id: uuid.UUID | None, outcome: str, reason: str) -> None:
    from app.database import AsyncSessionLocal

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        await db.execute(update(CallLog).where(CallLog.id == call_id).values(
            status="no_answer" if outcome == "no_answer" else "failed",
            outcome=outcome, summary=reason, duration_seconds=0, ended_at=now,
        ))
        if lead_id:
            await db.execute(update(Lead).where(Lead.id == lead_id).values(status=outcome, updated_at=now))
        await db.commit()
    await emit_call_events(call_id)


async def _start_recording(call_id: uuid.UUID, room_name: str, key: str) -> None:
    from app.database import AsyncSessionLocal
    from app.services import recordings

    try:
        egress_id = await recordings.start(room_name, key)
    except Exception as exc:  # a recording problem must never drop the call
        log.error("recording_start_failed", room=room_name, error=str(exc))
        return
    async with AsyncSessionLocal() as db:
        await db.execute(update(CallLog).where(CallLog.id == call_id)
                         .values(recording_key=key, egress_id=egress_id))
        await db.commit()


async def _dial_and_watch(req, call_id: uuid.UUID, lead_id: uuid.UUID | None, room_name: str,
                          recording_key: str | None = None) -> None:
    lk = _lk()
    try:
        resp = await lk.sip.create_sip_participant(req, timeout=60)
        log.info("livekit_sip_answered", room=room_name, to=req.sip_call_to, from_number=req.sip_number,
                 sip_call_id=getattr(resp, "sip_call_id", ""))
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await db.execute(update(CallLog).where(CallLog.id == call_id, CallLog.answered_at.is_(None))
                             .values(answered_at=datetime.now(timezone.utc), status="connected"))
            await db.commit()
        if recording_key:
            await _start_recording(call_id, room_name, recording_key)
    except api.SipCallError as exc:
        code = exc.sip_status_code or 0
        status = exc.metadata.get("sip_status", "") if exc.metadata else ""
        outcome = "no_answer" if code in _NO_ANSWER_CODES else "failed"
        hint = _SIP_HINTS.get(code, "")
        reason = (f"Not answered ({code} {status})." if outcome == "no_answer"
                  else "Call failed" + (f" — {hint}." if hint else f" ({code} {status})."))
        log.error("livekit_sip_failed", room=room_name, to=req.sip_call_to, trunk=req.sip_trunk_id,
                  sip_code=code, sip_status=status, error=str(exc),
                  metadata=dict(exc.metadata) if exc.metadata else {})
        await _mark_call_failed(call_id, lead_id, outcome, reason)
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room=room_name))
        except Exception:
            pass
    except Exception as exc:
        if "timed out" in str(exc).lower():
            # Rang out (ringing_timeout) — nobody picked up. That's a no-answer, not a failure.
            log.info("livekit_sip_no_answer", room=room_name, to=req.sip_call_to, error=str(exc)[:120])
            await _mark_call_failed(call_id, lead_id, "no_answer", "Not answered.")
        else:
            log.exception("livekit_sip_error", room=room_name, to=req.sip_call_to, trunk=req.sip_trunk_id,
                          error=str(exc), error_type=exc.__class__.__name__)
            await _mark_call_failed(call_id, lead_id, "failed", "Call failed — the call couldn't be connected.")
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room=room_name))
        except Exception:
            pass
    finally:
        await lk.aclose()


class CallService:

    async def _create_room_and_dispatch(self, lk: api.LiveKitAPI, room_name: str, metadata: str) -> None:
        await lk.room.create_room(api.CreateRoomRequest(
            name=room_name, metadata=metadata, empty_timeout=120, max_participants=5,
        ))
        agent_name = settings.livekit_agent_name or "closer"
        dispatch = await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
            agent_name=agent_name, room=room_name, metadata=metadata,
        ))
        log.info("agent_dispatched", room=room_name, agent_name=agent_name,
                 dispatch_id=getattr(dispatch, "id", ""))

    async def start_web_call(self, agent: Agent, db: AsyncSession, variables: dict | None = None,
                             record: bool = False) -> dict:
        """Browser voice test: returns {url, token, room, call_id, recording} for livekit-client.

        record=True: the voice worker records the conversation itself (both sides, mixed after the call) and
        uploads it to the recordings bucket — no LiveKit egress involved."""
        if not settings.voice_ready:
            raise CallSetupError(
                "Voice isn't configured. Set LIVEKIT_URL/API_KEY/API_SECRET, OPENAI_API_KEY, "
                "DEEPGRAM_API_KEY and CARTESIA_API_KEY on the backend, and run the agent worker."
            )
        room_name = f"web-{agent.id.hex[:8]}-{int(time.time())}"
        call_log = CallLog(
            id=uuid.uuid4(), org_id=agent.org_id, agent_id=agent.id, call_type="web", livekit_room_name=room_name,
            status="connected", started_at=datetime.now(timezone.utc),
        )
        db.add(call_log)
        await db.flush()
        variables = {"name": "there", **(variables or {})}
        metadata = _build_metadata(call_log, agent, variables, "web", None)
        if record and settings.recordings_ready:
            from app.services import recordings

            call_log.recording_key = recordings.key_for(agent.org_id, call_log.id)
            metadata = json.dumps({**json.loads(metadata), "record_key": call_log.recording_key})
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
        return {"url": settings.livekit_url, "token": token, "room": room_name, "call_id": str(call_log.id),
                "recording": bool(call_log.recording_key)}

    async def dispatch_call(self, lead: Lead | None, db: AsyncSession, *, agent: Agent | None = None,
                            to_phone: str | None = None, campaign_id: uuid.UUID | None = None,
                            from_number: str | None = None) -> CallLog:
        """Dial a phone number with the given agent — refusing a contact that's already being called."""
        if lead is None:
            return await self._dispatch(lead, db, agent=agent, to_phone=to_phone, campaign_id=campaign_id,
                                        from_number=from_number)
        recent = datetime.now(timezone.utc) - timedelta(minutes=20)
        last = lead.last_called_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if lead.id in _IN_DIAL or (lead.status == "calling" and last is not None and last >= recent):
            raise LeadBusy("This contact is already on a call.")
        _IN_DIAL.add(lead.id)
        try:
            return await self._dispatch(lead, db, agent=agent, to_phone=to_phone, campaign_id=campaign_id,
                                        from_number=from_number)
        finally:
            _IN_DIAL.discard(lead.id)

    async def _dispatch(self, lead: Lead | None, db: AsyncSession, *, agent: Agent | None = None,
                        to_phone: str | None = None, campaign_id: uuid.UUID | None = None,
                        from_number: str | None = None) -> CallLog:
        """Dial a phone number via LiveKit SIP outbound with the given agent."""
        if not settings.livekit_sip_outbound_trunk_id:
            raise CallSetupError(
                "Phone calling isn't configured — set LIVEKIT_SIP_OUTBOUND_TRUNK_ID "
                "(a LiveKit outbound SIP trunk, e.g. via Twilio Elastic SIP)."
            )
        if lead is not None and lead.do_not_call:
            raise CallSetupError("This contact is on the do-not-call list.")
        if lead is not None and lead.crm_refs:
            from app.services.crm.sync import ensure_context
            try:
                await ensure_context(db, lead)  # the agent knows the CRM's notes and history
            except Exception as exc:
                log.info("crm_context_failed", error=str(exc))
        phone = validate_e164(to_phone or (lead.phone if lead else ""))
        campaign_id = campaign_id or (lead.campaign_id if lead else None)

        if agent is None and campaign_id:
            campaign = await db.get(Campaign, campaign_id)
            if campaign and campaign.agent_id:
                agent = await db.get(Agent, campaign.agent_id)

        org_id = (agent.org_id if agent else None) or (lead.org_id if lead else None)
        org = await db.get(Organization, org_id) if org_id else None
        if org is None:
            raise CallSetupError("This call isn't attached to an account.")
        await db.refresh(org, ["credits_balance", "status", "unlimited_credits"])
        ensure_can_call(org)  # raises InsufficientCredits
        if agent is not None:
            from app.services.entitlements import check_agent_can_call

            await check_agent_can_call(db, org, agent)  # PlanLimit (an InsufficientCredits) when over the agent limit

        from app.services import recordings, telephony
        from app.services.billing.credits import reserve_for_call

        # Set credits aside and cap the call at what the balance covers.
        requested = (agent.max_duration_seconds if agent else 600) or 600
        max_seconds, rate, reserved = await reserve_for_call(db, org, agent, requested)

        room_name = f"call-{uuid.uuid4()}"
        if from_number:
            # A specific number was picked (test calls): it must be one of this account's own numbers.
            if not any(n.number == from_number for n in await telephony.active_numbers(db, org.id)):
                raise CallSetupError("That number isn't on this account — pick one of your phone numbers.")
        else:
            from_number = await telephony.caller_id_for(db, org.id, agent)
        call_log = CallLog(
            id=uuid.uuid4(),
            org_id=org.id,
            lead_id=lead.id if lead else None,
            campaign_id=campaign_id,
            agent_id=agent.id if agent else None,
            call_type="outbound",
            to_phone=phone,
            from_phone=from_number or None,
            livekit_room_name=room_name,
            credits_reserved=reserved,
            credit_rate=rate,
            status="initiated",
            started_at=datetime.now(timezone.utc),
        )
        carrier = await telephony.carrier_of(db, org.id, from_number)
        record = recordings.enabled_for(agent)
        if record and settings.recording_via_twilio and carrier == "twilio":
            # The Twilio trunk records the call; it's copied into the bucket after the call ends.
            from app.services import twilio_recordings

            twilio_recordings.mark_pending(call_log)
        db.add(call_log)
        await db.flush()

        variables = {**(lead_variables(lead) if lead else {}), "phone": phone}
        if lead and agent and (lead.custom_fields or {}).get("crm_fields"):
            # Fill the script's {{variables}} from the CRM contact (Integrations → Script variables).
            from app.models.crm import CrmConnection
            from app.services.crm import variables as crm_vars

            conns = (await db.execute(select(CrmConnection).where(CrmConnection.org_id == org.id))).scalars().all()
            variables = crm_vars.apply(variables, lead, agent, list(conns))
        metadata = _build_metadata(call_log, agent, variables, "outbound", lead, max_seconds=max_seconds)

        if lead:
            now = datetime.now(timezone.utc)
            await db.execute(update(Lead).where(Lead.id == lead.id)
                             .values(status="calling", last_called_at=now, updated_at=now))
        await db.commit()
        log.info("dispatching_call", lead_id=str(lead.id) if lead else None, phone=phone,
                 room=room_name, agent=str(agent.id) if agent else "legacy")

        if carrier == "bandwidth":
            # Bandwidth rings the contact; on answer it hands the call to LiveKit and the agent joins there.
            from app.services import bandwidth

            recording_key = recordings.key_for(org.id, call_log.id) if record and settings.recordings_ready else None
            try:
                await bandwidth.place_call(str(call_log.id), phone, from_number, metadata, recording_key)
            except bandwidth.BandwidthError as exc:
                log.error("bandwidth_dial_failed", call_log_id=str(call_log.id), error=str(exc))
                await _mark_call_failed(call_log.id, lead.id if lead else None, "failed",
                                        "Call failed — the call couldn't be placed.")
                raise CallSetupError("The call couldn't be placed. If this keeps happening, message us in the chat.") from exc
            return call_log

        lk = _lk()
        try:
            await self._create_room_and_dispatch(lk, room_name, metadata)
        except Exception as exc:
            log.error("dispatch_call_failed", error=str(exc), room=room_name)
            await _mark_call_failed(call_log.id, lead.id if lead else None, "failed", "Call failed — the call couldn't be started.")
            raise
        finally:
            await lk.aclose()

        # Dial in the background and wait for the outcome, so a carrier rejection
        # (403, busy, no answer…) is recorded on the call instead of it looking
        # "in progress" forever.
        trunk_id = (settings.livekit_sip_plivo_trunk_id if carrier == "plivo" and settings.livekit_sip_plivo_trunk_id
                    else settings.livekit_sip_outbound_trunk_id)
        sip_req = api.CreateSIPParticipantRequest(
            sip_trunk_id=trunk_id,
            sip_call_to=phone,
            sip_number=from_number,
            room_name=room_name,
            participant_identity=f"sip_{phone.lstrip('+')}",
            participant_name=(lead.name if lead else phone) or phone,
            play_dialtone=False,
            ringing_timeout=timedelta(seconds=45),
            wait_until_answered=True,
            krisp_enabled=True,
        )
        log.info("livekit_sip_dialing", room=room_name, to=phone, from_number=from_number or "trunk default",
                 trunk=trunk_id, carrier=carrier)
        # LiveKit egress only when Twilio isn't recording (egress is capped by concurrency and monthly minutes).
        recording_key = (recordings.key_for(org.id, call_log.id)
                         if record and (not settings.recording_via_twilio or carrier != "twilio") else None)
        task = asyncio.create_task(_dial_and_watch(sip_req, call_log.id, lead.id if lead else None, room_name,
                                                   recording_key))
        _BACKGROUND.add(task)
        task.add_done_callback(_BACKGROUND.discard)
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
        ended_at: float | None = None,
    ) -> CallLog | None:
        call_log = (await db.execute(
            select(CallLog).where(CallLog.id == uuid.UUID(call_log_id))
        )).scalar_one_or_none()
        if not call_log:
            log.warning("update_call_outcome_not_found", call_log_id=call_log_id)
            return None
        # A dial that already failed (e.g. carrier 403) keeps its specific reason;
        # the worker's empty "no answer" report afterwards shouldn't overwrite it.
        if call_log.ended_at and call_log.status in ("failed", "no_answer") and not transcript:
            return call_log

        prev_outcome = call_log.outcome
        now = datetime.now(timezone.utc)
        # The worker reports a few seconds (up to ~20 s) after the caller hangs up; end the call when they left.
        if ended_at:
            left = datetime.fromtimestamp(ended_at, tz=timezone.utc)
            if left <= now:
                now = left
        # Talk time runs from pickup for phone calls (ringing isn't billed), from start for web calls.
        started = call_log.answered_at or call_log.started_at
        if started and started.tzinfo is None:  # SQLite drops tzinfo
            started = started.replace(tzinfo=timezone.utc)
        duration = max(0, int((now - started).total_seconds())) if started else None
        if (call_log.call_type == "outbound" and not call_log.answered_at
                and not any(t.get("role") == "user" for t in (transcript or []))):
            duration = 0  # never picked up

        from app.agent.runtime import reconcile_outcome

        outcome = reconcile_outcome(outcome, transcript) or outcome
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
            if outcome == "do_not_call":
                lead_values["do_not_call"] = True  # the contact asked not to be called again
            await db.execute(update(Lead).where(Lead.id == call_log.lead_id).values(**lead_values))

        already_counted = prev_outcome in ("meeting_booked", "qualified", "interested")  # a repeated report
        if call_log.campaign_id and not already_counted:
            inc: dict = {}
            if outcome == "meeting_booked":
                inc = {"total_booked": Campaign.total_booked + 1, "total_qualified": Campaign.total_qualified + 1}
            elif outcome in ("qualified", "interested"):
                inc = {"total_qualified": Campaign.total_qualified + 1}
            if inc:
                await db.execute(update(Campaign).where(Campaign.id == call_log.campaign_id).values(**inc))

        await db.commit()
        await db.refresh(call_log)
        await charge_call(db, call_log)
        await db.commit()
        log.info("call_outcome_updated", call_log_id=call_log_id, outcome=outcome, duration=duration,
                 credits=call_log.credits_charged)
        return call_log


async def analyze_and_store(call_log_id: str, force: bool = False) -> None:
    """Background: run post-call analysis and save summary/sentiment/extracted fields.

    force=True (the Re-analyze button) also lets the analyzer correct an outcome it set before."""
    try:
        await _analyze(call_log_id, force=force)
    finally:
        await emit_call_events(uuid.UUID(call_log_id))


async def _analyze(call_log_id: str, force: bool = False) -> None:
    from app.database import AsyncSessionLocal
    from app.services.llm import analyze_call

    async with AsyncSessionLocal() as db:
        call_log = await db.get(CallLog, uuid.UUID(call_log_id))
        if not call_log or not call_log.transcript:
            return
        from app.agent.runtime import NO_CONVERSATION_OUTCOMES, person_answered

        mislabeled = (call_log.outcome in (*NO_CONVERSATION_OUTCOMES, "failed")
                      and person_answered(call_log.transcript))
        if mislabeled:
            call_log.outcome = "completed"
            if call_log.status in ("no_answer", "failed"):
                call_log.status = "completed"
        agent = await db.get(Agent, call_log.agent_id) if call_log.agent_id else None
        result = await analyze_call(
            call_log.transcript,
            agent.extraction_fields if agent else None,
            agent.success_criteria if agent else "",
        )
        if not result:
            await db.commit()
            return
        call_log.summary = result.get("summary")
        call_log.sentiment = result.get("sentiment")
        call_log.extracted_data = {**(result.get("extracted") or {}), "_successful": result.get("successful")}
        # The analyzer's outcome only fills in when the agent didn't pick a specific one — or, when
        # re-analyzing on request, replaces anything but a hard result the agent confirmed.
        replaceable = call_log.outcome in (None, "completed", "failed") or (
            force and call_log.outcome not in ("meeting_booked", "transferred", "do_not_call"))
        if replaceable and result.get("outcome"):
            if call_log.duration_seconds or call_log.outcome != "failed":
                from app.agent.runtime import reconcile_outcome
                call_log.outcome = reconcile_outcome(result["outcome"], call_log.transcript)
        # A corrected outcome must reach the contact too: someone who talked is never left in a redial state,
        # and a "conversation" that was really a voicemail greeting gets the contact their retry.
        if call_log.lead_id and call_log.outcome not in ("no_answer", "voicemail", "failed"):
            from app.routers.campaigns import RETRY_STATUSES

            await db.execute(update(Lead).where(Lead.id == call_log.lead_id, Lead.status.in_(RETRY_STATUSES))
                             .values(status=call_log.outcome))
        elif call_log.lead_id and call_log.outcome == "voicemail":
            latest = (await db.execute(select(CallLog.id).where(CallLog.lead_id == call_log.lead_id)
                                       .order_by(CallLog.started_at.desc()).limit(1))).scalar_one_or_none()
            if latest == call_log.id:
                await db.execute(update(Lead).where(Lead.id == call_log.lead_id, Lead.status == "completed")
                                 .values(status="voicemail"))
        # Someone who asked not to be called again goes on the Do-Not-Call list.
        if call_log.outcome == "do_not_call" and call_log.lead_id:
            lead = await db.get(Lead, call_log.lead_id)
            if lead:
                lead.do_not_call = True
        await db.commit()
        log.info("call_analyzed", call_log_id=call_log_id, outcome=call_log.outcome)


async def fix_mislabeled_outcomes(limit: int = 500) -> int:
    """Repair: calls where the contact clearly talked but were labeled no answer / voicemail / failed."""
    from app.agent.runtime import NO_CONVERSATION_OUTCOMES, person_answered
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(CallLog.id, CallLog.transcript).where(
            CallLog.outcome.in_((*NO_CONVERSATION_OUTCOMES, "failed")), CallLog.transcript.isnot(None),
        ).order_by(CallLog.started_at.desc()).limit(limit))).all()
    ids = [str(r.id) for r in rows if person_answered(r.transcript)]
    for cid in ids:
        try:
            await _analyze(cid)
        except Exception as exc:
            log.warning("outcome_repair_failed", call_log_id=cid, error=str(exc))
    if ids:
        log.info("outcomes_repaired", count=len(ids))
    return len(ids)


async def emit_call_events(call_id: uuid.UUID) -> None:
    """call.completed for every finished phone call, plus meeting.booked when one was booked."""
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        # Claim the call so its events go out exactly once (re-analysis, late worker reports).
        claimed = await db.execute(update(CallLog).where(
            CallLog.id == call_id, CallLog.events_sent_at.is_(None), CallLog.call_type.in_(("outbound", "inbound")),
            CallLog.org_id.isnot(None),
        ).values(events_sent_at=datetime.now(timezone.utc)))
        await db.commit()
        if claimed.rowcount != 1:
            return
        call = await db.get(CallLog, call_id)
        lead = await db.get(Lead, call.lead_id) if call.lead_id else None
        agent = await db.get(Agent, call.agent_id) if call.agent_id else None
        campaign = await db.get(Campaign, call.campaign_id) if call.campaign_id else None
    data = {
        "call_id": str(call.id),
        "status": call.status,
        "outcome": call.outcome,
        "summary": public_summary(call.status, call.summary),
        "sentiment": call.sentiment,
        "duration_seconds": call.duration_seconds,
        "to_phone": call.to_phone,
        "contact": {"id": str(lead.id), "name": lead.name, "phone": lead.phone, "email": lead.email,
                    "company": lead.company} if lead else None,
        "agent_id": str(call.agent_id) if call.agent_id else None,
        "agent_name": agent.name if agent else None,
        "campaign_id": str(call.campaign_id) if call.campaign_id else None,
        "campaign_name": campaign.name if campaign else None,
        "meeting_time": call.agreed_meeting_time,
        "meeting_link": call.meeting_link,
        "prospect_email": call.prospect_email,
        "extracted_data": call.extracted_data or {},
        "started_at": call.started_at,
        "ended_at": call.ended_at,
    }
    await emit_event(call.org_id, "call.completed", data)
    from app.services.crm.sync import schedule_push
    schedule_push(call.org_id, data)
    if call.outcome == "meeting_booked":
        await emit_event(call.org_id, "meeting.booked", data)


# Singleton (name kept for existing imports)
call_service = CallService()
outbound_call_service = call_service


async def close_orphaned_calls(min_age_minutes: int = 2) -> int:
    """Close calls still marked live whose LiveKit room is gone — the worker's outcome report was lost (e.g. a
    restart right after hang-up). Otherwise the call shows "in progress" forever and holds a campaign slot."""
    from app.database import AsyncSessionLocal

    if not settings.livekit_ready:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=min_age_minutes)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(CallLog).where(
            CallLog.status.in_(("initiated", "ringing", "connected")), CallLog.ended_at.is_(None),
            CallLog.started_at < cutoff,
        ).limit(200))).scalars().all()
    if not rows:
        return 0
    lk = _lk()
    try:
        live = {r.name for r in (await lk.room.list_rooms(api.ListRoomsRequest())).rooms}
    finally:
        await lk.aclose()
    closed = 0
    for call in rows:
        if call.livekit_room_name and call.livekit_room_name in live:
            continue
        # Unknown talk time: end it at pickup so nobody is billed for time we can't account for.
        start = call.answered_at or call.started_at
        if start and start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        async with AsyncSessionLocal() as db:
            await outbound_call_service.update_call_outcome(
                call_log_id=str(call.id), outcome="completed" if call.answered_at else "no_answer",
                transcript=call.transcript, meeting_link=None, qualification_score=None, db=db,
                ended_at=start.timestamp() if start else None,
            )
        closed += 1
        log.info("orphaned_call_closed", call_log_id=str(call.id), room=call.livekit_room_name)
    return closed


def start_orphan_sweeper(interval: float = 60.0) -> asyncio.Task:
    async def _loop() -> None:
        while True:
            try:
                await close_orphaned_calls()
            except Exception as exc:
                log.warning("orphan_sweep_failed", error=str(exc)[:200])
            await asyncio.sleep(interval)

    return asyncio.create_task(_loop())
