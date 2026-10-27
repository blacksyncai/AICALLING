"""
OpenAI helpers: the text playground (same prompt + tools as the voice agent)
and post-call analysis (summary, outcome, sentiment, extracted fields).
"""

from __future__ import annotations

import json
from contextvars import ContextVar

import httpx
import structlog

from app.agent.runtime import (
    build_instructions, email_was_given, normalize_email, render_vars, strip_tool_mentions,
)
from app.config import settings
from app.models.call_log import CALL_OUTCOMES
from app.services import calendar

log = structlog.get_logger(__name__)

STANDARD_EXTRACTION_FIELDS = (
    {"name": "lead_intent", "description": "What the contact wants or intends (e.g. buy, sell, book, just browsing)"},
    {"name": "timeline", "description": "When the contact plans to act, in their words"},
    {"name": "key_objections", "description": "Main concerns or objections the contact raised"},
    {"name": "next_action", "description": "The agreed or recommended next step"},
)


class LLMNotConfigured(RuntimeError):
    pass


# Optional token meter: set it (a dict) around a block of calls to add up what they used, per model.
usage_meter: ContextVar[dict | None] = ContextVar("usage_meter", default=None)


def _meter(model: str | None, data: dict) -> None:
    meter = usage_meter.get()
    usage = data.get("usage") if isinstance(data, dict) else None
    if meter is None or not isinstance(usage, dict):
        return
    row = meter.setdefault(model or "unknown", {"input": 0, "output": 0, "calls": 0})
    row["input"] += int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    row["output"] += int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    row["calls"] += 1


async def _chat(payload: dict, timeout: float = 45.0) -> dict:
    from app.agent.models import llm_endpoint

    api_key, base_url, sends_temperature = llm_endpoint(payload.get("model"))
    if not api_key:
        raise LLMNotConfigured("No API key is set on the backend for this model.")
    if not sends_temperature:
        payload = {k: v for k, v in payload.items() if k != "temperature"}
    from app.agent.models import GROQ_MODELS

    if payload.get("model") in GROQ_MODELS:
        payload = {**payload, "reasoning_effort": "none"}  # no hidden thinking: it's only latency here
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"LLM error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        _meter(payload.get("model"), data)
        return data


def _tool_specs(cfg: dict) -> list[dict]:
    outcomes = list(CALL_OUTCOMES)
    tools = [{
        "type": "function",
        "function": {
            "name": "end_call",
            "description": "Hang up after saying goodbye.",
            "parameters": {
                "type": "object",
                "properties": {"outcome": {"type": "string", "enum": outcomes}},
                "required": ["outcome"],
            },
        },
    }]
    if cfg.get("enable_booking"):
        tools += [
            {
                "type": "function",
                "function": {
                    "name": "check_availability",
                    "description": "Get open appointment times. Call again for other options — each call returns "
                                   "times not offered yet.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "preferred_date": {"type": "string", "description": "YYYY-MM-DD, empty for the soonest"},
                            "time_of_day": {"type": "string", "enum": ["", "morning", "afternoon", "evening"]},
                            "time": {"type": "string", "description": "A specific time asked about, 24h HH:MM"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "book_appointment",
                    "description": "Book one of the slots returned by check_availability.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "slot": {"type": "string", "description": "'first', 'second', or the slot label"},
                            "email": {"type": "string", "description": "Exactly as the contact said it. Never guess."},
                        },
                        "required": ["slot", "email"],
                    },
                },
            },
        ]
    return tools


