"""
Shared runtime helpers for configurable agents.

Used by the API (text playground, post-call analysis) and by the LiveKit voice
worker, so a prompt behaves the same in chat as on a real call.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def render_vars(text: str, variables: dict | None) -> str:
    """Replace {{var}} placeholders. Unknown vars become a neutral fallback."""
    variables = {k: v for k, v in (variables or {}).items() if v not in (None, "")}

    def _sub(m: re.Match) -> str:
        key = m.group(1)
        if key in variables:
            return str(variables[key])
        return {"name": "there", "company": "your company"}.get(key, "")

    return _VAR_RE.sub(_sub, text or "")


def agent_to_runtime(agent, *, secrets: bool = False) -> dict:
    """Serialize an Agent row into the config the voice worker consumes.

    secrets=True adds the decrypted Cal.com key — only for server-side use (the private
    /internal endpoint and the playground), never for room metadata, which callers can read.
    """
    cfg = {
        "id": str(agent.id),
        "name": agent.name,
        "system_prompt": agent.system_prompt or "",
        "first_message": agent.first_message or "",
        "knowledge_base": agent.knowledge_base or "",
        "language": agent.language or "en",
        "llm_model": agent.llm_model or "gpt-4.1-nano",
        "temperature": agent.temperature if agent.temperature is not None else 0.5,
        "voice_id": agent.voice_id or "",
        "voice_speed": agent.voice_speed or 1.0,
        "voice_tuning": getattr(agent, "voice_tuning", None) or {},
        "background_audio": bool(agent.background_audio),
        "enable_booking": bool(agent.enable_booking),
        "calcom_event_type_id": agent.calcom_event_type_id or "",
        "calendar_timezone": getattr(agent, "calendar_timezone", None) or "",
        "calcom_key_set": bool(getattr(agent, "calcom_api_key_enc", None)),
        "transfer_number": agent.transfer_number or "",
        "voicemail_action": getattr(agent, "voicemail_action", None) or "hang_up",
        "voicemail_message": getattr(agent, "voicemail_message", None) or "",
        "max_duration_seconds": agent.max_duration_seconds or 600,
        "ai_disclosure": getattr(agent, "ai_disclosure", None) is not False,
        "business_name": (getattr(agent, "builder", None) or {}).get("business_name") or "",
    }
    if secrets:
        from app.services.secret_store import decrypt_value

        cfg["calcom_api_key"] = decrypt_value(getattr(agent, "calcom_api_key_enc", None))
    return cfg


def build_instructions(cfg: dict, variables: dict | None, channel: str = "phone") -> str:
    """Full system prompt: user prompt + knowledge base + tool guidance."""
    parts = [render_vars(cfg.get("system_prompt", ""), variables).strip()]

    kb = (cfg.get("knowledge_base") or "").strip()
    if kb:
        parts.append(
            "# KNOWLEDGE BASE\nUse this as your source of truth. Do not invent facts beyond it.\n"
            + render_vars(kb, variables)
        )

    if cfg.get("ai_disclosure"):
        company = cfg.get("business_name") or "the business you represent"
        parts.append(
            "# AI DISCLOSURE\nIf asked whether you're an AI or a real person, say honestly that "
            f"you're an AI assistant for {company}. Never claim to be human."
        )

    hidden = {"crm_context", "crm_context_at", "bs_deal", "bs_install", "bs_tries"}
    ctx_lines = [f"- {k}: {v}" for k, v in (variables or {}).items() if v not in (None, "") and k not in hidden]
    if ctx_lines:
        parts.append("# CONTACT CONTEXT\n" + "\n".join(ctx_lines))
    crm = str((variables or {}).get("crm_context") or "").strip()
    if crm:
        parts.append(
            "# WHAT THE CRM SAYS ABOUT THIS CONTACT\n"
            "Internal notes and history from the team's CRM. Use them to sound informed and personal "
            "(reference their business, past conversations or why you're calling back) but never read notes "
            "out loud, quote them, or mention a CRM, notes or research. If something here conflicts with "
            "what the contact says, trust the contact.\n" + crm[:1500])

    tools = ["- end_call(outcome): hangs up. Say your goodbye in the same reply, then call it. "
             "Pick the outcome that best describes the call."]
    if cfg.get("enable_booking"):
        tools.append("- check_availability(preferred_date): get real open slots. Only offer slots it returns.")
        tools.append("- book_appointment(slot, email): only AFTER the contact has explicitly picked one offered slot "
                     "AND told you their email. Pass the slot's exact label from check_availability. "
                     "Never say a meeting is booked until this tool confirms it.")
    if cfg.get("transfer_number") and channel == "phone":
        tools.append("- transfer_call(): hand the caller to a human when they ask for one or you can't help.")
    tools.append("Never say a tool's name or its arguments out loud — just use the tool.")
    parts.append("# TOOLS\n" + "\n".join(tools))

    now = datetime.now(timezone.utc)
    days = ", ".join(
        (now + timedelta(days=i)).strftime("%a %b %-d = %Y-%m-%d") for i in range(1, 15)
    )
    parts.append(
        f"# CONTEXT\nToday is {now.strftime('%A, %B %-d, %Y')} (UTC). Channel: {channel}.\n"
        f"Upcoming dates (use these, don't calculate): {days}."
    )
    return "\n\n".join(p for p in parts if p)


def lead_variables(lead) -> dict:
    """Template variables available for a lead (incl. custom CSV columns)."""
    if lead is None:
        return {}
    v = {
        "name": (lead.name or "").split(" ")[0] if lead.name else "",
        "full_name": lead.name or "",
        "company": lead.company or "",
        "phone": lead.phone or "",
        "email": lead.email or "",
        "role": lead.role or "",
    }
    for k, val in (getattr(lead, "custom_fields", None) or {}).items():
        v.setdefault(str(k), val)
    return v


_TOOL_NAMES = ("end_call", "check_availability", "book_appointment", "transfer_call")
_OUTCOME_TOKENS = ("meeting_booked", "not_qualified", "not_interested", "no_answer", "do_not_call", "wrong_number")


def strip_tool_mentions(text: str) -> str:
    """Remove tool names / outcome codes the model sometimes echoes into its spoken reply."""
    for name in _TOOL_NAMES + _OUTCOME_TOKENS:
        text = re.sub(rf"\s*\(?`?{name}(\([^)]*\))?`?\)?\.?", "", text)
    text = re.sub(r"\s*\bfunctions\.?\s*$", "", text)  # stray tool-call prefix the model sometimes leaks
    return text.strip()


def _normalize_email_speech(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"\s+at\s+", "@", t)
    t = re.sub(r"\s+dot\s+", ".", t)
    return re.sub(r"\s+", "", t)


def normalize_email(email: str) -> str:
    """'Jamie at Globex dot com' -> 'jamie@globex.com'."""
    return _normalize_email_speech(f" {email or ''} ").strip(".")


def email_was_given(email: str, user_turns: list[str], known_email: str = "") -> bool:
    """True if the contact actually said (or spelled) this email, or it's the one on file."""
    email = normalize_email(email)
    if not email or "@" not in email:
        return False
    if known_email and email == known_email.strip().lower():
        return True
    return any(email in _normalize_email_speech(t) for t in user_turns)


