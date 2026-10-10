"""
Pounce — voice agent tool functions.

Built as closures over CallState — exactly the same pattern as
carrier_sales.py (Hevox-Prod) but using @llm.ai_callable.

5 tools:
  1. load_lead_context      — auto-called at session start
  2. log_qualification_answer — fire-and-forget Q logging
  3. qualify_lead           — set score + completion gate
  4. book_meeting           — fetch Cal.com slots, return options
  5. end_call               — update DB, close session
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx
import structlog
from livekit.agents import llm

from app.agent.state import CallState
from app.config import settings

if TYPE_CHECKING:
    pass

log = structlog.get_logger(__name__)

# ── Question → state slot mapping ─────────────────────────────────────────────
_Q_SLOT_MAP = {
    "team_size": "q_team_size",
    "current_process": "q_current_process",
    "decision_maker": "q_decision_maker",
}


def build_pounce_tools(state: CallState, session=None) -> list:
    """
    Build the 5 Pounce tool callables as closures over `state`.

    Parameters
    ----------
    state   : CallState — mutable call state shared across all tools
    session : AgentSession (optional) — passed in for future session control
    """

    # ── 1. load_lead_context ──────────────────────────────────────────────────

    @llm.ai_callable(
        description=(
            "Load the lead's context at the very start of the call. "
            "MUST be the first tool called. Returns lead info as a summary string."
        )
    )
    async def load_lead_context() -> str:
        state.lead_loaded = True
        log.info("load_lead_context", lead_id=state.lead_id, name=state.name)
        return (
            f"Lead loaded — Name: {state.name}, "
            f"Company: {state.company}, "
            f"Role: {state.role or 'unknown'}, "
            f"Phone: {state.phone}. "
            f"Gate 1 (lead_loaded) is now TRUE. Proceed with the intro."
        )

    # ── 2. log_qualification_answer ───────────────────────────────────────────

    @llm.ai_callable(
        description=(
            "Log a qualification answer. Call immediately after the prospect "
            "answers each question. Fire-and-forget — returns 'Got it.' instantly."
        )
    )
    async def log_qualification_answer(
        question: str,
        answer: str,
    ) -> str:
        """
        Args:
            question: One of: team_size | current_process | decision_maker
            answer: Prospect's answer verbatim or a concise paraphrase
        """
        slot = _Q_SLOT_MAP.get(question)
        if slot:
            setattr(state, slot, answer)
        else:
            log.warning("log_qualification_answer_unknown_question", question=question)

        asyncio.create_task(_fire_log_answer(state, question, answer))
        return "Got it."

    # ── 3. qualify_lead ───────────────────────────────────────────────────────

    @llm.ai_callable(
        description=(
            "Compute qualification after all 3 questions are answered. "
            "Sets qualification_complete gate. Requires lead_loaded first."
        )
    )
    async def qualify_lead(
        score: int,
        summary: str,
    ) -> str:
        """
        Args:
            score: Integer 0-10 based on the scoring rubric in the system prompt
            summary: 1-sentence summary of why the lead is or isn't a fit
        """
        if not state.lead_loaded:
            return "Cannot qualify: load_lead_context has not been called yet."

        state.qualification_score = score
        state.qualification_complete = True

        log.info(
            "qualify_lead",
            lead_id=state.lead_id,
            score=score,
            summary=summary,
        )

        if score >= 5:
            return (
                f"Qualified! Score: {score}/10. {summary} "
                f"Gate 2 (qualification_complete) is TRUE. Proceed to book_meeting."
            )
        else:
            return (
                f"Not qualified. Score: {score}/10. {summary} "
                f"Gate 2 (qualification_complete) is TRUE. Proceed to end_call with outcome=not_qualified."
            )

    # ── 4. book_meeting ───────────────────────────────────────────────────────

    @llm.ai_callable(
        description=(
            "Fetch available meeting slots and return 2 options to the prospect. "
            "Gate-protected: requires qualification_complete AND score >= 5. "
            "Returns time options as a string — does NOT book yet. "
            "Booking is confirmed when the prospect picks a slot."
        )
    )
    async def book_meeting(
        preferred_time: str,
    ) -> str:
        """
        Args:
            preferred_time: Prospect's stated preference (e.g. 'tomorrow afternoon', 'Monday morning')
        """
        ok, reason = state.can_book_meeting()
        if not ok:
            return f"Cannot book meeting: {reason}."

        slots = await _fetch_calcom_slots(preferred_time)

        # Store slots in state (NEVER returned directly to LLM — only formatted labels)
        state._available_slots = slots

        if not slots:
            return (
                "I wasn't able to pull up specific times right now. "
                "Let me have our team reach out to you directly to schedule. "
                "What's the best email for you?"
            )

        # Return only human-readable slot labels — never raw API data
        option_a = slots[0]["label"]
        option_b = slots[1]["label"] if len(slots) > 1 else None

        if option_b:
            return (
                f"Great, I have two slots available: Option A is {option_a}, "
                f"and Option B is {option_b}. Which works better for you?"
            )
        return f"I have {option_a} available. Does that work for you?"

    # ── 5. end_call ───────────────────────────────────────────────────────────

    @llm.ai_callable(
        description=(
            "End the call gracefully and update the database. "
            "ALWAYS call this — it is required to close out every call."
        )
    )
    async def end_call(
        outcome: str,
    ) -> str:
        """
        Args:
            outcome: One of: qualified | not_qualified | meeting_booked | no_answer | failed
        """
        log.info("end_call", lead_id=state.lead_id, outcome=outcome)
        asyncio.create_task(_fire_end_call(state, outcome))

        farewells = {
            "meeting_booked": (
                f"Awesome, you're all set, {state.name}! "
                f"You'll get a calendar invite shortly. Looking forward to chatting — have a great day!"
            ),
            "qualified": (
                f"Great talking with you, {state.name}. "
                f"Our team will follow up to lock in a time. Have a good one!"
            ),
            "not_qualified": (
                f"Thanks for your time, {state.name}. "
                f"I'll keep you in mind as we grow — take care!"
            ),
            "no_answer": (
                "Thanks for your time. We'll be in touch. Have a great day!"
            ),
            "failed": "Thank you for your time. Goodbye.",
        }
        return farewells.get(outcome, f"Thank you, {state.name}. Take care!")

    return [
        load_lead_context,
        log_qualification_answer,
        qualify_lead,
        book_meeting,
        end_call,
    ]


# ── Background tasks (fire-and-forget) ───────────────────────────────────────


async def _fire_log_answer(state: CallState, question: str, answer: str) -> None:
    """Background: post qualification answer to backend API."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.patch(
                f"{settings.api_base_url}/api/leads/{state.lead_id}",
                json={"question": question, "answer": answer},
            )
    except Exception as exc:
        log.warning("fire_log_answer_failed", error=str(exc), lead_id=state.lead_id)