async def playground_reply(cfg: dict, variables: dict, history: list[dict], state: dict,
                           channel: str = "chat") -> dict:
    """
    One assistant turn for the text playground.
    history: [{"role": "user"|"assistant", "content": str}]
    state:   opaque dict round-tripped by the client (offered slots etc.)
    Returns {"reply", "tool_events", "ended", "outcome", "state"}.
    """
    messages: list[dict] = [{"role": "system", "content": build_instructions(cfg, variables, channel=channel)}]
    first = render_vars(cfg.get("first_message", ""), variables).strip()
    opening = ""
    if first and (not history or history[0].get("role") != "assistant"):
        messages.append({"role": "assistant", "content": first})
        opening = first
    if not history and opening:
        # Nothing said yet: the saved opening is the agent's first turn.
        return {"reply": "", "opening": opening, "tool_events": [], "ended": False, "outcome": None, "state": state}
    messages += [{"role": m["role"], "content": m["content"]} for m in history if m.get("content")]

    tool_events: list[dict] = []
    ended, outcome = False, None
    tools = _tool_specs(cfg)

    for _ in range(4):  # allow a few tool round-trips
        data = await _chat({
            "model": cfg.get("llm_model") or settings.llm_model,
            "temperature": cfg.get("temperature", 0.5),
            "messages": messages,
            "tools": tools,
        })
        msg = data["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            return {"reply": strip_tool_mentions(msg.get("content") or ""), "tool_events": tool_events,
                    "ended": ended, "outcome": outcome, "state": state}

        msg_index = len(messages)
        messages.append(msg)
        spoken = strip_tool_mentions(msg.get("content") or "")
        failed = False
        for call in calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if name == "end_call":
                if args.get("outcome") == "meeting_booked" and not state.get("booked"):
                    result = "Not ended: no meeting is booked yet. Finish booking first, or pick another outcome."
                else:
                    ended, outcome = True, args.get("outcome", "completed")
                    result = "Call ended."
            elif name == "check_availability":
                slots = await calendar.fetch_slots(
                    args.get("preferred_date", ""), cfg.get("calcom_event_type_id"), cfg.get("calcom_api_key"),
                    cfg.get("calendar_timezone"), time_of_day=args.get("time_of_day", ""), time=args.get("time", ""),
                    exclude={x["start"] for x in state.get("slots") or []}, allow_mock=True)
                state["slots"] = calendar.remember_slots(state.get("slots") or [], slots)
                if slots:
                    state["last_found"] = slots
                result = ("Open: " + calendar.spoken_offer(slots, cfg.get("calendar_timezone"))
                          + ". Offer them like that: day and time only. To book, pass one of these labels: "
                          + "; ".join(s["label"] for s in slots)) if slots else \
                    "No new openings for that. Offer a different day or time of day."
            elif name == "book_appointment":
                slot = calendar.pick_slot(state.get("slots") or [], args.get("slot", ""), cfg.get("calendar_timezone"),
                                          state.get("last_found"))
                user_turns = [m["content"] for m in history if m.get("role") == "user"]
                if not state.get("slots"):
                    result = "No slots offered yet — call check_availability first."
                elif not slot:
                    result = ("Which slot? Offered: " + "; ".join(x["label"] for x in state["slots"])
                              + ". Ask the contact to pick one, then pass its exact label.")
                elif not email_was_given(args.get("email", ""), user_turns, variables.get("email", "")):
                    result = ("Not booked: the contact hasn't given their email yet. "
                              "Ask for it and have them confirm the spelling — never guess it.")
                else:
                    link = await calendar.create_booking(slot["start"], normalize_email(args.get("email", "")),
                                                         variables.get("full_name") or variables.get("name", ""),
                                                         cfg.get("calcom_event_type_id"),
                                                         cfg.get("calcom_api_key"), cfg.get("calendar_timezone"), allow_mock=True)
                    if link:
                        state["booked"] = slot["label"]
                        result = f"Booked {slot['label']}. Confirm exactly this time with the contact. Link: {link}"
                    else:
                        result = "Not booked: no confirmation received. Do not claim success."
            else:
                result = "Unknown tool."
            failed = failed or result.startswith(("Not ", "Which slot", "No slots", "Unknown"))
            tool_events.append({"tool": name, "args": args, "result": result})
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
        # Text written alongside a failed tool call may claim success; let the model
        # answer the real result instead.
        if failed:
            messages[msg_index] = {**msg, "content": None}
        elif ended:
            return {"reply": spoken, "tool_events": tool_events, "ended": True, "outcome": outcome, "state": state}
        # Loop again so the model can speak after the tool result.

    return {"reply": "", "tool_events": tool_events, "ended": ended, "outcome": outcome, "state": state}


def _transcript_text(transcript: list[dict]) -> str:
    lines = []
    for t in transcript or []:
        role = t.get("role")
        if role in ("assistant", "agent"):
            lines.append(f"AGENT: {t.get('text', '')}")
        elif role in ("user", "caller"):
            lines.append(f"CONTACT: {t.get('text', '')}")
        elif role == "tool":
            lines.append(f"[tool {t.get('tool')}: {json.dumps(t.get('args', {}))}]")
    return "\n".join(lines)


