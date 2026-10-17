"""Existing ElevenLabs voices, namespaced so they never reach Cartesia."""
from __future__ import annotations

import re
import io
import wave
import httpx

from app.config import settings

MODEL = "eleven_flash_v2_5"
PREFIX = "elevenlabs:"


def is_elevenlabs_voice(voice_id):
    return bool(voice_id and voice_id.startswith(PREFIX))


def provider_voice_id(voice_id):
    value = voice_id.removeprefix(PREFIX)
    if not is_elevenlabs_voice(voice_id) or not re.fullmatch(r"[a-zA-Z0-9]{10,64}", value):
        raise ValueError("Invalid ElevenLabs voice ID")
    return value


def voice_settings(speed):
    # Installed plugin's VoiceSettings documents .8–1.2. Reject, never silently
    # replace a saved speed or fall back to a different provider/voice.
    if not .8 <= speed <= 1.2:
        raise ValueError("ElevenLabs speaking speed must be between 0.8 and 1.2")
    return {"stability": .5, "similarity_boost": .75, "speed": speed}


def make_livekit_tts(voice_id, *, speed=1.0, language="en"):
    from livekit.plugins import elevenlabs
    if not settings.elevenlabs_api_key:
        raise ValueError("ElevenLabs API key is not configured")
    kwargs = dict(voice_id=provider_voice_id(voice_id), api_key=settings.elevenlabs_api_key,
                  model=MODEL, encoding="pcm_24000", auto_mode=True,
                  voice_settings=elevenlabs.VoiceSettings(**voice_settings(speed)))
    if language not in ("", "multi", None):
        kwargs["language"] = language
    return elevenlabs.TTS(**kwargs)


async def synthesize_wav(voice_id, text, *, speed=1.0, language="en"):
    if not settings.elevenlabs_api_key:
        raise ValueError("ElevenLabs API key is not configured")
    payload = {"text": text, "model_id": MODEL, "voice_settings": voice_settings(speed)}
    if language not in ("", "multi", None):
        payload["language_code"] = language
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{provider_voice_id(voice_id)}",
            params={"output_format": "pcm_24000"}, headers={"xi-api-key": settings.elevenlabs_api_key},
            json=payload)
        response.raise_for_status()
    if not response.content or len(response.content) % 2:
        raise ValueError("Invalid ElevenLabs audio response")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
        wav.writeframes(response.content)
    return output.getvalue()