async def _fire_end_call(state: CallState, outcome: str) -> None:
    """Background: update call log and lead status in the database."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{settings.api_base_url}/api/webhook/calls/{state.call_log_id}/outcome",
                json={
                    "outcome": outcome,
                    "qualification_score": state.qualification_score,
                    "q_team_size": state.q_team_size,
                    "q_current_process": state.q_current_process,
                    "q_decision_maker": state.q_decision_maker,
                    "agreed_meeting_time": state.agreed_meeting_time,
                    "meeting_link": state.meeting_link,
                },
            )
    except Exception as exc:
        log.warning("fire_end_call_failed", error=str(exc), call_log_id=state.call_log_id)


async def _fetch_calcom_slots(preferred_time: str) -> list[dict]:
    """
    Fetch available slots from Cal.com.
    Falls back to mock slots if CALCOM_API_KEY is not set.
    Returns list of {"label": str, "start": ISO str, "slot_id": str}
    """
    if not settings.calcom_api_key or not settings.calcom_event_type_id:
        log.info("calcom_not_configured_using_mock_slots")
        return _mock_slots()

    try:
        import datetime

        now = datetime.datetime.now(datetime.timezone.utc)
        start_time = now.isoformat()
        end_time = (now + datetime.timedelta(days=7)).isoformat()

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://api.cal.com/v1/slots",
                params={
                    "apiKey": settings.calcom_api_key,
                    "eventTypeId": settings.calcom_event_type_id,
                    "startTime": start_time,
                    "endTime": end_time,
                    "timeZone": "America/Chicago",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        slots_raw = []
        for date_key, times in (data.get("slots") or {}).items():
            for slot in times:
                slots_raw.append(slot)
                if len(slots_raw) >= 4:
                    break
            if len(slots_raw) >= 4:
                break

        if not slots_raw:
            return _mock_slots()

        # Format into human-readable labels
        formatted = []
        for s in slots_raw[:2]:
            start_str = s.get("time", "")
            try:
                dt = datetime.datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                label = dt.strftime("%A, %B %-d at %-I:%M %p CT")
            except Exception:
                label = start_str
            formatted.append({"label": label, "start": start_str, "slot_id": s.get("time", "")})

        return formatted

    except Exception as exc:
        log.warning("calcom_fetch_failed", error=str(exc))
        return _mock_slots()


def _mock_slots() -> list[dict]:
    """Fallback mock slots for hackathon demo."""
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)
    slot_a = now + datetime.timedelta(days=1, hours=10)
    slot_b = now + datetime.timedelta(days=2, hours=14)

    return [
        {
            "label": slot_a.strftime("%A, %B %-d at %-I:%M %p CT"),
            "start": slot_a.isoformat(),
            "slot_id": slot_a.isoformat(),
        },
        {
            "label": slot_b.strftime("%A, %B %-d at %-I:%M %p CT"),
            "start": slot_b.isoformat(),
            "slot_id": slot_b.isoformat(),
        },
    ]