async def analyze_call(transcript: list[dict], extraction_fields: list[dict] | None,
                       success_criteria: str = "") -> dict | None:
    """Summarize a finished call. Returns None when there's nothing to analyze or no key."""
    if not settings.openai_api_key or not transcript:
        return None
    text = _transcript_text(transcript)
    if not text.strip():
        return None

    # Every call yields these standard fields, plus whatever the agent asks for.
    fields = list(STANDARD_EXTRACTION_FIELDS)
    seen = {f["name"] for f in fields}
    for f in extraction_fields or []:
        if f.get("name") and f["name"] not in seen:
            fields.append(f)
            seen.add(f["name"])
    field_spec = "\n".join(f'- "{f.get("name")}": {f.get("description", "")}' for f in fields if f.get("name"))
    from app.agent.runtime import contact_turns, person_answered, reconcile_outcome

    answered = person_answered(transcript)
    facts = (f"FACTS: the contact spoke {len(contact_turns(transcript))} time(s); "
             + ("a live person answered, so the outcome can NOT be no_answer or voicemail."
                if answered else "no live conversation was detected."))
    prompt = f"""Analyze this phone call transcript between an AI agent and a contact.

{facts}

Outcome definitions (pick the single best one):
- meeting_booked: a meeting/appointment time was confirmed.
- qualified: the contact meets the agent's criteria but nothing was booked yet.
- interested: the contact responded positively to what the agent offered: said yes, wanted to hear more,
  asked how it works / what it costs / next steps, or agreed to receive details ("yeah, send me that", "sure,
  I'd like a valuation", "how much is it?", "sounds good, tell me more"). NOT interested: only confirming who
  they are, asking who's calling or why, or answering a question before the offer was even made.
- callback: a follow-up is needed: a live person asked to be called back later, said it's a bad time / they're
  busy / driving, wants to think about it or check with someone, or asked for a text or email to look at later.
- not_interested: declined or said no.
- not_qualified: doesn't fit (wrong size, budget, area, etc.).
- do_not_call: asked to never be called again / remove them from the list.
- wrong_number: the person isn't who the agent was trying to reach.
- language_barrier: a live person answered but couldn't follow or reply in the agent's language (answered in
  another language, said they don't speak it, or clearly couldn't understand). Use this instead of
  not_interested when the "no" was really about language.
- hung_up: a live person answered and hung up during or right after the agent's opening, before responding to
  what the agent was calling about. Not when they declined first (not_interested) or talked for a while (completed).
- transferred: handed to a human.
- voicemail: a voicemail greeting/recording answered and no live person ever replied to the agent. This
  includes personal recorded greetings ("Hey, it's Sam, can't talk right now, I'll call you back / text me")
  — that is voicemail, NOT callback. Signs: the contact's only words are one monologue right after pickup
  that doesn't respond to anything the agent said.
- no_answer: ONLY when nobody answered at all; never when the contact said anything.
- completed: a live conversation happened but the contact never reacted to what the agent was calling about
  (e.g. the call dropped mid-pitch) and none of the above fits.

Once the contact reacted to the offer, pick the outcome that matches that reaction (interested, callback,
not_interested, ...); don't fall back to completed. Don't invent interest: a "maybe later" is callback, not
interested.

Return JSON with keys:
- "summary": 2-3 sentence summary of what happened.
- "outcome": one of {list(CALL_OUTCOMES)}.
- "sentiment": one of ["positive", "neutral", "negative"] (the contact's attitude).
- "successful": true/false. {('Success criteria: ' + success_criteria) if success_criteria else ''}
- "extracted": object with these keys (null when not mentioned):
{field_spec or '  (none)'}

TRANSCRIPT:
{text}"""
    try:
        data = await _chat({
            "model": settings.analysis_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        }, timeout=60.0)
        result = json.loads(data["choices"][0]["message"]["content"])
        if result.get("outcome") not in CALL_OUTCOMES:
            result["outcome"] = "completed"
        result["outcome"] = reconcile_outcome(result["outcome"], transcript)
        return result
    except Exception as exc:
        log.warning("call_analysis_failed", error=str(exc))
        return None
