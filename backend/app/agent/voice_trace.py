"""Bounded, content-free voice timelines. All offsets use one process monotonic clock.

The single private SDK read is pinned to the installed 1.6.4 context variable.
It observes the owning speech even during speculation; current_speech would
incorrectly attribute speculative audio to the speech currently playing.
Missing correlation is explicit, never guessed from wall clocks or text.
"""
from __future__ import annotations

import os
import time
import uuid
import hashlib
from functools import lru_cache
from collections import Counter
from importlib.metadata import version


@lru_cache(maxsize=1)
def _compatible():
    return version("livekit-agents") == "1.6.4"


def owning_speech():
    if not _compatible():
        return None
    from livekit.agents.voice.agent_activity import _SpeechHandleContextVar
    return _SpeechHandleContextVar.get(None)


class VoiceTrace:
    def __init__(self, emit, *, clock=time.monotonic, enabled=True):
        self.emit = emit
        self.clock = clock
        self.enabled = enabled
        self.origin = clock()
        self.clock_id = f"{os.getpid()}-{uuid.uuid4().hex[:12]}"
        self.counts = Counter()
        self._salt = os.urandom(16)

    def turn_key(self, text):
        # Correlates final transcript vs preemptive request only within this call.
        # Salt is never logged, and fingerprints cannot be joined across calls.
        return hashlib.blake2s(text.encode(), key=self._salt, digest_size=12).hexdigest()

    def mark(self, stage, *, speech=None, attempt=None, **fields):
        if not self.enabled:
            return
        self.counts[stage] += 1
        # Bound noise on long/noisy calls without retaining transcripts or audio.
        if self.counts[stage] > 500:
            return
        self.emit("voice_trace", clock_id=self.clock_id,
                  offset_ms=round((self.clock() - self.origin) * 1000, 3),
                  stage=stage, speech_id=getattr(speech, "id", None),
                  generation_step=getattr(speech, "num_steps", None), attempt=attempt,
                  **fields)

    async def stream(self, source, stage, *, speech=None, attempt=None, audio=False):
        """Observe without buffering; cancellation closes the upstream generator."""
        first = True
        amount = 0.0
        status = "complete"
        try:
            async for chunk in source:
                if first:
                    self.mark(stage + "_first", speech=speech, attempt=attempt)
                    first = False
                if audio:
                    amount += chunk.samples_per_channel / chunk.sample_rate
                yield chunk
        except BaseException:
            status = "cancelled_or_failed"
            raise
        finally:
            close = getattr(source, "aclose", None)
            if close:
                await close()
            self.mark(stage + "_end", speech=speech, attempt=attempt,
                      status=status, generated_audio_seconds=round(amount, 3) if audio else None)


def short_sentence_tokenizer(enabled):
    """1.6.4 parameters are character counts, not milliseconds or token counts.

    Keep the 10-character lookahead for abbreviations/addresses. Lower only the
    sentence merge threshold; never force-flush incomplete words or numbers.
    """
    from livekit.agents.tokenize.blingfire import SentenceTokenizer
    return SentenceTokenizer(min_sentence_len=1 if enabled else 20, stream_context_len=10)
