"""Voices spoken through LiveKit Inference, billed to the LiveKit project (its startup credits), no provider keys.

Agents store these as "<provider>:<voice id>". The voice id is usually a clone made in the LiveKit dashboard
(Voices → Custom voices, ids like v_goYxyDbAUbfP); one clone works on every provider LiveKit cloned it to.
- fishaudio:  Fish Audio s2.1-pro, fastest mode
- inworld:    Inworld TTS 2
- lkcartesia: Cartesia Sonic 3.5 (through LiveKit, not our own Cartesia account)
"""
from __future__ import annotations

import io
import re
import wave

from app.config import settings

SAMPLE_RATE = 24000
# prefix → (provider shown in the picker, LiveKit Inference model, languages it takes)
PROVIDERS = {
    "fishaudio:": ("fishaudio", "fishaudio/s2.1-pro",
                   {"en", "zh", "ja", "de", "fr", "es", "ko", "ar", "ru", "nl", "it", "pl", "pt"}),
    "inworld:": ("inworld", "inworld/inworld-tts-2",
                 {"en", "zh", "ja", "ko", "fr", "de", "es", "pt", "it", "nl", "pl", "ru", "ar", "hi", "he"}),
    "lkcartesia:": ("cartesia", "cartesia/sonic-3.5",
                    {"en", "es", "de", "pt", "zh", "ja", "ko", "hi", "nl", "pl", "ru", "sv", "tr"}),
}


def _prefix(voice_id) -> str | None:
    return next((p for p in PROVIDERS if voice_id and voice_id.startswith(p)), None)


def is_inference_voice(voice_id) -> bool:
    return _prefix(voice_id) is not None


def provider_of(voice_id) -> str:
    return PROVIDERS[_prefix(voice_id)][0]


def model_of(voice_id) -> str:
    return PROVIDERS[_prefix(voice_id)][1]


def provider_voice_id(voice_id: str) -> str:
    prefix = _prefix(voice_id)
    value = voice_id.removeprefix(prefix or "")
    if not prefix or not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", value):
        raise ValueError("Invalid voice ID")
    return value


def _options(prefix: str, speed: float) -> dict:
    if prefix == "fishaudio:":
        return {"latency": "low", "speed": speed}  # Fish Audio's fastest mode, for live calls
    if prefix == "inworld:":
        return {"speaking_rate": max(0.5, min(1.5, speed))}
    return {"speed": max(0.6, min(1.5, speed))}


def make_livekit_tts(voice_id: str, *, speed: float = 1.0, language: str = "en", http_session=None):
    from livekit.agents import inference

    prefix = _prefix(voice_id)
    _, model, languages = PROVIDERS[prefix]
    kwargs = dict(model=model, voice=provider_voice_id(voice_id), sample_rate=SAMPLE_RATE,
                  api_key=settings.livekit_api_key, api_secret=settings.livekit_api_secret,
                  extra_kwargs=_options(prefix, speed))
    lang = "en" if language in ("", "multi", None) else language
    if lang in languages:
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