# ── Did a person actually pick up? ───────────────────────────────────────────

_VOICEMAIL_HINTS = (
    "leave a message", "leave your message", "after the tone", "after the beep", "voicemail", "voice mail",
    "not available", "unavailable", "record your message", "mailbox", "at the tone", "please leave",
    "has not set up", "is not accepting", "reached the", "the person you are calling", "the number you have dialed",
    "can't take your call", "cannot take your call", "can't come to the phone", "unable to answer", "unable to take",
    "please record", "automated voice messaging", "forwarded to an automated", "voice messaging system",
    "not available to take",
    # Personal greetings
    "can't get to the phone", "can't answer", "can't talk right now", "i'll call you back", "i will call you back",
    "call you back as soon", "text me", "send me a text", "away from my phone", "you've reached", "you have reached",
)

# How people record their own greeting. Only trusted when it's the contact's very first, long-ish
# utterance right after pickup (a live person says "Hello?" first).
_PERSONAL_GREETING = (
    "can't get to the phone", "can't come to the phone", "can't answer", "can't talk right now", "can't talk at the moment",
    "unable to come to the phone", "unable to answer", "i'll call you back", "i will call you back", "call you back as soon",
    "get back to you as soon", "text me", "send me a text", "shoot me a text", "away from my phone", "not available right now",
    "you've reached", "you have reached", "sorry i missed your call", "sorry i missed you",
)


def looks_like_personal_greeting(text: str) -> bool:
    t = (text or "").lower().replace("’", "'")
    return len(t.split()) >= 7 and any(h in t for h in _PERSONAL_GREETING)

# Phrases only an answering machine says — strict, because hearing one ends a live call.
_VOICEMAIL_STRICT = (
    "leave a message", "leave your message", "after the tone", "after the beep", "at the tone", "voicemail",
    "voice mail", "record your message", "please record", "mailbox", "automated voice messaging",
    "voice messaging system", "not available to take your call", "can't take your call", "cannot take your call",
    "can't come to the phone", "cannot come to the phone",
)


def is_voicemail_greeting(text: str) -> bool:
    t = (text or "").lower().replace("’", "'")
    return any(h in t for h in _VOICEMAIL_STRICT)

NO_CONVERSATION_OUTCOMES = ("no_answer", "voicemail")


def is_voicemail_text(text: str) -> bool:
    t = (text or "").lower()
    return any(h in t for h in _VOICEMAIL_HINTS)


def contact_turns(transcript: list[dict] | None) -> list[str]:
    return [(t.get("text") or "").strip() for t in transcript or []
            if t.get("role") in ("user", "caller") and (t.get("text") or "").strip()]


def person_answered(transcript: list[dict] | None) -> bool:
    """True when a live person spoke on the call (not just a voicemail greeting or silence)."""
    if any(t.get("role") == "tool" and t.get("tool") == "voicemail" for t in transcript or []):
        return False  # the call worker detected an answering machine
    turns = contact_turns(transcript)
    if not turns:
        return False
    if all(is_voicemail_text(t) for t in turns):
        return False
    # A greeting that's mostly a voicemail recording ("Hi, you've reached Sam, leave a message") isn't a person.
    joined = " ".join(turns)
    return not (is_voicemail_text(joined) and len(turns) <= 2)


def reconcile_outcome(outcome: str | None, transcript: list[dict] | None) -> str | None:
    """Never label a call where the contact talked as no answer / voicemail."""
    if outcome in NO_CONVERSATION_OUTCOMES and person_answered(transcript):
        return "completed"
    return outcome
