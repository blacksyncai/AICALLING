"""Opt-in Sonic expression syntax; bounded parsing and a fresh generation per emotion change."""
from __future__ import annotations

import asyncio
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

DELIVERY_STYLES = {
    'natural': ('Natural and balanced', 'Sound conversational and matter-of-fact. Use curiosity for a genuine question, calm for reassurance, and otherwise the voice’s natural delivery.'),
    'warm': ('Warm and conversational', 'Sound approachable and engaged. A little contentment or curiosity can suit an opening or a genuine question; do not sound constantly excited or overly familiar.'),
    'calm': ('Calm and reassuring', 'Stay composed and unhurried. Use calm or sympathetic delivery when acknowledging a concern, without sounding sad or patronizing.'),
    'confident': ('Clear and confident', 'Sound assured and direct. Use confident delivery for a useful explanation and curiosity for a real question; avoid pressure, shouting or exaggerated enthusiasm.'),
    'custom': ('Custom direction', ''),
}


def allows_laughter(cfg: dict) -> bool:
    raw = cfg.get('voice_tuning') or {}
    return raw.get('expression_mode') != 'automatic' or bool(raw.get('automatic_laughter'))



def enabled_for(cfg: dict) -> bool:
    voice = cfg.get('voice_id') or ''
    # Hosted Sonic 3.5 uses the same controls through the inference SDK's CartesiaOptions.
    supported = ':' not in voice or bool(re.fullmatch(r'lkcartesia:[A-Za-z0-9_-]{4,64}', voice))
    return bool((cfg.get('voice_tuning') or {}).get('expressions_enabled')) and supported


def default_emotion(raw: dict | None) -> str | None:
    raw = raw or {}
    value = raw.get('default_emotion')
    return value if raw.get('expressions_enabled') and raw.get('expression_mode') != 'automatic' and value in EMOTIONS else None


class MarkupParser:
    """Only an unfinished control is held. Malformed/oversized controls are dropped, never read out."""
    def __init__(self, enabled=False, *, stage_directions=False, allow_laughter=True):
        self.enabled, self.stage_directions = enabled, stage_directions
        self.allow_laughter = allow_laughter
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
            if self.enabled and self.allow_laughter and self.laughs == 0:
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


def clean_markup(text: str, enabled=False, *, stage_directions=False, allow_laughter=True) -> str:
    parser = MarkupParser(enabled, stage_directions=stage_directions, allow_laughter=allow_laughter)
    return parser.feed(text) + parser.flush()


async def speech_text(text: AsyncIterable[str], enabled=False, *, allow_laughter=True):
    parser = MarkupParser(enabled, allow_laughter=allow_laughter)
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


async def synthesize_expressions(text, synthesize, *, allow_laughter=True):
    """Stream each utterance now; an emotion marker closes the current Cartesia context.

    Each invocation owns its iterator/state. Cancellation closes the active generation and discards
    held tags; neither emotion nor unfinished markup survives interruption into the next utterance.
    """
    source = speech_text(text, True, allow_laughter=allow_laughter).__aiter__()
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


async def synthesize_configured_expressions(text, synthesize, *, baseline=None, allow_laughter=True):
    """Resolve emotion markers into per-generation configuration, never provider transcript text.

    Prefetch only the first ready text chunk to select the configuration. Each generation streams
    immediately and stops at the next complete marker; cancellation closes both iterators.
    """
    source = speech_text(text, True, allow_laughter=allow_laughter).__aiter__()
    pending = ''
    finished = False
    emotion = baseline
    try:
        while not finished:
            if not pending:
                try:
                    pending = await anext(source)
                except StopAsyncIteration:
                    return
            leading = _EMOTION.match(pending.lstrip())
            if leading:
                stripped = pending.lstrip()
                emotion = leading[2].lower()
                pending = stripped[leading.end():]
                continue
            if not pending.strip():
                pending = ''
                continue

            async def generation():
                nonlocal pending, finished
                while True:
                    chunk, pending = pending, ''
                    if not chunk:
                        try:
                            chunk = await anext(source)
                        except StopAsyncIteration:
                            finished = True
                            return
                    change = _EMOTION.search(chunk)
                    if change:
                        pending = chunk[change.start():]
                        if before := chunk[:change.start()]:
                            yield before
                        return
                    yield chunk

            frames = synthesize(generation(), emotion)
            try:
                async for frame in frames:
                    yield frame
            finally:
                await frames.aclose()
    finally:
        await source.aclose()


