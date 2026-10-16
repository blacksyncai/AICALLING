"""
Per-agent voice tuning (Agent.voice_tuning) → the voice worker's settings.

- volume: Cartesia sonic-3 generation volume (0.5–2.0).
- responsiveness 0–1: how quickly the agent answers after the caller stops
  (endpointing delay). 0.75 = the standard 350 ms.
- interruption 0–1: how easily the caller can cut the agent off (how much speech
  counts as a barge-in). 0.75 = the standard 0.5 s / 2 words.
- pronunciations: [{"word", "say"}] — the word is replaced by its spoken spelling
  before it reaches the voice (the transcript keeps the original word).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterable


def _clamp(v, lo: float, hi: float, default: float) -> float:
    try:
        return min(hi, max(lo, float(v)))
    except (TypeError, ValueError):
        return default


def voice_tuning(raw: dict | None) -> dict:
    raw = raw or {}
    r = _clamp(raw.get("responsiveness"), 0, 1, 0.75)
    i = _clamp(raw.get("interruption"), 0, 1, 0.75)
    pron = [
        (str(p.get("word", "")).strip(), str(p.get("say", "")).strip())
        for p in (raw.get("pronunciations") or []) if isinstance(p, dict)
    ]
    return {
        "volume": round(_clamp(raw.get("volume"), 0.5, 2.0, 1.0), 2),
        "min_delay": round(0.95 - 0.8 * r, 2),           # 0.95 s … 0.15 s
        "max_delay": round(4.0 - 2.0 * r, 2),            # 4.0 s … 2.0 s
        "min_duration": round(1.1 - 0.8 * i, 2),         # 1.1 s … 0.3 s of speech
        "min_words": 1 if i >= 0.9 else 2 if i >= 0.4 else 3,
        "pronunciations": [(w, s) for w, s in pron if w and s],
    }


# Always applied after the account's own: how every agent says our name (never read "blacksync.ai" out as a link,
# or say the name twice when the model writes "BlackSync AI (blacksync.ai)").
BUILT_IN_PRONUNCIATIONS: list[tuple[str, str]] = [
    ("BlackSync AI (blacksync.ai)", "BlackSync dot A I"),
    ("BlackSync AI (blacksync dot ai)", "BlackSync dot A I"),
    ("blacksync.ai", "BlackSync dot A I"),
]


def apply_pronunciations(text: str, pairs: list[tuple[str, str]], *, preceding: str = "") -> str:
    for word, say in pairs:
        def replace(match, replacement=say):
            # A streaming segment can start inside a word emitted earlier.
            if match.start() == 0 and preceding and re.match(r"\w", preceding):
                return match.group(0)
            return replacement
        text = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", replace, text, flags=re.IGNORECASE)
    return text


def pronounce(pairs: list[tuple[str, str]]):
    """Stream immediately; retain only suffixes that could be pronunciation phrases."""
    pairs = [(word, say) for word, say in pairs if word]

    async def _transform(text: AsyncIterable[str]) -> AsyncIterable[str]:
        buffer = ""
        preceding = ""
        for_match = [word for word, _ in pairs]
        async for chunk in text:
            buffer += chunk
            cut = len(buffer)
            for word in for_match:
                # A prefix starting at a word boundary might continue in the next
                # chunk. Complete matches at the end also need their right boundary.
                for start in range(max(0, len(buffer) - len(word)), len(buffer)):
                    previous = buffer[start - 1] if start else preceding
                    if previous and re.match(r"\w", previous):
                        continue
                    suffix = buffer[start:]
                    if re.fullmatch(re.escape(word[:len(suffix)]), suffix, re.IGNORECASE):
                        cut = min(cut, start)
                        break
            if cut:
                ready, buffer = buffer[:cut], buffer[cut:]
                yield apply_pronunciations(ready, pairs, preceding=preceding)
                preceding = ready[-1]
        if buffer:
            yield apply_pronunciations(buffer, pairs, preceding=preceding)

    return _transform
