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


def agent_to_runtime(agent) -> dict:
    """Serialize an Agent row into the config the voice worker consumes."""
    return {
        "id": str(agent.id),
        "name": agent.name,
        "system_prompt": agent.system_prompt or "",
        "first_message": agent.first_message or "",
        "knowledge_base": agent.knowledge_base or "",
        "language": agent.language or "en",
        "llm_model": agent.llm_model or "gpt-4.1-mini",
        "temperature": agent.temperature if agent.temperature is not None else 0.5,
        "voice_id": agent.voice_id or "",
        "voice_speed": agent.voice_speed or 1.0,
        "background_audio": bool(agent.background_audio),
        "enable_booking": bool(agent.enable_booking),
        "calcom_event_type_id": agent.calcom_event_type_id or "",
        "transfer_number": agent.transfer_number or "",
        "max_duration_seconds": agent.max_duration_seconds or 600,
        "ai_disclosure": getattr(agent, "ai_disclosure", None) is not False,
        "business_name": (getattr(agent, "builder", None) or {}).get("business_name") or "",
    }


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

    ctx_lines = [f"- {k}: {v}" for k, v in (variables or {}).items() if v not in (None, "")]
    if ctx_lines:
        parts.append("# CONTACT CONTEXT\n" + "\n".join(ctx_lines))

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
