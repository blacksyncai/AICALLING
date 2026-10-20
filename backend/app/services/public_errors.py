"""
Keeps internal details (setting names, vendors we run on, "backend" wording) out of
error messages customers see. Admin and platform-settings routes keep the real text.
"""

from __future__ import annotations

import re

GENERIC = "Something went wrong on our end — please try again, or message us in the chat if it keeps happening."

_INTERNAL_PATHS = ("/api/admin",)

_ENV_NAME = re.compile(r"\b[A-Z][A-Z0-9]{2,}_[A-Z0-9_]+\b")  # OPENAI_API_KEY, LIVEKIT_URL …
_TECHNICAL = re.compile(
    r"livekit|twilio|deepgram|cartesia|openai|cerebras|mistral|nango|dataskip|resend|svix|clerk"
    r"|eleven[\s_-]*labs|signal[\s_-]*wire|bandwidth|anthropic"
    r"|on the server|backend|\.env\b|sip trunk|traceback|stack trace|api key is set",
    re.IGNORECASE,
)


def is_technical(text: str) -> bool:
    return bool(_ENV_NAME.search(text or "") or _TECHNICAL.search(text or ""))


def public_detail(path: str, detail):
    """The error detail a customer should see for a request to `path`."""
    if path.startswith(_INTERNAL_PATHS):
        return detail
    if isinstance(detail, str):
        return GENERIC if is_technical(detail) else detail
    if isinstance(detail, dict):
        return {k: (public_detail(path, v) if isinstance(v, str) else v) for k, v in detail.items()}
    return detail


def public_summary(status: str | None, summary: str | None) -> str | None:
    """Failed-call reasons stored before wording was cleaned up can name internals; show a plain one."""
    if summary and status in ("failed", "no_answer") and is_technical(summary):
        return "Call failed — the call couldn't be connected." if status == "failed" else "Not answered."
    return summary
