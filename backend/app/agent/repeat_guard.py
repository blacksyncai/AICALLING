"""
Stops the agent from re-reading a line it already said.

Some models answer a confused "Hello? Where are you calling from?" by reciting their intro or pitch again, word
for word or lightly reworded. Each sentence of a reply is checked against what the agent already said on the call;
repeats are dropped unspoken. If nothing new is left, the model is asked once more, told to respond to what the
contact just said instead.
"""

from __future__ import annotations

import re

MIN_WORDS = 6  # shorter lines ("Hey, is this Sam?") may fairly come up twice
REPEAT_AT = 8  # this many words in a row from an earlier line counts as a repeat
SIMILAR = 0.7  # a sentence whose words are mostly in one earlier sentence is a reworded repeat
NOVEL = 0.5  # a sentence this new by its first words is spoken without waiting for its end

NUDGE = (
    "# DON'T REPEAT YOURSELF\n"
    "Your last reply repeated something you already said on this call. Don't. Talk like a person: respond "
    "directly to what the contact just said in a few new words (e.g. \"Yeah, Compass Multifamily.\"), "
    "answer their question using the details you have, and don't re-read your pitch or ask the same question again."
)

_END = re.compile(r"[.?!]+[\"')]*\s+")


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def _sentences(text: str) -> list[str]:
    return [x for x in _END.split(text or "") if x.strip()]


class RepeatGuard:
    """Knows what the agent already said on this call and judges new sentences against it."""

    def __init__(self, said: list[str]) -> None:
        self.prev = [set(w) for w in (words(x) for line in said for x in _sentences(line)) if w]
        self.seen = set().union(*self.prev) if self.prev else set()
        self.runs = set()
        for line in said:
            w = words(line)
            self.runs.update(tuple(w[i:i + REPEAT_AT]) for i in range(len(w) - REPEAT_AT + 1))

    def repeats(self, sentence: str) -> bool:
        w = words(sentence)
        if len(w) < MIN_WORDS:
            return False
        if any(tuple(w[i:i + REPEAT_AT]) in self.runs for i in range(len(w) - REPEAT_AT + 1)):
            return True
        s = set(w)
        return any(len(s & p) / len(s) >= SIMILAR for p in self.prev)

    def clearly_new(self, partial: str) -> bool:
        w = words(partial)
        if partial and partial[-1].isalnum():
            w = w[:-1]  # the last word may still be arriving
        return len(w) >= MIN_WORDS and sum(x not in self.seen for x in w) / len(w) >= NOVEL


def _text(chunk) -> tuple[str | None, bool]:
    """(text in this chunk, whether it carries a tool call)."""
    if isinstance(chunk, str):
        return chunk, False
    delta = getattr(chunk, "delta", None)
    if delta is None:
        return None, False
    return delta.content, bool(delta.tool_calls)


async def _filtered(stream, guard: RepeatGuard, dropped: list[str]):
    """The stream with sentences that repeat earlier lines left out. Each sentence is held until it ends (or is
    clearly new); text comes out as strings, other chunks (tool calls, usage) as they are."""
    held, live = "", False

    def judge(sentence: str):
        if guard.repeats(sentence):
            dropped.append(sentence.strip())
            return None
        return sentence

    async for chunk in stream:
        text, tool = _text(chunk)
        if not text or tool:
            if held:
                out = held if live else judge(held)
                held, live = "", False
                if out:
                    yield out
            yield chunk
            continue
        if live:  # this sentence was already judged new: pass it straight through to its end
            m = _END.search(text)
            if not m:
                yield text
                continue
            yield text[:m.end()]
            text, live = text[m.end():], False
        held += text
        while (m := _END.search(held)):
            out = judge(held[:m.end()])
            held = held[m.end():]
            if out:
                yield out
        if held and guard.clearly_new(held):
            yield held
            held, live = "", True
    if held and (live or judge(held)):
        yield held


async def no_repeats(make_stream, said: list[str], on_repeat=None):
    """make_stream(nudged: bool) → an LLM node stream. Sentences that repeat earlier lines are dropped unspoken;
    if that leaves nothing to say, a nudged second attempt is passed through."""
    if not said:
        async for chunk in make_stream(False):
            yield chunk
        return
    dropped: list[str] = []
    spoke = acted = False
    stream = make_stream(False)
    try:
        async for piece in _filtered(stream, RepeatGuard(said), dropped):
            if isinstance(piece, str):
                spoke = spoke or bool(piece.strip())
            else:
                acted = acted or _text(piece)[1]
            yield piece
    finally:
        await _close(stream)
    if dropped and on_repeat:
        on_repeat(" ".join(dropped))
    if spoke or acted or not dropped:
        return
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
