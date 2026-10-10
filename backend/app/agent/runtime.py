"""
Shared runtime helpers for configurable agents.

Used by the API (text playground, post-call analysis) and by the LiveKit voice
worker, so a prompt behaves the same in chat as on a real call.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

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

    ctx_lines = [f"- {k}: {v}" for k, v in (variables or {}).items() if v not in (None, "")]
    if ctx_lines:
        parts.append("# CONTACT CONTEXT\n" + "\n".join(ctx_lines))

    tools = ["- end_call(outcome): call this after your goodbye to hang up. "
             "Pick the outcome that best describes the call."]
    if cfg.get("enable_booking"):
        tools.append("- check_availability(preferred_date): get real open slots. Only offer slots it returns.")
        tools.append("- book_appointment(slot, email): book the chosen slot. Confirm the email first.")
    if cfg.get("transfer_number") and channel == "phone":
        tools.append("- transfer_call(): hand the caller to a human when they ask for one or you can't help.")
    parts.append("# TOOLS\n" + "\n".join(tools))

    now = datetime.now(timezone.utc)
    parts.append(f"# CONTEXT\nToday is {now.strftime('%A, %B %-d, %Y')} (UTC). Channel: {channel}.")
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
