"""
Stops the agent from re-reading a line it already said.

Some models answer a confused "Hello? What property?" by reciting their scripted intro again, word for word.
The reply is held only until it stops matching everything the agent has said (usually the first word or two);
if it keeps matching an earlier line, it's dropped unspoken and the model is asked once more, told to respond
to what the contact just said instead.
"""

from __future__ import annotations

import re

MIN_WORDS = 6  # shorter lines ("Hey, is this Sam?") may fairly come up twice
REPEAT_AT = 8  # this many words in a row from an earlier line counts as a repeat

NUDGE = (
    "# DON'T REPEAT YOURSELF\n"
    "Your last reply started to repeat something you already said on this call, word for word. Don't. "
    "Respond directly to what the contact just said: answer their question using the details you have, "
    "or, if they didn't seem to hear you, say it again briefly in different words."
)


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


class RepeatGuard:
    def __init__(self, said: list[str]) -> None:
        self.prev = [w for w in (words(s) for s in said) if len(w) >= MIN_WORDS]
        self.text = ""

    def feed(self, text: str) -> str:
        """'repeat', 'ok' (it's new: stop checking) or 'wait' (still matches an earlier line)."""
        self.text += text
        got = words(self.text)
        if self.text and self.text[-1].isalnum():
            got = got[:-1]  # the last word may still be arriving
        matching = [p for p in self.prev if p[:len(got)] == got]
        if not matching:
            return "ok"
        if any(len(got) >= min(REPEAT_AT, len(p)) for p in matching):
            return "repeat"
        return "wait"


def _text(chunk) -> tuple[str | None, bool]:
    """(text in this chunk, whether it carries a tool call)."""
    if isinstance(chunk, str):
        return chunk, False
    delta = getattr(chunk, "delta", None)
    if delta is None:
        return None, False
    return delta.content, bool(delta.tool_calls)


async def no_repeats(make_stream, said: list[str], on_repeat=None):
    """make_stream(nudged: bool) → an LLM node stream. Yields the first attempt's chunks unless it re-reads an
    earlier line; then that attempt is dropped and a nudged second attempt is passed through."""
    if not said:
        async for chunk in make_stream(False):
            yield chunk
        return
    guard, held, checking = RepeatGuard(said), [], True
    stream = make_stream(False)
    try:
        async for chunk in stream:
            if not checking:
                yield chunk
                continue
            text, tool = _text(chunk)
            held.append(chunk)
            state = "ok" if tool else guard.feed(text) if text else "wait"
            if state == "wait":
                continue
            if state == "repeat":
                break
            checking = False
            for c in held:
                yield c
            held = []
        else:
            for c in held:  # ended while still matching a short prefix: say it
                yield c
            return
    finally:
        await _close(stream)
    if on_repeat:
        on_repeat(guard.text)
    async for chunk in make_stream(True):
        yield chunk


async def _close(stream) -> None:
    close = getattr(stream, "aclose", None)
    if close:
        try:
            await close()
        except Exception:
            pass


def said_lines(chat_ctx) -> list[str]:
    out = []
    for item in getattr(chat_ctx, "items", []):
        if getattr(item, "type", None) == "message" and getattr(item, "role", None) == "assistant":
            text = getattr(item, "text_content", None) or ""
            if text.strip():
                out.append(text)
    return out


def with_nudge(chat_ctx):
    """A copy of chat_ctx with the don't-repeat note added to the instructions (so the contact still has the
    last turn — some models refuse anything else)."""
    fixed = chat_ctx.copy()
    for i, item in enumerate(fixed.items):
        if getattr(item, "type", None) == "message" and getattr(item, "role", None) in ("system", "developer"):
            fixed.items[i] = item.model_copy(update={"content": [*item.content, "\n\n" + NUDGE]})
            return fixed
    fixed.add_message(role="system", content=NUDGE)
    fixed.items.insert(0, fixed.items.pop())
    return fixed
