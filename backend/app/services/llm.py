"""
OpenAI helpers: the text playground (same prompt + tools as the voice agent)
and post-call analysis (summary, outcome, sentiment, extracted fields).
"""

from __future__ import annotations

import json

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


async def _chat(payload: dict, timeout: float = 45.0) -> dict:
    from app.agent.models import llm_endpoint

    api_key, base_url, sends_temperature = llm_endpoint(payload.get("model"))
    if not api_key:
        raise LLMNotConfigured("No API key is set on the backend for this model.")
    if not sends_temperature:
        payload = {k: v for k, v in payload.items() if k != "temperature"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"LLM error {resp.status_code}: {resp.text[:300]}")
        return resp.json()


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
                    "description": "Get open appointment slots on/after a date.",
                    "parameters": {
                        "type": "object",
                        "properties": {"preferred_date": {"type": "string", "description": "YYYY-MM-DD"}},
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


async def playground_reply(cfg: dict, variables: dict, history: list[dict], state: dict) -> dict:
    """
    One assistant turn for the text playground.
    history: [{"role": "user"|"assistant", "content": str}]
    state:   opaque dict round-tripped by the client (offered slots etc.)
    Returns {"reply", "tool_events", "ended", "outcome", "state"}.
    """
    messages: list[dict] = [{"role": "system", "content": build_instructions(cfg, variables, channel="chat")}]
    first = render_vars(cfg.get("first_message", ""), variables).strip()
    if first and (not history or history[0].get("role") != "assistant"):
        messages.append({"role": "assistant", "content": first})
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
                slots = await calendar.fetch_slots(args.get("preferred_date", ""), cfg.get("calcom_event_type_id"),
                                             cfg.get("calcom_api_key"), cfg.get("calendar_timezone"))
                state["slots"] = calendar.remember_slots(state.get("slots") or [], slots)
                result = "Open slots: " + "; ".join(s["label"] for s in slots)
            elif name == "book_appointment":
                slot = calendar.pick_slot(state.get("slots") or [], args.get("slot", ""))
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
                    state["booked"] = slot["label"]
                    link = await calendar.create_booking(slot["start"], normalize_email(args.get("email", "")),
                                                         variables.get("full_name") or variables.get("name", ""),
                                                         cfg.get("calcom_event_type_id"),
                                                         cfg.get("calcom_api_key"), cfg.get("calendar_timezone"))
                    result = f"Booked {slot['label']}. Confirm exactly this time with the contact." + (f" Link: {link}" if link else "")
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
- interested: positive interest, wants more info or a follow-up.
- callback: a live person, replying to the agent, asked to be called back later / said it's a bad time.
- not_interested: declined or said no.
- not_qualified: doesn't fit (wrong size, budget, area, etc.).
- do_not_call: asked to never be called again / remove them from the list.
- wrong_number: the person isn't who the agent was trying to reach.
- transferred: handed to a human.
- voicemail: a voicemail greeting/recording answered and no live person ever replied to the agent. This
  includes personal recorded greetings ("Hey, it's Sam, can't talk right now, I'll call you back / text me")
  — that is voicemail, NOT callback. Signs: the contact's only words are one monologue right after pickup
  that doesn't respond to anything the agent said.
- no_answer: ONLY when nobody answered at all; never when the contact said anything.
- completed: a live conversation happened but none of the above fits (e.g. the contact hung up mid-call
  or the call ended before a clear result).

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