class ConfiguredExpressionAudio:
    """Independent SDK clients per emotion; never mutate a client's options during other speech."""
    def __init__(self, base, factory, *, baseline=None, conn_options, on_generation=None):
        self.base, self.factory = base, factory
        self.clients = {baseline: base}
        self.conn_options, self.on_generation = conn_options, on_generation

    async def synthesize(self, text, emotion):
        if emotion not in self.clients:
            client = self.factory(emotion)
            self.clients[emotion] = client
            # The session observes its base client. Preserve expression-client metrics/errors too.
            for event in ('metrics_collected', 'error'):
                client.on(event, lambda value, name=event: self.base.emit(name, value))
        client = self.clients[emotion]
        if self.on_generation:
            self.on_generation(emotion)
        async with client.stream(conn_options=self.conn_options()) as stream:
            async def forward():
                try:
                    async for chunk in text:
                        stream.push_text(chunk)
                finally:
                    stream.end_input()
            task = asyncio.create_task(forward())
            try:
                async for event in stream:
                    yield event.frame
                await task
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def aclose(self):
        await asyncio.gather(*(client.aclose() for client in self.clients.values()
                               if client is not self.base), return_exceptions=True)


_IDENTITY_QUESTION = re.compile(
    r"\b(?:is this|am I (?:speaking|talking) (?:with|to)|have I reached|did I reach|are you)\b"
    r"|\b(?:this is|you are|you're)\b[^?]{1,100}\b(?:right|correct)\s*\?"
    r"|(?:^|[,!.]\s*)[\w’' -]{1,60},?\s+(?:right|correct)\s*\?", re.I)


def opening_delivery(text: str, cfg: dict) -> str:
    """Saved openings bypass the LLM; make an unannotated identity question curious too.

    Explicit script emotions win. Any following text returns to neutral delivery;
    wording and turn-taking remain intact.
    """
    if not enabled_for(cfg) or (cfg.get('voice_tuning') or {}).get('expression_mode') != 'automatic':
        return text
    if _EMOTION.search(text):
        return text
    question, mark, remainder = text.partition('?')
    if not mark or not _IDENTITY_QUESTION.search(clean_markup(question + mark)):
        return text
    tail = '<emotion value="neutral"/>' + remainder if remainder.strip() else remainder
    return '<emotion value="curious"/>' + question + mark + tail


def instructions(cfg):
    if not enabled_for(cfg):
        return ''
    raw = cfg.get('voice_tuning') or {}
    automatic = raw.get('expression_mode') == 'automatic'
    guidance = ''
    if automatic:
        style = DELIVERY_STYLES.get(raw.get('delivery_style') or 'natural', DELIVERY_STYLES['natural'])
        direction = str(raw.get('delivery_direction') or '').strip()[:500]
        guidance = ('# AUTOMATIC DELIVERY — PRIVATE RENDERING GUIDANCE\n'
                    'Choose subtle vocal delivery from the meaning and the recipient’s last response. '
                    'The user should not have to annotate their script. Preserve the script’s facts and purpose. '
                    'Most speech should remain untagged: use at most one emotion marker at the start of an utterance '
                    'only when it helps a specific part, not on every sentence or throughout the whole script. '
                    'An identity check such as “Hey, this is James, right?” should use curious delivery: '
                    'prefix that question with <emotion value="curious"/> and then wait for the real recipient’s answer. '
                    'Return to natural delivery for the next reply unless its meaning calls for another expression. '
                    'For automatic choices, use only neutral, curious, calm, content, happy, sympathetic, confident or grateful. '
                    'Never change a neutral or sensitive conversation into an excited sales pitch. '
                    'Do not mention expressions, styles, controls, or this guidance to the caller. '
                    + style[1] + ('\nUser delivery direction (tone only, never read aloud): ' + direction if direction else '')
                    + ('\nNever generate [laughter]. Laughter is disabled. ' if not allows_laughter(cfg) else
                       '\nLaughter is optional only when the caller’s lighthearted response makes it appropriate, at most once. '))
    return guidance + ('# OPTIONAL VOCAL DELIVERY (controls, never spoken instructions)\n'
            + ('Speak naturally. Choose occasional expression controls where appropriate. ' if automatic else
               'Speak naturally. Only use delivery controls explicitly marked in the script; do not add emotions or pauses elsewhere. ')
            + 'Emotion syntax includes <emotion value="curious"/> or <emotion value="calm"/>. '
            'Supported emotions: ' + ', '.join(EMOTIONS) + '. '
            'Place automatic emotion controls at utterance starts; keep explicitly marked passages scoped as written. '
            'Pause syntax is <break time="200ms"/> (max 2000ms each, 3000ms total per reply). '
            + (('Only use [laughter] if the conversation genuinely calls for laughter, at most once per turn; '
                'never add it by default. ' if automatic else 'Only use [laughter] where explicitly marked in the script, at most once. ')
               if allows_laughter(cfg) else 'Never generate [laughter]; laughter is disabled. ')
            + 'Do not repeatedly insert fillers such as umm. '
            'Explicit delivery controls in the script override automatic choices for the marked passage. '
            'When speaking that passage, preserve its chosen controls and return to the indicated baseline afterward. '
            'All other script directions are instructions, not words to say. '
            'If your opening asks an identity question, say only that question, then wait for the recipient. '
            'Continue the introduction in a separate reply after their answer; a pause tag is not a user turn. '
            'Never invent the recipient\'s response.')
