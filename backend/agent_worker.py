"""
Pounce — LiveKit Agents 1.6.x worker process.

Run as a separate process from FastAPI:
    python agent_worker.py dev      # dev mode (auto-reconnect)
    python agent_worker.py start    # production

The worker joins every room it is dispatched to. Calls started from the
dashboard carry an agent config (prompt, voice, tools) in the room metadata
and run as a configurable agent; anything else runs the original Paul SDR.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import structlog
from dotenv import load_dotenv

load_dotenv()  # must happen before any app imports

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    WorkerOptions,
    cli,
    function_tool,
)
from livekit.plugins import cartesia, deepgram, openai, silero

from app.agent.prompt import build_system_prompt
from app.agent.voices import DEFAULT_VOICE_ID
from app.agent.state import CallState
from app.config import settings

log = structlog.get_logger(__name__)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(message)s",
)


# ── Deepgram keyterm boosting for SDR calls (nova-3 uses keyterms, not keywords)
_FREIGHT_KEYTERMS = [
    "Hemut", "freight broker", "TMS", "dispatcher", "load board", "carrier",
    "brokerage", "logistics", "shipment", "capacity", "lane", "rate",
    "demo", "meeting",
]

# House voice — "Blake - Helpful Agent" (Cartesia Sonic-3), matching hevox-prod's
# inbound carrier sales II agent.
_BLAKE_VOICE_ID = "a167e0f3-df7e-4d52-a9c3-f949145efdab"

try:
    from livekit.agents.voice.transcription.text_transforms import replace as _lk_replace
except Exception:
    _lk_replace = None

# Backchannel allow-list: single/multi-word acknowledgments that should NEVER
# be treated as full barge-in turns. When detected, Paul is instructed to
# continue rather than starting a new response from scratch.
_BACKCHANNELS = frozenset({
    "yeah", "yep", "yes", "yup", "sure", "right", "okay", "ok",
    "go ahead", "go on", "please", "i see", "got it", "uh huh",
    "mm hmm", "mmhmm", "mhm", "mm-hmm", "uh-huh", "sure thing",
    "sounds good", "makes sense", "of course", "for sure", "alright",
    "yeah sure", "yes please", "sure go ahead", "yeah go ahead",
    "please continue", "keep going", "absolutely", "definitely",
})


# ── Agent class ───────────────────────────────────────────────────────────────

class PounceAgent(Agent):
    """
    Paul — Pounce outbound SDR agent.
    State is stored per-instance so every call has isolated state.
    """

    def __init__(self, state: CallState):
        super().__init__(instructions=build_system_prompt(state))
        self._state = state
        self._t0: float | None = None        # set in entrypoint (call start)
        self._hangup = None                   # set in entrypoint; ends the SIP call
        self._dictation_mode = False          # True = extended endpointing for email/date

    async def _say_filler(self, text: str) -> None:
        """Hard-coded hold-line straight to TTS — fires before slow API calls."""
        try:
            self.session.say(text, allow_interruptions=True)
        except Exception as exc:
            log.debug("filler_say_failed", error=str(exc))

    async def stt_node(self, audio, model_settings):
        """Extend Deepgram endpointing silence window when expecting email/date input."""
        if self._dictation_mode:
            try:
                import dataclasses as _dc
                if _dc.is_dataclass(model_settings):
                    model_settings = _dc.replace(model_settings, endpointing=1200)
            except Exception:
                pass
        async for event in super().stt_node(audio, model_settings):
            yield event

    def _record_tool(self, name: str, args: dict | None = None, output=None) -> None:
        """Append a tool-call marker to the transcript so the Runs view shows
        exactly which tool fired, when, with what INPUT, and the OUTPUT."""
        import time as _t
        ts = round((_t.monotonic() - self._t0), 2) if self._t0 else 0.0
        self._state.transcript.append({
            "role": "tool",
            "tool": name,
            "args": args or {},
            "result": {"output": output, "success": True} if output is not None
                      else {"success": True},
            "ts": ts,
        })
        log.info("tool_call", tool=name, args=args, lead_id=self._state.lead_id)

    # ── Tool 1: load_lead_context ─────────────────────────────────────────────

    @function_tool
    async def load_lead_context(self) -> str:
        """
        Load the lead's context at the very start of the call.
        MUST be the first tool called. Returns lead info as a summary string.
        """
        self._state.lead_loaded = True
        self._record_tool("load_lead_context", {}, output={"name": self._state.name, "company": self._state.company})
        return (
            f"Lead loaded — Name: {self._state.name}, "
            f"Company: {self._state.company}, "
            f"Role: {self._state.role or 'unknown'}, "
            f"Phone: {self._state.phone}. "
            f"Gate 1 (lead_loaded) is now TRUE. Proceed with the intro."
        )

    # ── Tool 2: log_qualification_answer ──────────────────────────────────────

    @function_tool
    async def log_qualification_answer(self, question: str, answer: str) -> str:
        """
        Log a qualification answer immediately after the prospect responds.
        Fire-and-forget — returns 'Got it.' instantly.
        question: One of team_size | current_process | decision_maker
        answer: Prospect's answer verbatim or a concise paraphrase
        """
        import asyncio, httpx as _httpx

        _slot_map = {
            "team_size": "q_team_size",
            "current_process": "q_current_process",
            "decision_maker": "q_decision_maker",
        }
        slot = _slot_map.get(question)
        if slot:
            setattr(self._state, slot, answer)
        else:
            log.warning("unknown_qual_question", question=question)
        self._record_tool("log_qualification_answer", {"question": question, "answer": answer})

        async def _fire() -> None:
            try:
                async with _httpx.AsyncClient(timeout=5.0) as client:
                    await client.patch(
                        f"{settings.api_base_url}/internal/leads/{self._state.lead_id}",
                        json={"question": question, "answer": answer},
                    )
            except Exception as exc:
                log.warning("log_answer_fire_failed", error=str(exc))

        asyncio.create_task(_fire())
        return "Got it."

    # ── Tool 3: qualify_lead ──────────────────────────────────────────────────

    @function_tool
    async def qualify_lead(self, score: int, summary: str) -> str:
        """
        Compute qualification after all 3 questions are answered.
        Sets qualification_complete gate. Requires lead_loaded first.
        score: Integer 0-10 based on the scoring rubric in the system prompt
        summary: 1-sentence summary of why the lead is or isn't a fit
        """
        if not self._state.lead_loaded:
            return "Cannot qualify: load_lead_context has not been called yet."

        self._state.qualification_score = score
        self._state.qualification_complete = True
        self._record_tool("qualify_lead", {"score": score, "summary": summary}, output={"qualified": score >= 5})

        if score >= 5:
            return (
                f"Qualified! Score: {score}/10. {summary} "
                f"Gate 2 (qualification_complete) is TRUE. Proceed to book_meeting."
            )
        return (
            f"Not qualified. Score: {score}/10. {summary} "
            f"Gate 2 TRUE. Proceed to end_call with outcome=not_qualified."
        )

    # ── Tool 4: book_meeting ──────────────────────────────────────────────────

    @function_tool
    async def book_meeting(self, preferred_time: str = "", preferred_date: str = "") -> str:
        """
        Fetch available demo slots AROUND the date the prospect asked for.
        Gate-protected: requires qualification_complete AND score >= 5.
        preferred_time: their spoken preference, e.g. 'afternoon', 'July 2nd'.
        preferred_date: that date as YYYY-MM-DD (convert it yourself). Slots are
            fetched starting from this date, so honor what they asked for.
        """
        ok, reason = self._state.can_book_meeting()
        if not ok:
            return f"Cannot book meeting: {reason}."

        await self._say_filler("One sec, let me check what's open around then…")
        slots = await _fetch_calcom_slots(preferred_time, preferred_date)
        self._state._available_slots = slots
        self._record_tool(
            "book_meeting",
            {"preferred_time": preferred_time, "preferred_date": preferred_date},
            output={"slots": [s.get("label") for s in slots]},
        )

        if not slots:
            self._dictation_mode = False
            return (
                f"Hmm, nothing's opening up around {preferred_time or 'then'}. "
                "Want me to check a different day, or should I have the team email you?"
            )

        # Enter dictation mode — prospect needs to spell out email or confirm a date.
        self._dictation_mode = True

        # If we have a real email on file, fold it into the ask so we don't ask blind.
        email_hint = (
            f" I've got your email as {self._state.email}—still good?"
            if "@" in (self._state.email or "") else
            " What's the best email for the invite?"
        )
        option_a = slots[0]["label"]
        option_b = slots[1]["label"] if len(slots) > 1 else None
        if option_b:
            return (
                f"Okay, around then I've got {option_a} or {option_b}. "
                f"Which works better?{email_hint} Then I'll lock it in with confirm_meeting."
            )
        return f"Okay, I've got {option_a}. Work for you?{email_hint}"

    # ── Tool 5: confirm_meeting ───────────────────────────────────────────────

    @function_tool
    async def confirm_meeting(self, slot_choice: str, email: str) -> str:
        """
        Confirm and BOOK the demo once the prospect picks a slot and gives email.
        Creates the calendar booking and returns the confirmation.
        slot_choice: 'A' or 'B', or the spoken time they chose
        email: the prospect's email for the calendar invite
        """
        ok, reason = self._state.can_book_meeting()
        if not ok:
            return f"Cannot book meeting: {reason}."

        # Fall back to a real on-file email if the agent didn't capture one.
        if "@" not in (email or "") and "@" in (self._state.email or ""):
            email = self._state.email

        slots = self._state._available_slots or []
        chosen = None
        c = (slot_choice or "").strip().lower()
        if c in ("a", "option a", "first") and slots:
            chosen = slots[0]
        elif c in ("b", "option b", "second") and len(slots) > 1:
            chosen = slots[1]
        else:
            for s in slots:
                if c and c in s.get("label", "").lower():
                    chosen = s; break
        if not chosen and slots:
            chosen = slots[0]

        start = chosen.get("start") if chosen else None
        label = chosen.get("label") if chosen else "the time we discussed"

        await self._say_filler("Perfect, booking that now — one second…")
        link = await _create_calcom_booking(
            start=start, email=email, name=self._state.name, company=self._state.company,
        )

        self._dictation_mode = False
        self._state.prospect_email = email
        self._state.agreed_meeting_time = label
        self._state.meeting_link = link or ""
        self._state.meeting_booked = True
        self._record_tool("confirm_meeting", {"slot_choice": slot_choice, "email": email}, output={"booked": label, "link": link})

        link_line = f" The invite is on its way to {email}." if link else \
                    f" Our team will email the invite to {email}."
        return (
            f"Booked you for {label}.{link_line} Anything else before I let you go? "
            f"Then call end_call with outcome=meeting_booked."
        )

    # ── Tool 6: end_call ──────────────────────────────────────────────────────

    @function_tool
    async def end_call(self, outcome: str) -> str:
        """
        End the call gracefully and update the database.
        ALWAYS call this — it is required to close out every call.
        outcome: One of qualified | not_qualified | meeting_booked | no_answer | failed
        """
        self._record_tool("end_call", {"outcome": outcome})

        # Persist the result, then hang up the SIP line after the goodbye plays.
        asyncio.create_task(_post_call_outcome(self._state, outcome))
        if self._hangup:
            self._hangup()   # schedules the actual disconnect (see entrypoint)

        farewells = {
            "meeting_booked": (
                f"Awesome, you're all set, {self._state.name}! "
                f"You'll get a calendar invite shortly. Looking forward to chatting — have a great day!"
            ),
            "qualified": (
                f"Great talking with you, {self._state.name}. "
                f"Our team will follow up to lock in a time. Have a good one!"
            ),
            "not_qualified": (
                f"Thanks for your time, {self._state.name}. "
                f"I'll keep you in mind as we grow — take care!"
            ),
            "no_answer": "Thanks for your time. We'll be in touch. Have a great day!",
            "failed": "Thank you for your time. Goodbye.",
        }
        return farewells.get(outcome, f"Thank you, {self._state.name}. Take care!")


# ── Call outcome finalization ─────────────────────────────────────────────────

async def _push_live_event(call_log_id: str, event: dict) -> None:
    """Fire-and-forget: send a live event to the SSE broadcaster via HTTP."""
    if not call_log_id:
        return
    import httpx as _httpx
    try:
        async with _httpx.AsyncClient(timeout=2.0) as client:
            await client.post(
                f"{settings.api_base_url}/internal/calls/{call_log_id}/live-event",
                json=event,
            )
    except Exception as exc:
        log.debug("live_push_failed", error=str(exc))


async def _post_call_outcome(state, outcome: str) -> None:
    """
    Idempotently POST the call outcome + captured transcript to the webhook.
    Called from end_call (normal path) AND from the shutdown callback (caller
    hung up before end_call). The outcome_posted flag prevents double writes.
    """
    if state.outcome_posted or not state.call_log_id:
        return
    state.outcome_posted = True

    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{settings.api_base_url}/internal/calls/{state.call_log_id}/outcome",
                json={
                    "outcome": outcome,
                    "qualification_score": state.qualification_score,
                    "q_team_size": state.q_team_size,
                    "q_current_process": state.q_current_process,
                    "q_decision_maker": state.q_decision_maker,
                    "agreed_meeting_time": state.agreed_meeting_time,
                    "meeting_link": state.meeting_link,
                    "prospect_email": state.prospect_email,
                    "transcript": state.transcript,
                },
            )
        log.info("call_outcome_posted", call_log_id=state.call_log_id,
                 outcome=outcome, turns=len(state.transcript))
    except Exception as exc:
        # Allow the shutdown fallback to retry — losing the transcript is worse
        # than a rare double POST (the webhook upsert is idempotent on call_log).
        state.outcome_posted = False
        log.warning("post_call_outcome_failed", error=str(exc), call_log_id=state.call_log_id)


def _derive_outcome(state) -> str:
    """Best-effort outcome when the call ends without an explicit end_call."""
    if state.meeting_booked:
        return "meeting_booked"
    if state.qualification_complete:
        return "qualified" if (state.qualification_score or 0) >= 5 else "not_qualified"
    if not state.transcript:
        return "no_answer"
    return "failed"


# ── Cal.com booking creator ───────────────────────────────────────────────────

async def _create_calcom_booking(start, email: str, name: str, company: str) -> str:
    """
    Create a real Cal.com booking for `start` (ISO time) with the prospect's
    email. Returns a meeting link, or "" on failure. Falls back to a placeholder
    confirmation link when Cal.com isn't configured so the demo still completes.
    """
    if not start:
        return ""
    if not settings.calcom_api_key or not settings.calcom_event_type_id:
        log.info("calcom_not_configured_booking_mock", email=email)
        return f"https://cal.com/hemut/demo?attendee={email}"

    import httpx
    payload = {
        "start": start,
        "eventTypeId": int(settings.calcom_event_type_id),
        "attendee": {
            "name": name or "Prospect",
            "email": email,
            "timeZone": "America/Chicago",
            "language": "en",
        },
        "metadata": {"source": "pounce", "company": (company or "")[:48]},
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.cal.com/v2/bookings",
                headers={
                    "Authorization": f"Bearer {settings.calcom_api_key}",
                    "cal-api-version": "2024-08-13",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = (resp.json() or {}).get("data") or {}
        uid = data.get("uid") or data.get("id")
        link = f"https://cal.com/booking/{uid}" if uid else ""
        log.info("calcom_booking_created", email=email, uid=uid)
        return link or f"https://cal.com/hemut/demo?attendee={email}"
    except Exception as exc:
        log.warning("calcom_booking_failed", error=str(exc), email=email)
        return f"https://cal.com/hemut/demo?attendee={email}"


# ── Cal.com slot fetcher ──────────────────────────────────────────────────────

async def _fetch_calcom_slots(preferred_time: str, preferred_date: str = "") -> list[dict]:
    """
    Fetch available Cal.com slots (API v2) starting from the date the prospect
    asked for, or fall back to mock. Returns up to 2 options, spread across days
    so we don't only ever offer the first day's earliest two times.
    """
    import datetime, httpx

    if not settings.calcom_api_key or not settings.calcom_event_type_id:
        log.info("calcom_not_configured_using_mock")
        return _mock_slots()

    now = datetime.datetime.now(datetime.timezone.utc)
    # Honor the requested date when it parses and isn't in the past.
    start_date = now.date()
    try:
        if preferred_date:
            pd = datetime.date.fromisoformat(preferred_date.strip()[:10])
            # LLM sometimes sends the wrong year (e.g. 2024 instead of 2026).
            # Fix: if the date is in the past, bump to current year, then next year.
            if pd < now.date():
                pd = pd.replace(year=now.year)
            if pd < now.date():
                pd = pd.replace(year=now.year + 1)
            start_date = pd
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://api.cal.com/v2/slots",
                headers={
                    "Authorization": f"Bearer {settings.calcom_api_key}",
                    "cal-api-version": "2024-09-04",
                },
                params={
                    "eventTypeId": settings.calcom_event_type_id,
                    "start": start_date.isoformat(),
                    "end": (start_date + datetime.timedelta(days=10)).isoformat(),
                    "timeZone": "America/Chicago",
                },
            )
            resp.raise_for_status()
            data = (resp.json() or {}).get("data") or {}

        # data is { "YYYY-MM-DD": [ {"start": ISO}, ... ], ... }. Offer a midday
        # slot from the requested day, then one from a later day, for variety.
        days = sorted(data.keys())
        if not days:
            return _mock_slots()

        def _pick(day_slots: list) -> str | None:
            starts = [(s.get("start") if isinstance(s, dict) else s) for s in day_slots]
            starts = [s for s in starts if s]
            if not starts:
                return None
            return starts[len(starts) // 2]  # roughly midday, not the 6am slot

        picks: list[str] = []
        first = _pick(data[days[0]])
        if first:
            picks.append(first)
        for d in days[1:]:
            nxt = _pick(data[d])
            if nxt:
                picks.append(nxt); break
        if len(picks) < 2:  # only one day had slots — take a second from it
            for s in data[days[0]]:
                val = s.get("start") if isinstance(s, dict) else s
                if val and val not in picks:
                    picks.append(val)
                    if len(picks) >= 2:
                        break
        if not picks:
            return _mock_slots()

        formatted = []
        for start_str in picks[:2]:
            try:
                dt = datetime.datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                label = dt.strftime("%A, %B %-d at %-I:%M %p CT")
            except Exception:
                label = start_str
            formatted.append({"label": label, "start": start_str, "slot_id": start_str})
        return formatted
    except Exception as exc:
        log.warning("calcom_fetch_failed", error=str(exc))
        return _mock_slots()


def _mock_slots() -> list[dict]:
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    slot_a = now + datetime.timedelta(days=1, hours=10)
    slot_b = now + datetime.timedelta(days=2, hours=14)
    return [
        {"label": slot_a.strftime("%A, %B %-d at %-I:%M %p CT"), "start": slot_a.isoformat(), "slot_id": slot_a.isoformat()},
        {"label": slot_b.strftime("%A, %B %-d at %-I:%M %p CT"), "start": slot_b.isoformat(), "slot_id": slot_b.isoformat()},
    ]


# ── Continuous call-center background ambience ────────────────────────────────

async def _play_continuous_bg(room, control: dict) -> None:
    """
    Publish a looping call-center ambience track (matches hevox-prod). Runs as
    its own LiveKit audio track — always on, independent of TTS — so the call
    sounds like it's coming from a live sales floor. `control` is shared so the
    track can be unpublished and the loop cancelled on shutdown.
    """
    import wave
    from pathlib import Path

    import numpy as np
    from livekit import rtc

    bg_path = Path(__file__).parent / "assets" / "call-center-bg.wav"
    if not bg_path.exists():
        log.warning("agent.no_bg_audio_file", path=str(bg_path))
        return

    with wave.open(str(bg_path), "rb") as wf:
        src_rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
        samples = np.frombuffer(frames, dtype=np.int16)

    # Resample to 24kHz to match TTS output rate (SIP bridge mixes all tracks).
    target_rate = 24000
    if src_rate != target_rate:
        ratio = target_rate / src_rate
        new_len = int(len(samples) * ratio)
        indices = np.clip((np.arange(new_len) / ratio).astype(int), 0, len(samples) - 1)
        samples = samples[indices]

    # Volume — clearly audible call-center hum without masking the agent.
    volume = 0.3
    samples = (samples.astype(np.float32) * volume).astype(np.int16)

    audio_source = rtc.AudioSource(target_rate, 1)
    track = rtc.LocalAudioTrack.create_audio_track("bg-audio", audio_source)
    await room.local_participant.publish_track(track, rtc.TrackPublishOptions())
    control["track"] = track
    log.info("agent.bg_track_published", samples=len(samples))

    chunk_duration = 0.04
    chunk_samples = int(target_rate * chunk_duration)
    pos, total = 0, len(samples)
    try:
        while True:
            end = pos + chunk_samples
            if end > total:
                chunk = np.concatenate([samples[pos:], samples[:end - total]])
                pos = end - total
            else:
                chunk = samples[pos:end]
                pos = end
            await audio_source.capture_frame(rtc.AudioFrame(
                data=chunk.tobytes(),
                sample_rate=target_rate,
                num_channels=1,
                samples_per_channel=chunk_samples,
            ))
            await asyncio.sleep(chunk_duration * 0.9)
    except asyncio.CancelledError:
        log.info("agent.bg_track_loop_cancelled")
        raise


# ── Configurable agents (built in the dashboard) ──────────────────────────────
#
# When room metadata carries an "agent" config (every call started from the
# dashboard), the worker builds the agent from that config: prompt, knowledge
# base, voice, model and the enabled actions. Rooms without one fall back to
# the original Paul SDR above.

_END_OUTCOMES = (
    "meeting_booked", "qualified", "not_qualified", "interested", "not_interested",
    "callback", "transferred", "voicemail", "no_answer", "completed", "failed",
)


class _CallRun:
    """Per-call mutable state for a configurable agent."""

    def __init__(self, call_log_id: str, call_type: str) -> None:
        self.call_log_id = call_log_id
        self.call_type = call_type
        self.transcript: list[dict] = []
        self.outcome: str | None = None
        self.outcome_posted = False
        self.slots: list[dict] = []
        self.meeting_link = ""
        self.meeting_time = ""
        self.email = ""
        self.t0 = 0.0
        self.lat: dict[str, list[float]] = {"eou": [], "llm": [], "tts": []}

    def latency_summary(self) -> dict | None:
        avg = lambda xs: round(sum(xs) / len(xs), 3) if xs else None
        eou, llm, tts = avg(self.lat["eou"]), avg(self.lat["llm"]), avg(self.lat["tts"])
        if eou is None and llm is None:
            return None
        return {
            "turns": len(self.lat["llm"]),
            "avg_eou": eou,
            "avg_llm_ttft": llm,
            "avg_tts_ttfb": tts,
            "avg_response": round(sum(v for v in (eou, llm, tts) if v), 3),
        }


async def _post_run_outcome(run: _CallRun, outcome: str) -> None:
    if run.outcome_posted or not run.call_log_id:
        return
    run.outcome_posted = True
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{settings.api_base_url}/internal/calls/{run.call_log_id}/outcome",
                json={
                    "outcome": outcome,
                    "agreed_meeting_time": run.meeting_time,
                    "meeting_link": run.meeting_link or None,
                    "prospect_email": run.email,
                    "transcript": run.transcript,
                    "metrics": run.latency_summary(),
                },
            )
        log.info("call_outcome_posted", call_log_id=run.call_log_id, outcome=outcome)
    except Exception as exc:
        run.outcome_posted = False
        log.warning("post_call_outcome_failed", error=str(exc), call_log_id=run.call_log_id)


async def _fetch_agent_config(agent_id: str) -> dict | None:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(f"{settings.api_base_url}/internal/agents/{agent_id}/runtime")
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        log.warning("agent_config_fetch_failed", agent_id=agent_id, error=str(exc))
        return None


async def _delete_room(room_name: str) -> None:
    from livekit import api as _lkapi
    lk = _lkapi.LiveKitAPI(
        url=settings.livekit_url, api_key=settings.livekit_api_key, api_secret=settings.livekit_api_secret,
    )
    try:
        await lk.room.delete_room(_lkapi.DeleteRoomRequest(room=room_name))
        log.info("call_hung_up", room=room_name)
    except Exception as exc:
        log.warning("hangup_failed", error=str(exc))
    finally:
        await lk.aclose()


def _build_tools(cfg: dict, run: _CallRun, ctx: JobContext, session_ref: dict,
                 cfg_vars: dict | None = None) -> list:
    """Function tools for a configurable agent, based on what it has enabled."""
    import time as _t
    from app.services import calendar as _cal

    def _record(name: str, args: dict, output=None) -> None:
        run.transcript.append({
            "role": "tool", "tool": name, "args": args,
            "result": {"output": output, "success": True},
            "ts": round(_t.monotonic() - run.t0, 2) if run.t0 else 0.0,
        })

    def _hangup(delay: float) -> None:
        async def _go() -> None:
            await asyncio.sleep(delay)
            await _delete_room(ctx.room.name)
        asyncio.create_task(_go())

    async def end_call(outcome: str) -> str:
        """Hang up the call. Call this only AFTER you've said goodbye.

        Args:
            outcome: The result of the call. One of meeting_booked, qualified, not_qualified,
                interested, not_interested, callback, transferred, voicemail, no_answer, completed.
        """
        outcome = outcome if outcome in _END_OUTCOMES else "completed"
        if outcome == "meeting_booked" and not run.meeting_time:
            return "Not ended: no meeting is booked yet. Finish booking first, or pick another outcome."
        run.outcome = outcome
        _record("end_call", {"outcome": outcome})
        asyncio.create_task(_post_run_outcome(run, outcome))
        _hangup(4.0)
        return "Call is ending. Do not say anything else."

    tools = [function_tool(end_call)]

    if cfg.get("enable_booking"):
        async def check_availability(preferred_date: str = "") -> str:
            """Look up open appointment slots. Only ever offer the slots this returns.

            Args:
                preferred_date: The day the contact prefers, as YYYY-MM-DD. Empty for the soonest.
            """
            session = session_ref.get("session")
            if session:
                session.say("One sec, let me check the calendar.", allow_interruptions=True)
            found = await _cal.fetch_slots(preferred_date, cfg.get("calcom_event_type_id"))
            run.slots = _cal.remember_slots(run.slots, found)
            _record("check_availability", {"preferred_date": preferred_date},
                    {"slots": [s["label"] for s in found]})
            if not found:
                return "Nothing is open around then. Offer to check another day."
            return "Open slots: " + " or ".join(s["label"] for s in found)

        async def book_appointment(slot: str, email: str) -> str:
            """Book one of the slots from check_availability. Confirm the email spelling first.

            Args:
                slot: The exact label of the slot they chose, as returned by check_availability.
                email: The contact's email exactly as they said it. Never guess it.
            """
            if not run.slots:
                return "No slots offered yet. Call check_availability first."
            chosen = _cal.pick_slot(run.slots, slot)
            if not chosen:
                return ("Which slot? Offered: " + "; ".join(s["label"] for s in run.slots)
                        + ". Ask the contact to pick one, then pass its exact label.")
            from app.agent.runtime import email_was_given, normalize_email
            email = normalize_email(email)
            user_turns = [t.get("text", "") for t in run.transcript if t.get("role") == "user"]
            if not email_was_given(email, user_turns, (cfg_vars or {}).get("email", "")):
                return ("Not booked: the contact hasn't given that email. Ask for their email "
                        "and have them spell it — never guess it.")
            link = await _cal.create_booking(chosen["start"], email, "", cfg.get("calcom_event_type_id"))
            run.meeting_link, run.meeting_time, run.email = link, chosen["label"], email
            _record("book_appointment", {"slot": slot, "email": email}, {"booked": chosen["label"], "link": link})
            return f"Booked for {chosen['label']}. Confirm exactly this time with them, then wrap up."

        tools += [function_tool(check_availability), function_tool(book_appointment)]

    transfer_to = (cfg.get("transfer_number") or "").strip()
    if transfer_to and run.call_type == "outbound":
        async def transfer_call() -> str:
            """Transfer the caller to a human teammate. Tell them you're connecting them first."""
            from livekit import api as _lkapi
            sip_identity = next(
                (p.identity for p in ctx.room.remote_participants.values() if p.identity.startswith("sip_")),
                None,
            )
            if not sip_identity:
                return "Transfer isn't possible on this call. Offer to take a message instead."
            _record("transfer_call", {"to": transfer_to})
            run.outcome = "transferred"
            lk = _lkapi.LiveKitAPI(
                url=settings.livekit_url, api_key=settings.livekit_api_key,
                api_secret=settings.livekit_api_secret,
            )
            try:
                await asyncio.sleep(2.5)  # let the hand-off line finish
                await lk.sip.transfer_sip_participant(_lkapi.TransferSIPParticipantRequest(
                    participant_identity=sip_identity, room_name=ctx.room.name,
                    transfer_to=f"tel:{transfer_to}", play_dialtone=True,
                ))
                asyncio.create_task(_post_run_outcome(run, "transferred"))
                return "Transferred."
            except Exception as exc:
                log.warning("transfer_failed", error=str(exc))
                run.outcome = None
                return "The transfer failed. Apologize and offer to have someone call them back."
            finally:
                await lk.aclose()

        tools.append(function_tool(transfer_call))

    return tools


