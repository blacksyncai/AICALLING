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

import httpx

import structlog
from dotenv import load_dotenv

load_dotenv()  # must happen before any app imports

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RunContext,
    StopResponse,
    WorkerOptions,
    cli,
    function_tool,
)
from livekit.plugins import cartesia, deepgram, elevenlabs, openai, silero
# Register downloads and inference runners before CLI/worker initialization, on the main thread.
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from app.agent.prompt import build_system_prompt
from app.agent.mistral_tts import is_mistral_voice, make_livekit_tts
from app.agent.elevenlabs_tts import is_elevenlabs_voice, make_livekit_tts as make_elevenlabs_tts
from app.agent.models import MISTRAL_MODELS, NEEDS_USER_TURN
from app.agent.runtime import contact_turns, should_hold_hangup

CALL_CONNECTED_CUE = "[The call just connected.]"
from app.agent.voices import DEFAULT_VOICE_ID
from app.agent.state import CallState
from app.config import settings

log = structlog.get_logger(__name__)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(message)s",
)


def _prewarm_process(proc) -> None:
    """Load shared VAD before an idle worker accepts its first call."""
    proc.userdata["vad"] = silero.VAD.load()
    proc.userdata["vad_prewarmed"] = True


def _job_vad(ctx):
    # LiveKit VAD instances support independent streams for each session.
    vad = ctx.proc.userdata.get("vad")
    if vad is None:
        vad = silero.VAD.load()
        ctx.proc.userdata["vad"] = vad
        ctx.proc.userdata["vad_prewarmed"] = False
    return vad


def _prewarm_tts(tts, ctx) -> bool:
    warm = getattr(tts, "prewarm", None)
    if not callable(warm):
        return False
    try:
        # Register cleanup before opening a socket: no-answer jobs also need to close it.
        close = getattr(tts, "aclose", None)
        if callable(close):
            ctx.add_shutdown_callback(close)
        warm()
        return True
    except Exception as exc:
        log.warning("tts_prewarm_failed", error=type(exc).__name__)
        return False


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
                        f"{settings.api_base_url}/internal/leads/{self._state.lead_id}", headers=settings.internal_headers,
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

_shared_client: httpx.AsyncClient | None = None


