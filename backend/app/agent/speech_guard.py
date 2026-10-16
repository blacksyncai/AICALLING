"""
Stops model "leaks" from being spoken.

Reasoning models (gpt-oss on Cerebras) sometimes stream their private notes and imagined next turns into
the reply: "...for the invite?We need to capture email then book.Sure, you can send it to tony@...{ "slot":
... }". Everything after the first sign of that is dropped — never spoken, never kept in the call's history.

Signs: a sentence running straight into the next with no space ("invite?We"), braces (JSON), stage directions
in square brackets ("[Call ended]"), and note / role markers. Tool calls in the same stream still go through.
"""

from __future__ import annotations

import re

_SEAM = re.compile(r"(?<=[a-z0-9][.?!])(?=[A-Z])")  # "invite?We" — two messages glued together
_MARKERS = re.compile(r"[{}\[\]→]|\((?:Note|wait|waiting|pause|stop)|\bNote:|<\||\b(?:assistant|user|system)\s*:|\bThe (?:assistant|user) (?:should|is|wants|said)",
                      re.IGNORECASE)
# Internal names that must never be read out (tool calls / outcome codes written as text).
_INTERNAL_NAMES = re.compile(r"\b(?:end_call|check_availability|book_appointment|transfer_call|meeting_booked|"
                             r"not_interested|not_qualified|no_answer|do_not_call|wrong_number)\b|\bfunctions\.")
_HOLD = 24  # keep this much unspoken until more arrives, so a marker split across chunks is still caught


class SpeechGuard:
    def __init__(self) -> None:
        self.buffer = ""
        self.sent = 0
        self.cut_at: int | None = None

    @property
    def cut(self) -> bool:
        return self.cut_at is not None

    def _find_cut(self) -> int | None:
        hits = [m.start() for m in (_SEAM.search(self.buffer), _MARKERS.search(self.buffer),
                                    _INTERNAL_NAMES.search(self.buffer)) if m]
        return min(hits) if hits else None

    def feed(self, text: str) -> str:
        """New model text in; the part that's safe to speak now out."""
        text = text.replace("*", "")  # markdown emphasis ("**937-555-0142**") would be read out
        if self.cut:
            self.buffer += text  # kept only for the log
            return ""
        self.buffer += text
        cut = self._find_cut()
        if cut is not None:
            self.cut_at = cut
            out = self.buffer[self.sent:cut]
            self.sent = cut
            return out
        safe = max(self.sent, len(self.buffer) - _HOLD)
        # A completed sentence cannot be the unfinished prefix of any of the
        # protected internal markers. Release it now instead of waiting for
        # another 24 characters (or the end of the model's reply). Retain full
        # text for cross-chunk seam detection such as "Question?We need...".
        boundaries = list(re.finditer(r"[.!?][\"']?(?=\s)|[!?][\"']?$", self.buffer[self.sent:]))
        if boundaries:
            safe = max(safe, self.sent + boundaries[-1].end())
        out = self.buffer[self.sent:safe]
        self.sent = safe
        return out

    def flush(self) -> str:
        if self.cut:
            return ""
        out = self.buffer[self.sent:]
        self.sent = len(self.buffer)
        return out

    @property
    def dropped(self) -> str:
        return self.buffer[self.cut_at:] if self.cut else ""


def clean(text: str) -> str:
    """Whole-text version (for checks and tests)."""
    g = SpeechGuard()
    return (g.feed(text) + g.flush()).strip()


async def guarded(stream, on_cut=None):
    """Wrap an LLM node stream (str or ChatChunk items): speak only the clean part, keep tool calls."""
    guard = SpeechGuard()
    async for chunk in stream:
        if isinstance(chunk, str):
            out = guard.feed(chunk)
            if out:
                yield out
            continue
        delta = getattr(chunk, "delta", None)
        if delta is not None and delta.content:
            out = guard.feed(delta.content)
            chunk = chunk.model_copy(update={"delta": delta.model_copy(update={"content": out or None})})
            if not out and not delta.tool_calls and not getattr(chunk, "usage", None):
                continue
        yield chunk
    tail = guard.flush()
    if tail:
        yield tail
    if guard.cut and on_cut:
        on_cut(guard.dropped)