async def _run_configurable(ctx: JobContext, metadata: dict) -> None:
    import time as _time
    from app.agent.models import llm_endpoint
    from app.agent.runtime import build_instructions, render_vars
    from app.agent.voice_tuning import pronounce, voice_tuning

    cfg = metadata.get("agent") or {}
    if metadata.get("fetch_config") and metadata.get("agent_id"):
        cfg = await _fetch_agent_config(metadata["agent_id"]) or cfg
    variables = metadata.get("variables") or {}
    call_type = metadata.get("call_type", "outbound")
    run = _CallRun(metadata.get("call_log_id", ""), call_type)

    log.info("configurable_agent_started", room=ctx.room.name, agent=cfg.get("name"), call_type=call_type)

    if call_type == "outbound":
        await _wait_for_sip_answer(ctx)
    else:
        await ctx.wait_for_participant()

    turn_detector = None
    if not settings.low_resource_mode:
        try:
            from livekit.plugins.turn_detector.multilingual import MultilingualModel
            turn_detector = MultilingualModel()
        except Exception:
            turn_detector = None

    language = cfg.get("language") or "en"
    tuning = voice_tuning(cfg.get("voice_tuning"))
    model = cfg.get("llm_model") or "gpt-4.1-mini"
    api_key, base_url, sends_temperature = llm_endpoint(model)
    llm_kwargs = dict(model=model, api_key=api_key, base_url=base_url)
    if sends_temperature:
        llm_kwargs["temperature"] = float(cfg.get("temperature", 0.5))
    session_kwargs = dict(
        stt=deepgram.STT(
            model="nova-3", language=language if language != "multi" else "multi",
            api_key=settings.deepgram_api_key,
        ),
        llm=openai.LLM(**llm_kwargs),
        tts=cartesia.TTS(
            model="sonic-3",
            voice=cfg.get("voice_id") or DEFAULT_VOICE_ID,
            language=None if language in ("en", "multi") else language,
            speed=float(cfg.get("voice_speed") or 1.0),
            volume=tuning["volume"] if tuning["volume"] != 1.0 else None,
            api_key=settings.cartesia_api_key,
        ),
        vad=silero.VAD.load(),
        turn_handling={
            "interruption": {
                "min_duration": tuning["min_duration"],
                "min_words": tuning["min_words"],
                "false_interruption_timeout": 3.0,
                "resume_false_interruption": True,
            },
            # Latency: by default answer ~350 ms after the caller stops (adapts per caller),
            # and start drafting the reply — including audio — before the turn is final.
            "endpointing": {"mode": "dynamic", "min_delay": tuning["min_delay"], "max_delay": tuning["max_delay"]},
            "preemptive_generation": {"enabled": True, "preemptive_tts": True},
        },
    )
    if turn_detector:
        session_kwargs["turn_detection"] = turn_detector
    if _lk_replace is not None:
        session_kwargs["tts_text_transforms"] = ["filter_markdown", "filter_emoji"]
        if tuning["pronunciations"]:
            session_kwargs["tts_text_transforms"].append(pronounce(tuning["pronunciations"]))

    session = AgentSession(**session_kwargs)
    session_ref: dict = {"session": session}

    # Per-turn latency: end-of-turn delay + LLM first token + TTS first audio.
    def _on_metrics(ev) -> None:
        m = getattr(ev, "metrics", None)
        kind = getattr(m, "type", "")
        try:
            if kind == "eou_metrics":
                run.lat["eou"].append(float(m.end_of_utterance_delay))
            elif kind == "llm_metrics" and m.ttft > 0:
                run.lat["llm"].append(float(m.ttft))
            elif kind == "tts_metrics" and m.ttfb > 0:
                run.lat["tts"].append(float(m.ttfb))
        except Exception:
            pass

    session.on("metrics_collected", _on_metrics)
    channel = "phone" if call_type == "outbound" else "web"
    agent = Agent(
        instructions=build_instructions(cfg, variables, channel=channel),
        tools=_build_tools(cfg, run, ctx, session_ref, variables),
    )

    run.t0 = _time.monotonic()

    def _on_item(ev) -> None:
        try:
            item = getattr(ev, "item", None)
            role = getattr(item, "role", None)
            text = (getattr(item, "text_content", None) or "").strip()
            if role not in ("user", "assistant") or not text:
                return
            run.transcript.append({"role": role, "text": text, "ts": round(_time.monotonic() - run.t0, 2)})
            asyncio.create_task(_push_live_event(run.call_log_id, {
                "type": "transcript_turn", "session_id": ctx.room.name,
                "role": "agent" if role == "assistant" else "caller", "text": text, "ts": str(_time.time()),
            }))
        except Exception as exc:
            log.debug("transcript_capture_failed", error=str(exc))

    session.on("conversation_item_added", _on_item)
    await session.start(agent, room=ctx.room)

    asyncio.create_task(_push_live_event(run.call_log_id, {
        "type": "call_started", "session_id": ctx.room.name, "agent_type": cfg.get("name", "agent"),
        "direction": call_type, "caller_phone": variables.get("phone", ""),
        "prospect_name": variables.get("full_name") or variables.get("name", ""),
        "prospect_company": variables.get("company", ""), "ts": str(_time.time()),
    }))

    bg_state: dict = {"task": None, "track": None}
    if cfg.get("background_audio") and call_type == "outbound":
        bg_state["task"] = asyncio.create_task(_play_continuous_bg(ctx.room, bg_state))

    # Hard cap on call length: ask the agent to wrap up, then hang up.
    max_s = int(cfg.get("max_duration_seconds") or 600)

    async def _enforce_max_duration() -> None:
        await asyncio.sleep(max(30, max_s - 20))
        try:
            session.generate_reply(instructions="We're out of time. Politely wrap up and say goodbye now.")
        except Exception:
            pass
        await asyncio.sleep(20)
        await _delete_room(ctx.room.name)

    timer = asyncio.create_task(_enforce_max_duration())

    async def _shutdown() -> None:
        timer.cancel()
        task = bg_state.get("task")
        if task:
            task.cancel()
        outcome = run.outcome or ("no_answer" if not run.transcript else "completed")
        await _push_live_event(run.call_log_id, {
            "type": "call_ended", "session_id": ctx.room.name, "outcome": outcome,
            "duration_sec": round(_time.monotonic() - run.t0), "ts": str(_time.time()),
        })
        await _post_run_outcome(run, outcome)

    ctx.add_shutdown_callback(_shutdown)

    # When the browser tester leaves, end the job so the outcome is saved promptly.
    if call_type == "web":
        def _on_left(_p) -> None:
            if not ctx.room.remote_participants:
                asyncio.create_task(_delete_room(ctx.room.name))
        ctx.room.on("participant_disconnected", _on_left)

    first = render_vars(cfg.get("first_message", ""), variables).strip()
    if first:
        session.say(first, allow_interruptions=True)
    else:
        session.generate_reply(instructions="Greet the contact and begin the conversation.")


