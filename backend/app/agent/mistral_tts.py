"""Mistral (Voxtral) text-to-speech for the voice worker and voice previews.

Voices from Mistral are stored on agents as "mistral:<voice id>" so they can sit next to
Cartesia ids. Audio is streamed as SSE (`speech.audio.delta`, base64 float32 LE, 24 kHz mono)
and converted to 16-bit PCM.
"""

from __future__ import annotations

import base64
import json
import struct

import httpx

from app.config import settings

MISTRAL_VOICE_PREFIX = "mistral:"
MISTRAL_TTS_MODEL = "voxtral-mini-tts-latest"
MISTRAL_SPEECH_URL = "https://api.mistral.ai/v1/audio/speech"
SAMPLE_RATE = 24000


def is_mistral_voice(voice_id: str | None) -> bool:
    return bool(voice_id) and voice_id.startswith(MISTRAL_VOICE_PREFIX)


def mistral_voice_slug(voice_id: str) -> str:
    return voice_id[len(MISTRAL_VOICE_PREFIX):]


def f32le_to_s16le(data: bytes) -> bytes:
    n = len(data) // 4
    if not n:
        return b""
    samples = struct.unpack(f"<{n}f", data[: n * 4])
    return struct.pack(f"<{n}h", *(int(max(-1.0, min(1.0, s)) * 32767) for s in samples))


def _payload(voice_id: str, text: str) -> dict:
    return {"model": MISTRAL_TTS_MODEL, "voice_id": mistral_voice_slug(voice_id), "input": text,
            "response_format": "pcm", "stream": True}


async def iter_pcm16(client: httpx.AsyncClient, voice_id: str, text: str):
    """Yield 16-bit PCM chunks as Mistral streams them. Raises httpx.HTTPStatusError on API errors."""
    headers = {"Authorization": f"Bearer {settings.mistral_api_key}", "Accept": "text/event-stream"}
    async with client.stream("POST", MISTRAL_SPEECH_URL, headers=headers, json=_payload(voice_id, text)) as resp:
        if resp.status_code >= 400:
            await resp.aread()
            resp.raise_for_status()
        carry = b""
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if not raw or raw == "[DONE]":
                continue
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            audio = event.get("audio_data")
            if not audio:
                continue
            buf = carry + base64.b64decode(audio)
            cut = len(buf) - len(buf) % 4
            carry = buf[cut:]
            if cut:
                yield f32le_to_s16le(buf[:cut])


def wav_header(pcm_len: int) -> bytes:
    return (b"RIFF" + struct.pack("<I", 36 + pcm_len) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, 1, SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16)
            + b"data" + struct.pack("<I", pcm_len))


async def synthesize_wav(voice_id: str, text: str) -> bytes:
    async with httpx.AsyncClient(timeout=30.0) as client:
        pcm = b"".join([c async for c in iter_pcm16(client, voice_id, text)])
    return wav_header(len(pcm)) + pcm


def make_livekit_tts(voice_id: str):
    """A LiveKit TTS speaking with a Mistral voice (imported lazily so the API doesn't need livekit)."""
    from livekit.agents import APIConnectionError, APIStatusError, APITimeoutError, tts, utils
    from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

    class MistralTTS(tts.TTS):
        def __init__(self) -> None:
            super().__init__(capabilities=tts.TTSCapabilities(streaming=False),
                             sample_rate=SAMPLE_RATE, num_channels=1)
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))

        @property
        def model(self) -> str:
            return MISTRAL_TTS_MODEL

        @property
        def provider(self) -> str:
            return "Mistral"

        def synthesize(self, text: str, *, conn_options=DEFAULT_API_CONNECT_OPTIONS):
            return _Chunked(tts=self, input_text=text, conn_options=conn_options)

        async def aclose(self) -> None:
            await self._client.aclose()

    class _Chunked(tts.ChunkedStream):
        async def _run(self, output_emitter) -> None:
            output_emitter.initialize(request_id=utils.shortuuid(), sample_rate=SAMPLE_RATE,
                                      num_channels=1, mime_type="audio/pcm")
            try:
                async for chunk in iter_pcm16(self._tts._client, voice_id, self._input_text):
                    output_emitter.push(chunk)
                output_emitter.flush()
            except httpx.TimeoutException as exc:
                raise APITimeoutError() from exc
            except httpx.HTTPStatusError as exc:
                raise APIStatusError(str(exc), status_code=exc.response.status_code, body=exc.response.text) from exc
            except httpx.HTTPError as exc:
                raise APIConnectionError() from exc

    return MistralTTS()