def _api_client() -> httpx.AsyncClient:
    """One pooled client for internal API calls — no per-request TCP/TLS handshake."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
    return _shared_client


async def _api_post(path: str, *, json: dict, timeout: float = 10.0) -> httpx.Response:
    """POST to the internal API on the shared pooled connection."""
    return await _api_client().post(
        f"{settings.api_base_url}{path}", headers=settings.internal_headers, json=json, timeout=timeout
    )


async def _post_call_outcome(state, outcome: str) -> None:
    """
    Idempotently POST the call outcome + captured transcript to the webhook.
    Called from end_call (normal path) AND from the shutdown callback (caller
    hung up before end_call). The outcome_posted flag prevents double writes.
    """
    if state.outcome_posted or not state.call_log_id:
        return
    state.outcome_posted = True

    try:
        resp = await _api_post(f"/internal/calls/{state.call_log_id}/outcome", json={
            "outcome": outcome,
            "qualification_score": state.qualification_score,
            "q_team_size": state.q_team_size,
            "q_current_process": state.q_current_process,
            "q_decision_maker": state.q_decision_maker,
            "agreed_meeting_time": state.agreed_meeting_time,
            "meeting_link": state.meeting_link,
            "prospect_email": state.prospect_email,
            "transcript": state.transcript,
        })
        resp.raise_for_status()  # a rejected report must be retried, not logged as sent
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
    "wrong_number", "do_not_call", "language_barrier",
)


def _last_contact_turn(transcript: list[dict]) -> str:
    """What the contact said most recently (empty if they haven't spoken)."""
    for t in reversed(transcript or []):
        if t.get("role") == "user" and (t.get("text") or "").strip():
            return t["text"].strip()
    return ""


_TASKS: set = set()


def _keep(task: asyncio.Task) -> asyncio.Task:
    """Hold a reference to a fire-and-forget task so it isn't garbage-collected mid-flight."""
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return task


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
        self.ended_wall: float | None = None  # unix time the caller left
        self.last_found: list[dict] = []  # the times offered most recently ("the first one")
        self.post_task: asyncio.Task | None = None  # an outcome report in flight (awaited at shutdown)
        self.lat: dict[str, list[float]] = {"eou": [], "llm": [], "tts": []}
        from app.agent.turn_latency import TurnLatency
        self.turn_latency = TurnLatency()
        from app.agent.committed_actions import CommittedActions
        self.actions = CommittedActions()
        self.trace = None  # attached by the configurable session
        self.transferring = False  # warm transfer in progress: the caller is on hold, so silence is expected
        self.handed_off = False  # warm transfer connected: the caller and teammate share the room now

    def latency_summary(self) -> dict | None:
        avg = lambda xs: round(sum(xs) / len(xs), 3) if xs else None
        eou, llm, tts = avg(self.lat["eou"]), avg(self.lat["llm"]), avg(self.lat["tts"])
        observed = self.turn_latency.summary()
        if eou is None and llm is None and not observed.get("response_gap_samples"):
            return None
        return {
            **observed,
            "response_metric": "session_state_gap" if observed.get("response_gap_samples") else "unmeasured",
            "turns": len(self.lat["llm"]),
            "avg_eou": eou,
            "avg_llm_ttft": llm,
            "avg_tts_ttfb": tts,
            "avg_response": observed.get("avg_turn_gap"),
        }


async def _post_run_outcome(run: _CallRun, outcome: str) -> None:
    if run.outcome_posted or not run.call_log_id:
        return
    run.outcome_posted = True
    try:
        resp = await _api_post(f"/internal/calls/{run.call_log_id}/outcome", json={
            "outcome": outcome,
            "agreed_meeting_time": run.meeting_time,
            "meeting_link": run.meeting_link or None,
            "prospect_email": run.email,
            "transcript": run.transcript,
            "metrics": run.latency_summary(),
            "ended_at": run.ended_wall,
        })
        resp.raise_for_status()  # a rejected report must be retried, not logged as sent
        log.info("call_outcome_posted", call_log_id=run.call_log_id, outcome=outcome)
    except Exception as exc:
        run.outcome_posted = False
        log.warning("post_call_outcome_failed", error=str(exc), call_log_id=run.call_log_id)


async def _fetch_agent_config(agent_id: str) -> dict | None:
    try:
        resp = await _api_client().get(
            f"{settings.api_base_url}/internal/agents/{agent_id}/runtime",
            headers=settings.internal_headers, timeout=8.0)
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

    def _record(name: str, args: dict, output=None, *, success=True) -> None:
        run.transcript.append({
            "role": "tool", "tool": name, "args": args,
            "result": {"output": output, "success": success},
            "ts": round(_t.monotonic() - run.t0, 2) if run.t0 else 0.0,
        })

    def _hangup(context: RunContext | None, outcome: str) -> None:
        async def _go() -> None:
            # Hang up once the goodbye has actually finished playing (a fixed delay cut long goodbyes
            # off and left short ones hanging), plus a beat so it doesn't feel abrupt.
            try:
                if context is not None:
                    await asyncio.wait_for(context.wait_for_playout(), timeout=20)
            except Exception:
                pass
            if (context is not None and context.speech_handle.interrupted and run.ended_wall is None
                    and any(p.identity.startswith("sip_") for p in ctx.room.remote_participants.values())):
                # They talked over the goodbye ("wait, one more thing") and are still on — stay and let them
                # finish. The outcome stays as the latest result; a later end_call or the shutdown reports it.
                log.info("hangup_cancelled_interrupted", room=ctx.room.name, outcome=outcome)
                return
            if outcome == "voicemail":
                session_ref["voicemail_detected"] = True
            is_voicemail = outcome == "voicemail" or session_ref.get("voicemail_detected")
            if not is_voicemail:
                run.post_task = asyncio.create_task(_post_run_outcome(run, outcome))
            await asyncio.sleep(1.2)
            # Recheck: AMD may classify voicemail while goodbye is playing.
            if outcome == "voicemail" or session_ref.get("voicemail_detected"):
                from app.agent.voicemail_timing import finish_voicemail
                await finish_voicemail(run.t0, cfg.get("voice_tuning"),
                    hangup=lambda: _delete_room(ctx.room.name),
                    report=lambda: _post_run_outcome(run, run.outcome or outcome))
            else:
                from app.agent.voicemail_timing import wait_for_voicemail_minimum as _min_wait
                await _min_wait(run.t0, cfg.get("voice_tuning"))  # never under 7 s connected
                await _delete_room(ctx.room.name)
        _keep(asyncio.create_task(_go()))

    guard = {"refused": False}

    async def end_call(outcome: str, context: RunContext) -> str | None:
        """Hang up the call. Call this only AFTER you've said goodbye.

        Args:
            outcome: The result of the call. One of meeting_booked, qualified, not_qualified,
                interested, not_interested, callback, transferred, voicemail, no_answer, wrong_number,
                do_not_call, language_barrier (they don't speak or understand your language), completed.
        """
        if context.speech_handle.interrupted:
            return "Not ended: the caller interrupted. Respond to their latest turn."
        outcome = outcome if outcome in _END_OUTCOMES else "completed"
        if outcome == "transferred" and run.outcome != "transferred":
            return "Not ended: no transfer has completed. Use the transfer tool first, or offer a callback; do not hang up as though the caller was connected."
        if outcome == "meeting_booked" and not run.meeting_time:
            return "Not ended: no meeting is booked yet. Finish booking first, or pick another outcome."
        last = _last_contact_turn(run.transcript)
        if not guard["refused"] and should_hold_hangup(outcome, last):
            # Hanging up on an engaged contact ("gotcha" → click) loses the call. Push back once.
            guard["refused"] = True
            log.info("end_call_held", room=ctx.room.name, outcome=outcome, contact_words=len(last.split()))
            return ("Not ended: the contact is still engaged and hasn't said goodbye. Don't hang up — respond to "
                    "what they just said and keep the conversation going. Only end after a clear goodbye.")
        run.outcome = outcome
        _record("end_call", {"outcome": outcome})
        log.info("end_call", room=ctx.room.name, outcome=outcome, contact_words=len(last.split()),
                 turns=sum(1 for t in run.transcript if t.get("role") in ("user", "assistant")))
        _hangup(context, outcome)
        return None  # no output → no follow-up reply (it used to speak things like "[Call ended]")

    tools = [function_tool(end_call)]

    if cfg.get("enable_booking"):
        async def check_availability(context: RunContext, preferred_date: str = "", time_of_day: str = "", time: str = "") -> str:
            """Look up open appointment times. Only ever offer times this returns. Call it again whenever they want
            other options (another day, morning/afternoon/evening, or a specific time) — each call returns times
            not offered yet.

            Args:
                preferred_date: The day they want, as YYYY-MM-DD. Empty for the soonest.
                time_of_day: "morning", "afternoon" or "evening" if they said so, else empty.
                time: A specific time they asked about, 24h "HH:MM" (e.g. "15:00"), else empty.
            """
            if context.speech_handle.interrupted:
                return "Lookup cancelled: the caller changed the turn."
            if run.trace:
                run.trace.mark("tool_request", speech=context.speech_handle, tool="check_availability")
            try:
                found = await _cal.fetch_slots(preferred_date, cfg.get("calcom_event_type_id"),
                                           cfg.get("calcom_api_key"), cfg.get("calendar_timezone"),
                                           time_of_day=time_of_day, time=time,
                                           exclude={s["start"] for s in run.slots}, count=3)
            except _cal.CalendarUnavailable:
                if run.trace:
                    run.trace.mark("tool_result", speech=context.speech_handle, tool="check_availability", status="unavailable")
                _record("check_availability", {}, {"error": "calendar unavailable"}, success=False)
                return "Availability is unavailable, not fully booked. Don't invent slots. Offer a teammate follow-up."
            if run.trace:
                run.trace.mark("tool_result", speech=context.speech_handle, tool="check_availability", status="ok")
            if context.speech_handle.interrupted:
                return "Lookup cancelled: don't offer these results after the caller changed their request."
            run.slots = _cal.remember_slots(run.slots, found)
            if found:
                run.last_found = found
            _record("check_availability", {"preferred_date": preferred_date, "time_of_day": time_of_day, "time": time},
                    {"slots": [s["label"] for s in found]})
            if not found:
                return ("No new openings for that. Offer a different day or time of day"
                        + (", or one of the times already offered." if run.slots else "."))
            return ("Open: " + _cal.spoken_offer(found, cfg.get("calendar_timezone"))
                    + ". Offer them exactly like that, in one short sentence (\"I've got " + _cal.spoken_offer(
                        found, cfg.get("calendar_timezone")) + ". What works best?\"). Say only the day and time: no "
                    "month, no date number, no time zone unless they ask. If they ask for the times again, say them "
                    "again. To book, pass one of these labels: " + "; ".join(s["label"] for s in found) + ".")

        async def book_appointment(slot: str, email: str, context: RunContext) -> str:
            """Book one of the slots from check_availability. Confirm the email spelling first.

            Args:
                slot: The exact label of the slot they chose, as returned by check_availability.
                email: The contact's email exactly as they said it. Never guess it.
            """
            if run.meeting_time:
                return f"Already booked for {run.meeting_time}. Do not create a second booking; changes need a teammate."
            if not run.slots:
                return "No slots offered yet. Call check_availability first."
            chosen = _cal.pick_slot(run.slots, slot, cfg.get("calendar_timezone"), run.last_found)
            if not chosen:
                return ("Which slot? Offered: " + "; ".join(s["label"] for s in run.slots)
                        + ". Ask the contact to pick one, then pass its exact label.")
            from app.agent.runtime import email_was_given, normalize_email
            email = normalize_email(email)
            user_turns = [t.get("text", "") for t in run.transcript if t.get("role") == "user"]
            if not email_was_given(email, user_turns, (cfg_vars or {}).get("email", "")):
                return ("Not booked: the contact hasn't given that email. Ask for their email "
                        "and have them spell it — never guess it.")
            from app.agent.committed_actions import ActionUncertain, NoAction
            async def _book():
                if run.trace:
                    run.trace.mark("tool_request", speech=context.speech_handle, tool="book_appointment")
                # A previous offer is not a reservation. Recheck real availability.
                from datetime import datetime
                local_day = datetime.fromisoformat(chosen["start"].replace("Z", "+00:00")).astimezone(
                    _cal._zone(cfg.get("calendar_timezone"))).date().isoformat()
                try:
                    fresh = await _cal.fetch_slots(local_day, cfg.get("calcom_event_type_id"),
                        cfg.get("calcom_api_key"), cfg.get("calendar_timezone"), count=10000)
                except _cal.CalendarUnavailable as exc:
                    if run.trace:
                        run.trace.mark("tool_result", speech=context.speech_handle, tool="book_appointment", status="read_unavailable_no_write")
                    raise NoAction("Not booked: availability could not be verified. Try checking availability again or offer a teammate follow-up.") from exc
                if context.speech_handle.interrupted:
                    if run.trace:
                        run.trace.mark("tool_result", speech=context.speech_handle, tool="book_appointment", status="cancelled_before_write")
                    raise NoAction("Not booked: the caller interrupted before booking. Respond to their latest request.")
                if chosen["start"] not in {s["start"] for s in fresh}:
                    if run.trace:
                        run.trace.mark("tool_result", speech=context.speech_handle, tool="book_appointment", status="stale")
                    raise NoAction("Not booked: that slot is no longer available. Check availability again.")
                link = await _cal.create_booking(chosen["start"], email, "", cfg.get("calcom_event_type_id"),
                    cfg.get("calcom_api_key"), cfg.get("calendar_timezone"))
                if not link:
                    raise ActionUncertain("No booking receipt")
                # Persist the authoritative result inside the shielded operation,
                # even if caller interruption cancels the model's waiting tool.
                run.meeting_link, run.meeting_time, run.email = link, chosen["label"], email
                _record("book_appointment", {"slot": slot, "email": email}, {"booked": chosen["label"], "link": link})
                if run.trace:
                    run.trace.mark("tool_result", speech=context.speech_handle, tool="book_appointment", status="confirmed")
                return f"Booked for {chosen['label']}. Confirm exactly this time with them, then wrap up."
            try:
                return await run.actions.run(("booking",), _book, context=context)
            except NoAction as exc:
                return str(exc)
            except ActionUncertain:
                _record("book_appointment", {}, {"error": "confirmation unavailable"}, success=False)
                if run.trace:
                    run.trace.mark("tool_result", speech=context.speech_handle, tool="book_appointment", status="unknown_no_retry")
                return "Booking is not confirmed. Do not retry or promise confirmation; offer a teammate follow-up."

        tools += [function_tool(check_availability), function_tool(book_appointment)]

    transfer_to = (cfg.get("transfer_number") or "").strip()
    if transfer_to and run.call_type in ("outbound", "inbound"):  # the prompt offers it on every phone call
        async def transfer_call(context: RunContext) -> str:
            """Transfer the caller to a human teammate. Tell them you're connecting them first."""
            from livekit import api as _lkapi
            from app.agent import call_transfer
            if cfg.get("transfer_mode") == "warm" and (session_ref.get("dial") or {}).get("trunk_id"):
                return await _warm_transfer(context)
            sip_identity = call_transfer.caller_identity(ctx.room.remote_participants.values())
            if not sip_identity:
                log.warning("call_transfer_no_sip_caller", call_log_id=run.call_log_id,
                            call_type=run.call_type, participant_count=len(ctx.room.remote_participants))
                return "Transfer isn't possible on this call. Offer to take a message instead."
            from app.agent.committed_actions import ActionUncertain, NoAction
            async def _transfer():
                try:
                    transfer_request = call_transfer.request(ctx.room.name, sip_identity, transfer_to)
                except ValueError:
                    raise NoAction("Transfer destination is not a valid phone number. Offer a callback and ask the team to check its transfer setting.") from None
                # Await the actual handoff line, rather than adding 2.5 seconds.
                try:
                    await asyncio.wait_for(context.wait_for_playout(), timeout=12)
                except asyncio.TimeoutError as exc:
                    raise NoAction("Transfer not started: handoff speech did not finish. Check the caller's request before continuing.") from exc
                if context.speech_handle.interrupted:
                    raise NoAction("Transfer cancelled before connecting; respond to the caller's correction.")
                lk = _lkapi.LiveKitAPI(url=settings.livekit_url, api_key=settings.livekit_api_key,
                                       api_secret=settings.livekit_api_secret)
                try:
                    if run.trace:
                        run.trace.mark("tool_request", speech=context.speech_handle, tool="transfer_call")
                    response = await asyncio.wait_for(lk.sip.transfer_sip_participant(
                        transfer_request, timeout=call_transfer.REQUEST_SECONDS), timeout=call_transfer.DEADLINE_SECONDS)
                    result = call_transfer.receipt(response)
                    log.info("call_transfer_result", call_log_id=run.call_log_id, **result)
                    if result["status"] != "completed":
                        _record("transfer_call", {}, result, success=False)
                        if run.trace:
                            run.trace.mark("tool_result", speech=context.speech_handle, tool="transfer_call", **result)
                        return ("Transfer failed. Offer a teammate callback; do not claim a connection or retry automatically."
                                if result["status"] == "failed" else
                                "Transfer is not confirmed. Do not retry automatically or claim a human answered; offer a teammate callback if the caller is still here.")
                    run.outcome = "transferred"
                    _record("transfer_call", {"to": transfer_to}, result)
                    if run.trace:
                        run.trace.mark("tool_result", speech=context.speech_handle, tool="transfer_call", status="completed")
                    run.post_task = asyncio.create_task(_post_run_outcome(run, "transferred"))
                    return "Transfer completed by the phone system. This does not verify which person answered."
                finally:
                    try:
                        await lk.aclose()
                    except Exception as exc:
                        # Closing the HTTP client cannot undo a confirmed handoff.
                        log.warning("call_transfer_client_cleanup_failed", error_type=type(exc).__name__)
            try:
                return await run.actions.run(("transfer",), _transfer, context=context)
            except NoAction as exc:
                return str(exc)
            except ActionUncertain as exc:
                details = call_transfer.error_details(exc.__cause__ or exc)
                log.warning("call_transfer_unconfirmed", call_log_id=run.call_log_id, **details)
                _record("transfer_call", {}, {"error": "result unavailable", **details}, success=False)
                if run.trace:
                    run.trace.mark("tool_result", speech=context.speech_handle, tool="transfer_call", status="unknown_no_retry")
                return "Transfer is not confirmed. Do not retry automatically; offer a teammate callback."

        async def _warm_transfer(context: RunContext) -> str:
            """Hold the caller, call the teammate and brief them, then put the caller through. If nobody takes
            it, the caller is back with the agent, which sets up the next step instead."""
            from livekit.agents.beta.workflows import WarmTransferTask
            from livekit import rtc
            from livekit.agents.llm import StopResponse as _Stop, ToolError
            from app.agent import handoff
            from app.services.outbound_call import validate_e164

            if run.transferring:
                return "A transfer is already in progress. Wait for it."
            try:
                number = validate_e164(transfer_to)
            except ValueError:
                return ("Transfer destination is not a valid phone number. Offer a callback and ask the team to check "
                        "its transfer setting.")
            try:  # let "one sec, let me grab someone" finish before the hold music starts
                await asyncio.wait_for(context.wait_for_playout(), timeout=12)
            except asyncio.TimeoutError:
                pass
            if context.speech_handle.interrupted:
                return "Transfer cancelled before connecting; respond to what the caller just said."
            session = session_ref["session"]
            dial = session_ref["dial"]
            ring = int(cfg.get("transfer_ring_seconds") or handoff.DEFAULT_RING_SECONDS)
            task = WarmTransferTask(
                sip_call_to=number, sip_trunk_id=dial["trunk_id"], sip_number=dial.get("from") or "",
                ringing_timeout=ring,
                instructions=handoff.briefing_instructions(cfg, cfg_vars, handoff.history_text(session.history)),
            )

            def _fail(reason: str) -> None:
                if not task.done():
                    task._set_result(ToolError(reason))  # the task's own way to finish and un-hold the caller

            def _caller_left(p) -> None:
                if p.identity != task._human_agent_identity and getattr(p, "kind", None) == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
                    _fail("caller hung up")

            async def _deadline() -> None:  # ringing plus the handoff conversation, never longer
                await asyncio.sleep(ring + handoff.BRIEFING_SECONDS)
                _fail("timed out")

            run.transferring = True
            log.info("warm_transfer_started", call_log_id=run.call_log_id, ring_seconds=ring)
            ctx.room.on("participant_disconnected", _caller_left)
            deadline = asyncio.create_task(_deadline())
            try:
                await task
                error = ""
            except Exception as exc:
                error = str(getattr(exc, "message", "") or exc)
            finally:
                deadline.cancel()
                ctx.room.off("participant_disconnected", _caller_left)
                run.transferring = False

            if not error:
                log.info("warm_transfer_connected", call_log_id=run.call_log_id)
                run.outcome, run.handed_off = "transferred", True
                if run.ended_wall is None:
                    run.ended_wall = _t.time()  # the agent's part of the call ends here
                _record("transfer_call", {"to": transfer_to, "mode": "warm"}, {"status": "connected"})
                run.post_task = asyncio.create_task(_post_run_outcome(run, "transferred"))

                async def _leave() -> None:  # the caller and teammate keep talking without us
                    await asyncio.sleep(0.5)
                    session.shutdown(drain=False)
                asyncio.create_task(_leave())
                raise _Stop()
            reason = ("caller_left" if "caller hung up" in error else "voicemail" if "voicemail" in error
                      else "declined" if "declined" in error else "no_answer")
            log.info("warm_transfer_not_connected", call_log_id=run.call_log_id, reason=reason, error=error[:120])
            _record("transfer_call", {"to": transfer_to, "mode": "warm"}, {"status": reason}, success=False)
            if reason == "caller_left":
                raise _Stop()
            return handoff.not_connected(reason, bool(cfg.get("enable_booking")))

        tools.append(function_tool(transfer_call))

    return tools


async def _recording_state(metadata: dict, room_name: str, state: str) -> None:
    if not metadata.get("worker_recording") or not metadata.get("call_log_id"):
        return
    try:
        response = await _api_post(
            f"/internal/calls/{metadata['call_log_id']}/recording-state",
            json={"room_name": room_name, "state": state}, timeout=5.0)
        response.raise_for_status()
    except Exception as exc:
        log.warning("recording_state_update_failed", state=state, error=type(exc).__name__)


async def _start_worker_recording(ctx, session, metadata):
    if not metadata.get("record_key") or not (metadata.get("call_type") == "web" or metadata.get("worker_recording")):
        return None
    from app.agent.call_recorder import CallRecorder
    recorder = CallRecorder(session, metadata["record_key"])
    try:
        if await recorder.start():
            log.info("worker_recording_started", room=ctx.room.name)
            asyncio.create_task(_recording_state(metadata, ctx.room.name, "recording"))
            return recorder
    except Exception as exc:
        log.warning("call_recording_start_failed", room=ctx.room.name, error=type(exc).__name__)
    await recorder.finish()
    asyncio.create_task(_recording_state(metadata, ctx.room.name, "failed"))
    return None


async def _draft_opening(cfg: dict, variables: dict) -> str:
    """The agent's first line for an outbound call, written ahead of pickup (empty on any failure)."""
    from openai import AsyncOpenAI

    from app.agent.models import llm_endpoint
    from app.agent.runtime import build_instructions

    model = cfg.get("llm_model") or "gpt-4.1-nano"
    try:
        api_key, base_url, sends_temperature = llm_endpoint(model)
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        kwargs: dict = {}
        if sends_temperature:
            kwargs["temperature"] = float(cfg.get("temperature", 0.5))
        from app.agent.models import GROQ_MODELS

        if model in GROQ_MODELS:
            kwargs["reasoning_effort"] = "none"
        contact_name = (variables.get("full_name") or variables.get("name") or "").strip()
        resp = await asyncio.wait_for(client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": build_instructions(cfg, variables, channel="phone")},
                {"role": "user", "content": "[The contact just picked up the phone.] Say only your opening line — one or two "
                                            "short spoken sentences, no stage directions or quotes."
                                            + (f" Greet {contact_name} by name and refer to them, never to yourself. "
                                               f"You are the caller; {contact_name} is the person who answered."
                                               if contact_name else
                                               " You are the caller; never introduce yourself as the person who answered.")},
            ],
            **kwargs,
        ), timeout=12)
        text = (resp.choices[0].message.content or "").strip().strip('"')
        return text if 0 < len(text) < 400 else ""
    except Exception as exc:
        log.warning("opening_draft_failed", model=model, error=str(exc)[:200])
        return ""


