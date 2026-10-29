"""Fish Audio voices through LiveKit Inference (paid from the LiveKit project's Fish Audio credits).

Voices are stored on agents as "fishaudio:<voice id>", e.g. a voice cloned in the LiveKit dashboard
(Voices → Custom voices, ids like v_goYxyDbAUbfP). No Fish Audio account or key: LiveKit bills the project.
"""
from __future__ import annotations

import io
import re
import wave

from app.config import settings

PREFIX = "fishaudio:"
MODEL = "fishaudio/s2.1-pro"
SAMPLE_RATE = 24000
LANGUAGES = {"en", "zh", "ja", "de", "fr", "es", "ko", "ar", "ru", "nl", "it", "pl", "pt"}


def is_fish_voice(voice_id) -> bool:
    return bool(voice_id and voice_id.startswith(PREFIX))


def provider_voice_id(voice_id: str) -> str:
    value = voice_id.removeprefix(PREFIX)
    if not is_fish_voice(voice_id) or not re.fullmatch(r"[A-Za-z0-9_]{4,64}", value):
        raise ValueError("Invalid Fish Audio voice ID")
    return value


def make_livekit_tts(voice_id: str, *, speed: float = 1.0, language: str = "en", http_session=None):
    from livekit.agents import inference

    kwargs = dict(model=MODEL, voice=provider_voice_id(voice_id), sample_rate=SAMPLE_RATE,
                  api_key=settings.livekit_api_key, api_secret=settings.livekit_api_secret,
                  # "low": Fish Audio's fastest mode, for live calls.
                  extra_kwargs={"latency": "low", "speed": speed})
    lang = "en" if language in ("", "multi", None) else language
    if lang in LANGUAGES:
        kwargs["language"] = lang
    if http_session is not None:
        kwargs["http_session"] = http_session
    return inference.TTS(**kwargs)


async def synthesize_wav(voice_id: str, text: str, *, speed: float = 1.0, language: str = "en") -> bytes:
    """A short WAV for voice previews in the editor."""
    import aiohttp

    async with aiohttp.ClientSession() as session:
        tts = make_livekit_tts(voice_id, speed=speed, language=language, http_session=session)
        pcm = bytearray()
        rate, channels = SAMPLE_RATE, 1
        async with tts.synthesize(text) as stream:
            async for ev in stream:
                pcm += bytes(ev.frame.data)
                rate, channels = ev.frame.sample_rate, ev.frame.num_channels
        await tts.aclose()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(pcm))
    return buf.getvalue()
