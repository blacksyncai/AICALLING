"""Opt-in Sonic expression syntax; bounded parsing and a fresh generation per emotion change."""
from __future__ import annotations

import html
import re
from collections.abc import AsyncIterable

# Cartesia's official generated GenerationConfig enum. Kept local so API validation needs no SDK import.
EMOTIONS = (
    'neutral', 'happy', 'excited', 'enthusiastic', 'elated', 'euphoric', 'triumphant', 'amazed',
    'surprised', 'flirtatious', 'curious', 'content', 'peaceful', 'serene', 'calm', 'grateful',
    'affectionate', 'trust', 'sympathetic', 'anticipation', 'mysterious', 'angry', 'mad', 'outraged',
    'frustrated', 'agitated', 'threatened', 'disgusted', 'contempt', 'envious', 'sarcastic', 'ironic',
    'sad', 'dejected', 'melancholic', 'disappointed', 'hurt', 'guilty', 'bored', 'tired', 'rejected',
    'nostalgic', 'wistful', 'apologetic', 'hesitant', 'insecure', 'confused', 'resigned', 'anxious',
    'panicked', 'alarmed', 'scared', 'proud', 'confident', 'distant', 'skeptical', 'contemplative', 'determined',
)
_EMOTION = re.compile(r'''<emotion\s+value\s*=\s*(["'])([a-z]+)\1\s*/>''', re.I)
_BREAK = re.compile(r'''<break\s+time\s*=\s*(["'])(\d+(?:\.\d+)?)(ms|s)\1\s*/>''', re.I)
MAX_TOKEN = 256


def enabled_for(cfg: dict) -> bool:
    voice = cfg.get('voice_id') or ''
    # Prefixed voices use other providers/LiveKit hosted clones; do not assume their control contracts.
    return bool((cfg.get('voice_tuning') or {}).get('expressions_enabled')) and ':' not in voice


def default_emotion(raw: dict | None) -> str | None:
    raw = raw or {}
    value = raw.get('default_emotion')
    return value if raw.get('expressions_enabled') and value in EMOTIONS else None


class MarkupParser:
    """Only an unfinished control is held. Malformed/oversized controls are dropped, never read out."""
    def __init__(self, enabled=False, *, stage_directions=False):
        self.enabled, self.stage_directions = enabled, stage_directions
        self.pending = ''
        self.mode = ''
        self.oversized = False
        self.tail = ''
        self.laughs = self.pauses = self.emotions = 0

    def _control(self, raw):
        raw = html.unescape(raw)
        match = _EMOTION.fullmatch(raw)
        if match and self.enabled and match[2].lower() in EMOTIONS and self.emotions < 8:
            self.emotions += 1
            return f'<emotion value="{match[2].lower()}"/>'
        match = _BREAK.fullmatch(raw)
        if match and self.enabled:
            duration = float(match[2]) * (1000 if match[3].lower() == 's' else 1)
            # Product limit: each pause <=2s, total deliberate pauses <=3s per utterance.
            if duration.is_integer() and 0 < duration <= 2000 and self.pauses + duration <= 3000:
                self.pauses += int(duration)
                return f'<break time="{int(duration)}ms"/>'
        if raw.lower() == '[laughter]':
            if self.enabled and self.laughs == 0:
                self.laughs += 1
                return '[laughter]'
            return ''
        if raw.startswith('[') and self.stage_directions and not raw.lower().startswith('[laugh'):
            return raw  # existing speech guard must still stop imagined turns/stage directions
        return ''

    def feed(self, text: str) -> str:
        out = []
        for char in text:
            if self.mode:
                if self.mode == 'entity':
                    self.pending += char
                    if self.pending.lower() == '&lt;':
                        self.mode, self.pending = 'tag', '<'
                    elif not '&lt;'.startswith(self.pending.lower()):
                        out.append(self.pending)
                        self.mode, self.pending = '', ''
                    continue
                self.tail = (self.tail + char)[-5:]
                if not self.oversized:
                    self.pending += char
                    if len(self.pending) > MAX_TOKEN:
                        self.pending, self.oversized = '', True
                ended = (char == ']' if self.mode == 'bracket' else char == '>' or self.tail.lower().endswith('&gt;'))
                if ended:
                    if not self.oversized:
                        out.append(self._control(self.pending))
                    self.mode, self.pending, self.tail, self.oversized = '', '', '', False
                continue
            if char in '<[&':
                self.mode = {'<':'tag', '[':'bracket', '&':'entity'}[char]
                self.pending, self.tail = char, char
            else:
                out.append(char)
        return ''.join(out)

    def flush(self):
        # An unfinished entity in plain speech is not a tag. Incomplete tags/brackets are never spoken.
        tail = self.pending if self.mode == 'entity' and self.pending == '&' else ''
        self.mode, self.pending, self.tail, self.oversized = '', '', '', False
        return tail


def clean_markup(text: str, enabled=False, *, stage_directions=False) -> str:
    parser = MarkupParser(enabled, stage_directions=stage_directions)
    return parser.feed(text) + parser.flush()


async def speech_text(text: AsyncIterable[str], enabled=False):
    parser = MarkupParser(enabled)
    try:
        async for chunk in text:
            ready = parser.feed(chunk)
            if ready:
                yield ready
        tail = parser.flush()
        if tail:
            yield tail
    finally:
        close = getattr(text, 'aclose', None)
        if close:
            await close()


async def synthesize_expressions(text, synthesize):
    """Stream each utterance now; an emotion marker closes the current Cartesia context.

    Each invocation owns its iterator/state. Cancellation closes the active generation and discards
    held tags; neither emotion nor unfinished markup survives interruption into the next utterance.
    """
    source = speech_text(text, True).__aiter__()
    pending = ''
    finished = False
    try:
        while not finished:
            async def generation():
                nonlocal pending, finished
                has_text = False
                while True:
                    if pending:
                        chunk, pending = pending, ''
                    else:
                        try:
                            chunk = await anext(source)
                        except StopAsyncIteration:
                            finished = True
                            return
                    for match in _EMOTION.finditer(chunk):
                        before, after = chunk[:match.start()], chunk[match.start():]
                        if has_text or before.strip():
                            if before:
                                yield before
                            pending = after
                            return
                        # A leading emotion belongs to this context, not the previous one.
                        yield match[0]
                        chunk = chunk[match.end():]
                        break
                    else:
                        if chunk:
                            has_text |= bool(chunk.strip())
                            yield chunk
                        continue
                    if chunk:
                        pending = chunk
            frames = synthesize(generation())
            try:
                async for frame in frames:
                    yield frame
            finally:
                await frames.aclose()
    finally:
        await source.aclose()


def instructions(cfg):
    if not enabled_for(cfg):
        return ''
    return ('# OPTIONAL VOCAL DELIVERY (controls, never spoken instructions)\n'
            'Speak naturally. Occasionally prefix an utterance with <emotion value="curious"/> or '
            '<emotion value="calm"/> to guide delivery. Supported emotions: ' + ', '.join(EMOTIONS) + '. '
            'Place emotion controls at utterance starts; avoid mid-sentence changes. '
            'Use <break time="200ms"/> for an occasional brief pause (max 2000ms each, 3000ms total). '
            'Only use [laughter] if the conversation genuinely calls for laughter, at most once per turn; '
            'never add it by default. Do not repeatedly insert fillers such as umm. '
            'All other script directions are instructions, not words to say. '
            'If your opening asks an identity question, say only that question, then wait for the recipient. '
            'Continue the introduction in a separate reply after their answer; a pause tag is not a user turn. '
            'Never invent the recipient\'s response.')