async def _wait_for_sip_answer(ctx: JobContext, timeout: float = 50.0) -> None:
    """
    LiveKit SIP outbound adds the callee as a participant while the call is
    still ringing; its `sip.callStatus` attribute flips to "active" on answer.
    Speaking before that loses the opening line. Falls through after a timeout
    so a missing attribute never wedges the call.
    """
    def _answered() -> bool:
        return any(
            (p.attributes or {}).get("sip.callStatus") == "active"
            for p in ctx.room.remote_participants.values()
        )

    if _answered():
        return
    answered_evt = asyncio.Event()

    def _on_attrs_changed(_changed, participant) -> None:
        if (participant.attributes or {}).get("sip.callStatus") == "active":
            answered_evt.set()

    def _on_connected(participant) -> None:
        if (participant.attributes or {}).get("sip.callStatus") == "active":
            answered_evt.set()

    ctx.room.on("participant_attributes_changed", _on_attrs_changed)
    ctx.room.on("participant_connected", _on_connected)
    try:
        await asyncio.wait_for(answered_evt.wait(), timeout=timeout)
        log.info("sip_call_active", room=ctx.room.name)
    except asyncio.TimeoutError:
        log.warning("sip_answer_wait_timeout", room=ctx.room.name)
    finally:
        ctx.room.off("participant_attributes_changed", _on_attrs_changed)
        ctx.room.off("participant_connected", _on_connected)