async def _run_configurable(ctx: JobContext, metadata: dict) -> None:
    from app.agent.voicemail_timing import wait_for_voicemail_minimum
    import time as _time
    from app.agent.models import llm_endpoint
    from app.agent.runtime import build_instructions, render_vars
    from app.agent.voice_tuning import BUILT_IN_PRONUNCIATIONS, pronounce, voice_tuning

    cfg = metadata.get("agent") or {}
    # Fetch over the private API when the config was too big to inline, or when booking needs
    # the agent's Cal.com key (it never rides in room metadata, which callers can read).
    needs_key = cfg.get("enable_booking") and cfg.get("calcom_key_set")
    if (metadata.get("fetch_config") or needs_key) and metadata.get("agent_id"):
        fetched = await _fetch_agent_config(metadata["agent_id"])
        if fetched:
            # Keep the per-call cap (credits / trial) the dispatcher set.
            cap = cfg.get("max_duration_seconds")
            cfg = {**fetched, **({"max_duration_seconds": cap} if cap else {})}
    variables = metadata.get("variables") or {}
    call_type = metadata.get("call_type", "outbound")
    run = _CallRun(metadata.get("call_log_id", ""), call_type)
    from app.agent.voice_trace import VoiceTrace, owning_speech, short_sentence_tokenizer
    trace = VoiceTrace(lambda event, **fields: log.info(event, room=ctx.room.name, **fields),
                       enabled=settings.voice_turn_trace)
    run.trace = trace

    log.info("configurable_agent_started", room=ctx.room.name, agent=cfg.get("name"), call_type=call_type)

    # Write the opening line while the phone is still ringing, so the agent can speak the moment
    # the contact says hello instead of waiting on the LLM after pickup.
    opening_task = None
    from app.agent.runtime import opening_reads_wrong

    # A saved opening that needs a detail this contact doesn't have ("Is this {{name}}?") would come out wrong,
    # so the agent writes its own first line from the prompt instead.
    fixed_opening = "" if opening_reads_wrong(cfg.get("first_message", ""), variables) else cfg.get("first_message", "")
    if call_type == "outbound" and not render_vars(fixed_opening, variables).strip():
        opening_task = asyncio.create_task(_draft_opening(cfg, variables))

    prepare_started = _time.monotonic()
    turn_detector = None
    if not settings.low_resource_mode:
        try:
            turn_detector = MultilingualModel()
            if settings.voice_fast_identity_turns:
                from app.agent.opening_turns import OpeningTurnDetector
                turn_detector = OpeningTurnDetector(
                    turn_detector, variables.get("full_name") or variables.get("name") or variables.get("first_name"),
                    on_fast=lambda: trace.mark("identity_turn_complete", source="closed_short_answer"))
        except Exception as exc:
            log.warning("turn_detector_unavailable", error=type(exc).__name__, reason=str(exc)[:240])
            turn_detector = None

    language = cfg.get("language") or "en"
    tuning = voice_tuning(cfg.get("voice_tuning"))
    model = cfg.get("llm_model") or "gpt-4.1-nano"
    voice_id = cfg.get("voice_id") or DEFAULT_VOICE_ID
    api_key, base_url, sends_temperature = llm_endpoint(model)
    llm_kwargs = dict(model=model, api_key=api_key, base_url=base_url)
    from app.agent.models import reasoning_effort_for

    if reasoning_effort_for(model):  # faster replies, and less private reasoning to leak into speech
        llm_kwargs["reasoning_effort"] = reasoning_effort_for(model)
    if sends_temperature:
        llm_kwargs["temperature"] = float(cfg.get("temperature", 0.5))
    session_kwargs = dict(
        stt=cartesia.STT(model="ink-whisper", language="tl", api_key=settings.cartesia_api_key)
        if language == "tl" else deepgram.STT(
            model="nova-3", language=language if language != "multi" else "multi",
            api_key=settings.deepgram_api_key,
        ),
        llm=openai.LLM(**llm_kwargs),
        tts=make_elevenlabs_tts(voice_id, speed=float(cfg.get("voice_speed") or 1.0), language=language)
        if is_elevenlabs_voice(voice_id) else
        make_livekit_tts(voice_id) if is_mistral_voice(voice_id) and settings.mistral_api_key else cartesia.TTS(
            model="sonic-3",
            voice=DEFAULT_VOICE_ID if is_mistral_voice(voice_id) else voice_id,
            language=None if language in ("en", "multi") else language,
            speed=float(cfg.get("voice_speed") or 1.0),
            volume=tuning["volume"] if tuning["volume"] != 1.0 else None,
            api_key=settings.cartesia_api_key,
            tokenizer=short_sentence_tokenizer(settings.voice_short_sentence_streaming),
        ),
        vad=_job_vad(ctx),
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
        session_kwargs["tts_text_transforms"].append(pronounce(tuning["pronunciations"] + BUILT_IN_PRONUNCIATIONS))

    session = AgentSession(**session_kwargs)
    session_ref: dict = {"session": session, "dial": metadata.get("dial") or {}}

    # Per-turn latency: end-of-turn delay + LLM first token + TTS first audio.
    def _on_metrics(ev) -> None:
        m = getattr(ev, "metrics", None)
        kind = getattr(m, "type", "")
        if kind in ("llm_metrics", "tts_metrics", "stt_metrics", "eou_metrics"):
            fields = {key: getattr(m, key) for key in (
                "ttft", "ttfb", "duration", "cancelled", "completion_tokens", "prompt_tokens",
                "audio_duration", "characters_count", "acquire_time", "connection_reused",
                "end_of_utterance_delay", "transcription_delay", "on_user_turn_completed_delay")
                if isinstance(getattr(m, key, None), (int, float, bool))}
            trace.mark("provider_metrics", provider_metric=kind,
                       provider_speech_id=getattr(m, "speech_id", None), **fields)
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

    def _speech_created(ev):
        speech = ev.speech_handle
        trace.mark("speech_created", speech=speech, source=ev.source, user_initiated=ev.user_initiated)
        speech.add_done_callback(lambda handle: trace.mark("speech_done", speech=handle, interrupted=handle.interrupted))

    session.on("speech_created", _speech_created)
    session.on("user_input_transcribed", lambda ev: trace.mark(
        "transcript_final" if ev.is_final else "transcript_interim"))
    session.on("agent_false_interruption", lambda ev: trace.mark("false_interruption", resumed=ev.resumed))
    session.on("eot_prediction", lambda ev: trace.mark("semantic_prediction", delay_seconds=ev.delay,
                                                       inference_seconds=ev.inference_duration))

    def _track_user_gap(ev):
        trace.mark("user_" + ev.new_state, observed_at="callback_receipt")
        run.turn_latency.user_state(getattr(ev, "old_state", ""), getattr(ev, "new_state", ""), _time.monotonic())

    def _track_agent_gap(ev):
        trace.mark("agent_" + ev.new_state, speech=session.current_speech,
                   observed_at="worker_output_state_not_caller_audibility")
        observed = run.turn_latency.agent_state(getattr(ev, "old_state", ""), getattr(ev, "new_state", ""), _time.monotonic())
        if observed:
            log.info("turn_response_gap", room=ctx.room.name, model=model, **observed)

    session.on("user_state_changed", _track_user_gap)
    session.on("agent_state_changed", _track_agent_gap)
    channel = "web" if call_type == "web" else "phone"

    # ── Voicemail: spot an answering machine early, then hang up or leave the agent's message ──
    from app.agent.runtime import personal_greeting_match, voicemail_greeting_match

    vm = {"detected": False, "heard": "", "speaking": False, "changed": _time.monotonic()}
    vm_action = (cfg.get("voicemail_action") or "hang_up")
    # Call screener: "seen" once one answered; "holding" while we wait for the person to come on the line.
    screen = {"seen": False, "holding": False, "passed": False, "since": 0.0}
    screen_action = cfg.get("screener_action") or "answer"
    # Outbound: the opening line answers the contact's "Hello?". Until it's queued, a user turn must not
    # also get its own reply, or the agent says the opening twice back to back.
    opening = {"pending": call_type == "outbound"}
    vm_message = render_vars(cfg.get("voicemail_message") or "", variables).strip()

    class _CallAgent(Agent):
        async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
            trace.mark("turn_committed", turn_key=trace.turn_key(new_message.text_content or ""))
            if vm["detected"]:
                raise StopResponse()  # don't talk back to a voicemail greeting
            if opening["pending"]:
                log.info("opening_covers_turn", room=ctx.room.name)
                raise StopResponse()  # the opening line is the reply to their "Hello?"
            if screen["holding"]:
                from app.agent.runtime import is_screener_hold

                text = (new_message.text_content or "").strip()
                if not text or is_screener_hold(text):
                    raise StopResponse()  # the screener is still holding the line: stay quiet
                screen["holding"], screen["passed"] = False, True
                log.info("screener_passed", room=ctx.room.name)
                turn_ctx.add_message(role="system", content=(
                    "The call screener has put the actual person on the line. Greet them naturally and carry on "
                    "with your opening from the start, as if they just picked up."))

        async def tts_node(self, text, model_settings):
            speech = owning_speech()
            observed_text = trace.stream(text, "tts_input", speech=speech)
            async for frame in trace.stream(Agent.default.tts_node(self, observed_text, model_settings),
                                            "tts_audio", speech=speech, audio=True):
                yield frame

        async def llm_node(self, chat_ctx, tools, model_settings):
            """The model's reply minus any leaked notes or imagined turns (see app/agent/speech_guard.py)."""
            from app.agent.speech_guard import guarded

            def _cut(dropped: str) -> None:
                log.warning("llm_leak_cut", room=ctx.room.name, model=model, dropped=dropped[:80])

            from app.agent.chat_order import contact_last

            from app.agent.repeat_guard import no_repeats, said_lines, with_nudge

            chat_ctx = contact_last(chat_ctx, needs_user_last=model in MISTRAL_MODELS)
            speech = owning_speech()
            user = next((item for item in reversed(chat_ctx.items)
                         if getattr(item, "role", None) == "user"), None)
            turn_key = trace.turn_key(getattr(user, "text_content", "") or "") if user else None

            def _attempt(nudged: bool):
                trace.mark("llm_request", speech=speech, attempt=int(nudged), turn_key=turn_key)
                return trace.stream(Agent.default.llm_node(self, with_nudge(chat_ctx) if nudged else chat_ctx,
                                    tools, model_settings), "llm_chunk", speech=speech, attempt=int(nudged))

            def _repeat(dropped: str) -> None:
                log.warning("llm_repeat_cut", room=ctx.room.name, model=model, dropped=dropped[:80])

            first_text = True
            heard = getattr(user, "text_content", "") or "" if user else ""
            async for chunk in guarded(no_repeats(_attempt, said_lines(chat_ctx), _repeat, heard), _cut):
                text = chunk if isinstance(chunk, str) else getattr(getattr(chunk, "delta", None), "content", None)
                if text and first_text:
                    trace.mark("usable_text_first", speech=speech, turn_key=turn_key)
                    first_text = False
                yield chunk

    async def _handle_voicemail() -> None:
        session_ref["voicemail_detected"] = True
        log.info("voicemail_detected", room=ctx.room.name, action=vm_action)
        try:
            session.interrupt(force=True)
        except Exception:
            pass
        left = False
        if vm_action == "leave_message" and vm_message:
            # Wait for the greeting (and its beep) to finish: ~2.5 s of quiet (greetings pause mid-way), at most 30 s.
            deadline = _time.monotonic() + 30
            while _time.monotonic() < deadline:
                if not vm["speaking"] and _time.monotonic() - vm["changed"] > 2.5:
                    break
                await asyncio.sleep(0.2)
            try:
                await session.say(vm_message, allow_interruptions=False).wait_for_playout()
                left = True
            except Exception as exc:
                log.warning("voicemail_message_failed", error=str(exc))
        run.transcript.append({"role": "tool", "tool": "voicemail",
                               "args": {"action": "left_message" if left else "hung_up"},
                               "result": {"success": True}, "ts": round(_time.monotonic() - run.t0, 2)})
        # Screened and the person never came on: not a voicemail (the agent was on the line working).
        vm_outcome = "screened" if screen["seen"] and not screen["passed"] else "voicemail"
        if run.outcome_posted and run.outcome not in ("voicemail", "no_answer", "screened"):
            # The agent already ended it as a conversation, but it was a greeting (detection can land a few
            # seconds late). Report again so it's recorded as voicemail and the contact gets their retry.
            if len(contact_turns(run.transcript)) <= 2:
                run.outcome_posted = False
                log.info("outcome_corrected_to_voicemail", room=ctx.room.name, was=run.outcome)
        run.outcome = vm_outcome
        await asyncio.sleep(0.5)
        from app.agent.voicemail_timing import finish_voicemail
        async def _report() -> None:
            # Keep the greeting on the call record: it's how Radar hears whose voicemail it was.
            from app.agent.runtime import voicemail_greeting_turn

            turn = voicemail_greeting_turn(run.transcript, vm["heard"])
            if turn:
                run.transcript.append({**turn, "ts": round(_time.monotonic() - run.t0, 2)})
            await _post_run_outcome(run, vm_outcome)

        await finish_voicemail(run.t0, cfg.get("voice_tuning"),
            hangup=lambda: _delete_room(ctx.room.name), report=_report)

    async def _answer_screener() -> None:
        try:
            session.interrupt(force=True)
        except Exception:
            pass
        run.transcript.append({"role": "tool", "tool": "call_screener", "args": {"action": screen_action},
                               "result": {"success": True}, "ts": round(_time.monotonic() - run.t0, 2)})
        if screen_action == "hang_up":
            vm["detected"] = True
            await _handle_voicemail()
            return
        screen["since"] = _time.monotonic()
        # Sound like someone they know who trailed off ("Hey Mark, it's just…"): no name, company or pitch,
        # so the person picks up to see who it is.
        first = (variables.get("first_name") or "").strip() or \
            (variables.get("name") or variables.get("full_name") or "").strip().split(" ")[0]
        try:
            session.say(f"Hey {first}, it's just..." if first and first.lower() != "there" else "Hey, it's just...",
                        allow_interruptions=False)
        except Exception as exc:
            log.warning("screener_reply_failed", error=str(exc)[:200])

    def _on_transcribed(ev) -> None:
        if call_type == "outbound" and vm["detected"] and getattr(ev, "is_final", False):
            # Keep hearing the greeting until hangup: the name often comes after the detection phrase.
            if len(vm["heard"]) < 2000:
                vm["heard"] += " " + (getattr(ev, "transcript", "") or "")
            return
        if call_type != "outbound" or vm["detected"] or not getattr(ev, "is_final", False):
            return
        if run.t0 and _time.monotonic() - run.t0 > 45:
            return  # only the opening of the call
        text = getattr(ev, "transcript", "") or ""
        if not screen["seen"]:
            from app.agent.runtime import screener_match

            hit = screener_match(vm["heard"] + " " + text)
            if hit:
                screen["seen"] = True
                vm["heard"] = ""  # a screener that then sends us to voicemail is still caught below
                log.info("screener_match", room=ctx.room.name, phrase=hit, action=screen_action)
                screen["holding"] = screen_action == "answer"  # before its turn completes, so we don't reply to it
                asyncio.create_task(_answer_screener())
                return
            from app.agent.runtime import screener_hold_start

            held = screener_hold_start(text)
            if held and screen_action == "hang_up":
                screen["seen"] = True
                log.info("screener_hold_match", room=ctx.room.name, phrase=held, action=screen_action)
                asyncio.create_task(_answer_screener())
                return
            if held:
                # It heard the opening and is holding while the person decides: stop talking and wait.
                screen.update(seen=True, holding=True, since=_time.monotonic())
                vm["heard"] = ""
                log.info("screener_hold_match", room=ctx.room.name, phrase=held)
                run.transcript.append({"role": "tool", "tool": "call_screener", "args": {"action": "wait"},
                                       "result": {"success": True}, "ts": round(_time.monotonic() - run.t0, 2)})
                try:
                    session.interrupt(force=True)
                except Exception:
                    pass
                return
        first = not vm["heard"].strip()
        vm["heard"] += " " + text
        # A recorded greeting ("Hey, it's Sam, can't talk right now, I'll call you back") is the first
        # thing heard after pickup; a live person says hello first.
        # Greetings arrive in pieces ("Hi, reached Valerie." … "I'll get back to you"), so judge everything heard
        # in the first 20 s — unless the contact's first words were a live "hello?".
        elapsed = _time.monotonic() - run.t0 if run.t0 else 0
        if first:
            vm["live_hello"] = len(text.split()) <= 3 and "?" in text
        match = voicemail_greeting_match(vm["heard"])
        if not match and run.t0 and elapsed < 20 and not vm.get("live_hello"):
            match = personal_greeting_match(vm["heard"])
        if match:
            vm["detected"] = True
            # The matched phrase (not what was said) — enough to spot a false positive in the logs.
            log.info("voicemail_match", room=ctx.room.name, phrase=match, after_s=round(elapsed, 1),
                     words=len(vm["heard"].split()))
            asyncio.create_task(_handle_voicemail())

    def _on_user_state(ev) -> None:
        vm["speaking"] = getattr(ev, "new_state", "") == "speaking"
        vm["changed"] = _time.monotonic()

    if call_type == "outbound" and vm_action != "ignore":
        session.on("user_input_transcribed", _on_transcribed)
        session.on("user_state_changed", _on_user_state)

    instructions = build_instructions(cfg, variables, channel=channel)
    tts_prewarmed = False
    if call_type in ("outbound", "inbound"):
        tts_prewarmed = _prewarm_tts(session_kwargs["tts"], ctx)
    log.info("voice_resources_ready", room=ctx.room.name,
             seconds=round(_time.monotonic() - prepare_started, 3),
             vad_prewarmed=bool(ctx.proc.userdata.get("vad_prewarmed")), tts_prewarm_started=tts_prewarmed)
    # Construct providers and warm the voice socket during ringing, but do not listen or speak before answer.
    if call_type == "outbound":
        await _wait_for_sip_answer(ctx)
    else:
        await ctx.wait_for_participant()

    agent = _CallAgent(
        instructions=instructions,
        tools=_build_tools(cfg, run, ctx, session_ref, variables),
    )

    run.t0 = _time.monotonic()
    wall_t0 = _time.time()

    # Stop the clock the moment the caller leaves; the job's own teardown takes ~20 s more.
    def _mark_ended(*_a) -> None:
        if run.ended_wall is None:
            run.ended_wall = _time.time()

    def _on_participant_left(p) -> None:
        from livekit import rtc

        if getattr(p, "kind", None) in (rtc.ParticipantKind.Value("PARTICIPANT_KIND_EGRESS"),
                                        rtc.ParticipantKind.Value("PARTICIPANT_KIND_AGENT")):
            return  # the recorder or another agent leaving isn't the caller hanging up
        _mark_ended()

    ctx.room.on("participant_disconnected", _on_participant_left)
    ctx.room.on("disconnected", _mark_ended)
    session.on("close", _mark_ended)

    def _on_item(ev) -> None:
        try:
            item = getattr(ev, "item", None)
            role = getattr(item, "role", None)
            from app.agent.turn_latency import stage_timings
            timings = stage_timings(getattr(item, "metrics", None))
            if timings:
                log.info("turn_stage_latency", room=ctx.room.name, model=model, role=role, **timings)
                trace.mark("sdk_item_metrics", speech=owning_speech(), role=role,
                           item_id=getattr(item, "id", None), **timings)
            text = (getattr(item, "text_content", None) or "").strip()
            if role not in ("user", "assistant") or not text or text == CALL_CONNECTED_CUE:
                return
            run.transcript.append({"role": role, "text": text, "ts": round(_time.monotonic() - run.t0, 2)})
            # Per-turn trace for diagnosing dropped calls: the agent's words, only a word count for the contact.
            log.info("turn", room=ctx.room.name, role=role, words=len(text.split()),
                     t=round(_time.monotonic() - run.t0, 1), **({"text": text[:80]} if role == "assistant" else {}))
        except Exception as exc:
            log.debug("transcript_capture_failed", error=str(exc))

    session.on("conversation_item_added", _on_item)
    log.info("call_config", room=ctx.room.name, call_type=call_type, model=model,
             has_first_message=bool((cfg.get("first_message") or "").strip()), voicemail_action=vm_action,
             stt_provider="cartesia" if language == "tl" else "deepgram", language=language,
             tts_provider="elevenlabs" if is_elevenlabs_voice(voice_id) else "mistral" if is_mistral_voice(voice_id) and settings.mistral_api_key else "cartesia",
             background_audio=bool(cfg.get("background_audio")), turn_detection="semantic" if turn_detector else "vad",
             preemptive_generation=True, preemptive_tts=True,
             short_sentence_streaming=settings.voice_short_sentence_streaming, trace_enabled=settings.voice_turn_trace,
             fast_identity_turns=settings.voice_fast_identity_turns,
             tuning={k: v for k, v in tuning.items() if k != "pronunciations"})
    session.on("agent_state_changed", lambda ev: log.info("agent_state", room=ctx.room.name,
                                                           state=getattr(ev, "new_state", "")))
    session.on("error", lambda ev: log.warning("session_error", room=ctx.room.name,
                                               error=str(getattr(ev, "error", ev))[:300]))
    session.on("close", lambda ev: log.info("session_closed", room=ctx.room.name,
                                            reason=str(getattr(ev, "reason", "")), error=str(getattr(ev, "error", "") or "")[:300]))
    session_started = _time.monotonic()
    await session.start(agent, room=ctx.room)
    log.info("voice_session_ready", room=ctx.room.name,
             after_answer_seconds=round(_time.monotonic() - session_started, 3))

    recorder = await _start_worker_recording(ctx, session, metadata)

    # Answering-machine detection: LiveKit's AMD classifies the first seconds after pickup (human / voicemail /
    # IVR / mailbox full) and holds the agent's opening line until it decides. Phrase matching stays as backup.
    if call_type == "outbound" and vm_action != "ignore" and settings.openai_api_key:
        try:
            from livekit.agents.voice.amd import AMD

            detector = AMD(
                session,
                llm=openai.LLM(model="gpt-4.1-mini", api_key=settings.openai_api_key, base_url=settings.openai_base_url),
                stt=deepgram.STT(model="nova-3", language="en", api_key=settings.deepgram_api_key),
                interrupt_on_machine=True, ivr_detection=False, suppress_compatibility_warning=True,
                wait_until_finished=(vm_action == "leave_message"),
                # People often answer without speaking; don't hold the opening line longer than ~3 s.
                detection_options={"no_speech_threshold": 3.0},
            )
            await detector.__aenter__()
            # Don't hold the opening line for AMD's verdict (that cost ~6 s on live pickups); it keeps listening
            # and hangs up / leaves the message as soon as it hears a machine.
            # Private SDK method: verify on any livekit-agents upgrade — if it disappears, AMD will hold the
            # opening line again; this warning makes that regression visible in logs instead of silent.
            act = getattr(session, "_activity", None)
            if act is not None and hasattr(act, "_resume_authorization"):
                act._resume_authorization()
            else:
                log.warning("amd_resume_authorization_unavailable",
                            hint="livekit-agents private API changed; opening line may be held for AMD verdict")

            async def _amd_flow() -> None:
                try:
                    result = await detector.execute()
                    cat = getattr(result.category, "value", str(result.category))
                    log.info("amd_result", room=ctx.room.name, category=cat, reason=result.reason[:200],
                             delay=round(result.delay, 2))
                    run.transcript.append({"role": "tool", "tool": "answer_detection",
                                           "args": {"result": cat, "reason": result.reason[:160]},
                                           "result": {"success": True}, "ts": round(_time.monotonic() - run.t0, 2)})
                    if result.is_machine and not vm["detected"]:
                        await asyncio.sleep(1.5)  # a screener's words may still be on their way to the transcript
                        if screen["seen"] or "screen" in (result.reason or "").lower():
                            log.info("amd_machine_is_screener", room=ctx.room.name)
                            return
                        vm["detected"] = True
                        await _handle_voicemail()
                except Exception as exc:
                    log.warning("amd_failed", room=ctx.room.name, error=str(exc)[:200])
                finally:
                    try:
                        await detector.aclose()
                    except Exception:
                        pass

            asyncio.create_task(_amd_flow())
        except Exception as exc:
            log.warning("amd_unavailable", error=str(exc)[:200])

    bg_state: dict = {"task": None, "track": None}
    if cfg.get("background_audio") and call_type == "outbound":
        bg_state["task"] = asyncio.create_task(_play_continuous_bg(ctx.room, bg_state))

    # Hard cap on call length: ask the agent to wrap up, then hang up.
    max_s = int(cfg.get("max_duration_seconds") or 600)

    async def _enforce_max_duration() -> None:
        await asyncio.sleep(max(30, max_s - 20))
        if run.handed_off:
            return  # the caller is talking to the team now
        try:
            session.generate_reply(instructions="We're out of time. Politely wrap up and say goodbye now.")
        except Exception:
            pass
        await asyncio.sleep(20)
        await _delete_room(ctx.room.name)

    timer = asyncio.create_task(_enforce_max_duration())

    # Phone calls: hang up after a long silence (a voicemail that's recording, or a dead line) instead of
    # sitting on the line — and billing — until the carrier cuts it off.
    silence = {"agent": "", "user": "", "since": _time.monotonic(), "checked_in": False}

    def _activity(kind: str):
        def _on(ev) -> None:
            state = getattr(ev, "new_state", "")
            prev, silence[kind] = silence[kind], state
            # Only speech (or the agent working on a reply) counts as activity. The contact going "away"
            # after a quiet spell is not activity — counting it restarted the clock and left ~40 s of dead air.
            if state in ("speaking", "thinking") or prev in ("speaking", "thinking"):
                silence["since"] = _time.monotonic()
                if kind == "user" and state == "speaking":
                    silence["checked_in"] = False
        return _on

    CHECK_IN_AFTER, HANG_UP_AFTER = 7.0, 8.0  # quiet seconds: check in once, then hang up
    SCREENER_WAIT = 75.0  # how long to hold for a screened person before giving up

    async def _hang_up_on_silence() -> None:
        while True:
            await asyncio.sleep(1)
            if vm["detected"] or session_ref.get("voicemail_detected"):
                continue  # voicemail handler owns its silent wait and hangup
            if screen["holding"]:
                # A screener is holding the line while the person decides (often 30-50 s). Quiet is expected;
                # don't check in or hang up, unless the person never comes on.
                if _time.monotonic() - (screen["since"] or run.t0) > SCREENER_WAIT:
                    log.info("screener_timeout", room=ctx.room.name)
                    run.outcome = run.outcome or "screened"
                    _mark_ended()
                    await wait_for_voicemail_minimum(run.t0, cfg.get("voice_tuning"))
                    await _delete_room(ctx.room.name)
                    return
                silence["since"] = _time.monotonic()
                continue
            if run.transferring or run.handed_off:
                silence["since"] = _time.monotonic()  # on hold for a warm transfer, or handed off
                continue
            quiet = silence["agent"] in ("listening", "") and silence["user"] != "speaking"
            if not quiet:
                continue
            idle = _time.monotonic() - silence["since"]
            if not silence["checked_in"] and idle > CHECK_IN_AFTER:
                silence["checked_in"] = True
                log.info("silence_check_in", room=ctx.room.name, seconds=round(idle, 1))
                try:
                    session.say("Hello? Can you hear me okay?", allow_interruptions=True)
                except Exception as exc:
                    log.warning("silence_check_in_failed", error=str(exc)[:120])
                continue
            if silence["checked_in"] and idle > HANG_UP_AFTER:
                log.info("silence_hangup", room=ctx.room.name, seconds=round(idle, 1))
                run.transcript.append({"role": "tool", "tool": "end_call", "args": {"reason": "silence"},
                                       "result": {"success": True}, "ts": round(_time.monotonic() - run.t0, 2)})
                _mark_ended()
                await wait_for_voicemail_minimum(run.t0, cfg.get("voice_tuning"))  # never under 7 s connected
                await _delete_room(ctx.room.name)
                return

    silence_task = None
    if call_type in ("outbound", "inbound"):
        session.on("agent_state_changed", _activity("agent"))
        session.on("user_state_changed", _activity("user"))
        silence_task = asyncio.create_task(_hang_up_on_silence())

    finished: dict = {"task": None}

    async def _shutdown() -> None:
        # Session close and job shutdown both land here; they share one run and both wait for it to finish.
        if finished["task"] is None:
            finished["task"] = asyncio.ensure_future(_finish())
        await asyncio.shield(finished["task"])

    async def _finish() -> None:
        timer.cancel()
        if silence_task:
            silence_task.cancel()
        task = bg_state.get("task")
        if task:
            task.cancel()
        # An outcome report already on its way (end_call / transfer): let it land, retry below if it failed.
        if run.post_task is not None and not run.post_task.done():
            await asyncio.wait({run.post_task}, timeout=6)
        from app.agent.runtime import is_voicemail_text, person_answered, reconcile_outcome
        if run.outcome:
            outcome = reconcile_outcome(run.outcome, run.transcript) or run.outcome
        elif person_answered(run.transcript):
            outcome = "completed"
        elif any(t.get("role") == "user" and is_voicemail_text(t.get("text", "")) for t in run.transcript):
            outcome = "voicemail"
        else:
            outcome = "no_answer"
        if screen["seen"] and not screen["passed"] and outcome in ("no_answer", "voicemail"):
            outcome = "screened"
        await _post_run_outcome(run, outcome)  # first: it's what matters if the job is cut short
        if recorder is not None:
            saved = await recorder.finish()
            if metadata.get("worker_recording"):
                await _recording_state(metadata, ctx.room.name, "ready" if saved else "failed")
        # If the session died on its own (e.g. a voice error), don't leave the caller on dead air.
        if call_type != "web" and ctx.room.remote_participants and not run.handed_off:
            await _delete_room(ctx.room.name)

    ctx.add_shutdown_callback(_shutdown)

    # Report as soon as the conversation ends — the job's own teardown can take ~20 s, and a restart in that
    # window would lose the outcome (the call would look "in progress" forever).
    def _on_session_close(_ev) -> None:
        async def _later() -> None:
            await asyncio.sleep(1.0)  # let the last transcript items land
            await _shutdown()
        _keep(asyncio.create_task(_later()))

    session.on("close", _on_session_close)

    # When the browser tester leaves, end the job so the outcome is saved promptly.
    if call_type == "web":
        def _on_left(_p) -> None:
            if not ctx.room.remote_participants:
                asyncio.create_task(_delete_room(ctx.room.name))
        ctx.room.on("participant_disconnected", _on_left)

    first = render_vars(fixed_opening if call_type == "outbound" else cfg.get("first_message", ""), variables).strip()
    if call_type == "outbound":
        # Let the contact finish their "Hello?" (or ~1.2 s of quiet), then speak the line written during ringing.
        t_open = _time.monotonic()
        heard = False
        while _time.monotonic() - t_open < 3.0:
            if vm["detected"]:
                break
            if silence["user"] == "speaking":
                heard = True
            elif heard or _time.monotonic() - t_open > 1.2:
                break
            await asyncio.sleep(0.05)
        if not first and opening_task is not None:
            try:
                first = await asyncio.wait_for(opening_task, timeout=2.0)
            except Exception:
                first = ""
        log.info("opening_line", room=ctx.room.name, waited=round(_time.monotonic() - t_open, 2),
                 prepared=bool(first), heard_hello=heard)
        if vm["detected"]:
            return
    # Some models need a user turn before they'll answer at all (see NEEDS_USER_TURN).
    cue = {"user_input": CALL_CONNECTED_CUE} if model in NEEDS_USER_TURN else {}
    if first:
        from app.agent.runtime import strip_tool_mentions
        from app.agent.speech_guard import clean

        first = strip_tool_mentions(clean(first))  # the drafted opening skips the reply filter
    opening["pending"] = False
    try:
        if first:
            session.say(first, allow_interruptions=True)
        elif call_type == "inbound":
            session.generate_reply(instructions="You're answering an incoming phone call. Greet the caller warmly and ask how you can help.", **cue)
        else:
            session.generate_reply(instructions="Greet the contact and begin the conversation.", **cue)
    except RuntimeError as exc:  # they hung up before the opening line (the session already closed)
        log.info("opening_skipped", room=ctx.room.name, reason=str(exc)[:80])


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

async def _run_inbound(ctx: JobContext) -> None:
    caller = await ctx.wait_for_participant()
    attrs = dict(getattr(caller, "attributes", {}) or {})
    to_number = attrs.get("sip.trunkPhoneNumber", "")
    from_number = attrs.get("sip.phoneNumber", "")
    routed = None
    try:
        resp = await _api_post("/internal/inbound-call",
                               json={"to": to_number, "from_number": from_number, "room": ctx.room.name}, timeout=8.0)
        if resp.status_code == 200:
            routed = resp.json()
    except Exception as exc:
        log.warning("inbound_route_failed", error=str(exc), to=to_number)
    if not routed:
        # Nobody answers this number (no live inbound campaign, or out of credits): hang up.
        log.info("inbound_unrouted", to=to_number, room=ctx.room.name)
        await _delete_room(ctx.room.name)
        return
    log.info("inbound_call", to=to_number, room=ctx.room.name, agent=(routed.get("agent") or {}).get("name"))
    await _run_configurable(ctx, routed)


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

    # Inbound phone call (the SIP dispatch rule sends us here): find who answers the dialed number.
    try:
        job_meta = json.loads(getattr(ctx.job, "metadata", "") or "{}")
    except json.JSONDecodeError:
        job_meta = {}
    if job_meta.get("call_type") == "inbound":
        await _run_inbound(ctx)
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
        vad=_job_vad(ctx),
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
        except Exception as exc:  # never let transcript capture break the call
            log.debug("transcript_capture_failed", error=str(exc))

    session.on("conversation_item_added", _on_conversation_item)

    await session.start(agent, room=ctx.room)
    recorder = await _start_worker_recording(ctx, session, metadata)

    # Announce call_started to Live Monitor
    import time as _ts

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
        if not state.outcome_posted:
            await _post_call_outcome(state, outcome)
        if recorder is not None:
            saved = await recorder.finish()
            if metadata.get("worker_recording"):
                await _recording_state(metadata, ctx.room.name, "ready" if saved else "failed")

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
            prewarm_fnc=_prewarm_process,
            shutdown_process_timeout=90.0,
            agent_name=settings.livekit_agent_name or "closer",
            **extra,
        )
    )