# ── Worker entrypoint ─────────────────────────────────────────────────────────

async def entrypoint(ctx: JobContext) -> None:
    """Called by the LiveKit worker for every new room/job."""
    await ctx.connect()

    raw_metadata = ctx.room.metadata or "{}"
    try:
        metadata = json.loads(raw_metadata)
    except json.JSONDecodeError:
        log.error("agent_metadata_parse_error", raw=raw_metadata)
        metadata = {}

    # Dashboard-built agents carry their config in the metadata.
    if metadata.get("agent") or metadata.get("agent_id"):
        await _run_configurable(ctx, metadata)
        return

    state = CallState(
        lead_id=metadata.get("lead_id", "unknown"),
        name=metadata.get("name", "there"),
        company=metadata.get("company", "your company"),
        phone=metadata.get("phone", ""),
        role=metadata.get("role", ""),
        email=metadata.get("email", ""),
        call_log_id=metadata.get("call_log_id", ""),
    )

    log.info("agent_started", room=ctx.room.name, lead_id=state.lead_id, name=state.name)

    await _wait_for_sip_answer(ctx)

    turn_detector = None
    if not settings.low_resource_mode:
        try:
            from livekit.plugins.turn_detector.multilingual import MultilingualModel
            turn_detector = MultilingualModel()
        except Exception:
            turn_detector = None

    # Agent pipeline mirrors hevox-prod's inbound carrier sales II agent:
    #   STT  = Deepgram nova-3 (en) with freight keyterm boosting
    #   LLM  = OpenAI gpt-4.1 @ temp 0.3 (reliable tool calls, natural cadence)
    #   TTS  = Cartesia Sonic-3, "Blake - Helpful Agent" voice, broker-tuned
    session_kwargs = dict(
        stt=deepgram.STT(
            model="nova-3",
            language="en",
            keyterm=_FREIGHT_KEYTERMS,
            api_key=settings.deepgram_api_key,
        ),
        llm=openai.LLM(
            model="gpt-4.1",
            temperature=0.3,
            api_key=settings.openai_api_key,
        ),
        tts=cartesia.TTS(
            model="sonic-3",
            voice=_BLAKE_VOICE_ID,
            language=None,          # auto-detect from LLM text
            speed=0.96,             # slightly below neutral — clearer, less rushed
            emotion=["positivity:medium"],
            text_pacing=True,       # keep Cartesia's natural phrase pauses
            api_key=settings.cartesia_api_key,
        ),
        vad=silero.VAD.load(),
        user_away_timeout=5.0,
        turn_handling={
            "interruption": {
                "min_duration": 0.5,
                "min_words": 2,         # 1-word backchannels ("yeah") don't barge-in
                "false_interruption_timeout": 3.0,   # up from 2.0 — more resume time
                "resume_false_interruption": True,
            },
            "preemptive_generation": {"enabled": False},
        },
    )
    if turn_detector:
        session_kwargs["turn_detection"] = turn_detector
    if _lk_replace is not None:
        session_kwargs["tts_text_transforms"] = ["filter_markdown", "filter_emoji"]

    session = AgentSession(**session_kwargs)
    agent = PounceAgent(state)

    # ── Capture the transcript ────────────────────────────────────────────────
    # Append every finalized user/assistant turn to state.transcript so end_call
    # can ship it to the outcome webhook → Runs tab. ts = seconds since start.
    import time as _time
    _call_t0 = _time.monotonic()
    agent._t0 = _call_t0   # tool-call markers share the same clock

    # ── Hang up the SIP line when end_call fires ──────────────────────────────
    # Give the goodbye line time to play, then delete the room (drops the PSTN
    # leg + the agent) so the call actually ends.
    def _hangup() -> None:
        async def _go() -> None:
            await asyncio.sleep(7.0)  # let the farewell finish speaking
            try:
                from livekit import api as _lkapi
                lk = _lkapi.LiveKitAPI(
                    url=settings.livekit_url,
                    api_key=settings.livekit_api_key,
                    api_secret=settings.livekit_api_secret,
                )
                try:
                    await lk.room.delete_room(_lkapi.DeleteRoomRequest(room=ctx.room.name))
                    log.info("call_hung_up", room=ctx.room.name)
                finally:
                    await lk.aclose()
            except Exception as exc:
                log.warning("hangup_failed", error=str(exc))
        asyncio.create_task(_go())

    agent._hangup = _hangup

    def _on_conversation_item(ev) -> None:
        try:
            item = getattr(ev, "item", None)
            if item is None:
                return
            role = getattr(item, "role", None)
            text = (getattr(item, "text_content", None) or "").strip()
            if role not in ("user", "assistant") or not text:
                return

            # Backchannel allow-list: if the prospect said a pure acknowledgment,
            # override the LLM response to continue naturally rather than treating
            # it as a new topic or question.
            if role == "user":
                normalized = text.lower().rstrip(".,!? ")
                if normalized in _BACKCHANNELS:
                    session.generate_reply(
                        instructions=(
                            "The prospect just gave a brief backchannel (e.g. 'yeah', "
                            "'right', 'go ahead'). Do NOT ask what they meant. Continue "
                            "naturally — re-ask your last question or move to the next "
                            "step in the flow. Keep it short."
                        )
                    )
                    return  # skip transcript for pure backchannels

            state.transcript.append({
                "role": role,
                "text": text,
                "ts": round(_time.monotonic() - _call_t0, 2),
            })
            # Push to live monitor in real time
            import time as _t2
            asyncio.create_task(_push_live_event(state.call_log_id, {
                "type": "transcript_turn",
                "session_id": ctx.room.name,
                "role": "agent" if role == "assistant" else "caller",
                "text": text,
                "ts": str(_t2.time()),
            }))
        except Exception as exc:  # never let transcript capture break the call
            log.debug("transcript_capture_failed", error=str(exc))

    session.on("conversation_item_added", _on_conversation_item)

    await session.start(agent, room=ctx.room)

    # Announce call_started to Live Monitor
    import time as _ts
    asyncio.create_task(_push_live_event(state.call_log_id, {
        "type": "call_started",
        "session_id": ctx.room.name,
        "agent_type": "sdr",
        "direction": "outbound",
        "caller_phone": state.phone,
        "prospect_name": state.name,
        "prospect_company": state.company,
        "ts": str(_ts.time()),
    }))

    # Continuous call-center ambience — separate track, always on (hevox parity).
    bg_audio_state: dict = {"task": None, "track": None}
    bg_audio_state["task"] = asyncio.create_task(_play_continuous_bg(ctx.room, bg_audio_state))

    async def _stop_bg_audio() -> None:
        task = bg_audio_state.pop("task", None)
        track = bg_audio_state.pop("track", None)
        if task:
            task.cancel()
            try:
                await task
            except (Exception, asyncio.CancelledError):
                pass
        if track:
            try:
                await ctx.room.local_participant.unpublish_track(track.sid)
            except Exception as exc:
                log.debug("agent.bg_unpublish_failed", error=str(exc))
        log.info("agent.bg_audio_stopped")

    ctx.add_shutdown_callback(_stop_bg_audio)

    # Fallback finalizer — if the caller hangs up before the agent calls
    # end_call, still persist the transcript + a derived outcome to the Runs tab.
    async def _finalize_call() -> None:
        outcome = _derive_outcome(state)
        import time as _tf
        await _push_live_event(state.call_log_id, {
            "type": "call_ended",
            "session_id": ctx.room.name,
            "outcome": outcome,
            "duration_sec": round(_tf.monotonic() - _call_t0),
            "ts": str(_tf.time()),
        })
        if state.outcome_posted:
            return
        await _post_call_outcome(state, outcome)

    ctx.add_shutdown_callback(_finalize_call)

    session.generate_reply(
        instructions="Call load_lead_context() immediately, then deliver the intro script."
    )

    log.info("agent_session_started", room=ctx.room.name, lead_id=state.lead_id)


if __name__ == "__main__":
    # Explicit-dispatch mode (hevox-prod style). The worker registers under
    # agent_name="closer" (LIVEKIT_AGENT_NAME) and only runs in rooms it was explicitly dispatched to
    # via agent_dispatch.create_dispatch (see OutboundCallService.dispatch_call).
    # This pairs with LiveKit SIP outbound — no auto-dispatch, no Twilio bridge.
    extra: dict = {}
    if settings.low_resource_mode:
        from livekit.agents import JobExecutorType
        # Run calls as threads in this process: a separate job process would load
        # every plugin a second time and blow a 512 MB memory limit.
        extra = dict(
            job_executor_type=JobExecutorType.THREAD,
            num_idle_processes=0,
            load_fnc=lambda *_: 0.0,
            initialize_process_timeout=60.0,
        )
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=settings.livekit_agent_name or "closer",
            **extra,
        )
    )
