"""
Speech-to-text for typing by voice in the app (the mic button next to text fields).
Audio is sent base64-encoded, transcribed with OpenAI, and not stored.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone

import httpx
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.services.auth import CtxDep

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/speech", tags=["speech"])

MAX_AUDIO_BYTES = 8 * 1024 * 1024   # ~3 minutes of compressed audio
MAX_PER_MINUTE = 20
_TYPES = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4", "audio/mpeg": "mp3", "audio/wav": "wav",
          "audio/x-m4a": "m4a", "audio/aac": "aac"}
_hits: dict = {}


class TranscribeRequest(BaseModel):
    audio_base64: str = Field(max_length=12_000_000)
    mime_type: str = Field(default="audio/webm", max_length=100)
    language: str | None = Field(default=None, max_length=8)


def _throttle(user_id) -> None:
    now = datetime.now(timezone.utc).timestamp()
    recent = [t for t in _hits.get(user_id, []) if now - t < 60]
    if len(recent) >= MAX_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Too many voice requests. Wait a minute and try again.")
    _hits[user_id] = recent + [now]


async def transcribe_audio(audio: bytes, mime: str, language: str | None) -> str:
    ext = _TYPES.get(mime.split(";")[0].strip().lower(), "webm")
    data = {"model": "whisper-1"}
    if language and language.isalpha() and len(language) == 2:
        data["language"] = language.lower()
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{settings.openai_base_url.rstrip('/')}/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            data=data, files={"file": (f"speech.{ext}", audio, mime.split(";")[0])},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"transcription failed with HTTP {resp.status_code}")
    return (resp.json().get("text") or "").strip()


@router.post("/transcribe")
async def transcribe(body: TranscribeRequest, ctx: CtxDep):
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="Voice typing isn't available right now.")
    try:
        audio = base64.b64decode(body.audio_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="The recording didn't upload correctly. Please try again.")
    if len(audio) < 1000:
        raise HTTPException(status_code=400, detail="That recording was too short. Hold the mic a little longer.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=400, detail="That recording is too long. Keep it under about 3 minutes.")
    _throttle(ctx.user.id)
    try:
        text = await transcribe_audio(audio, body.mime_type, body.language)
    except Exception as exc:
        log.warning("speech_transcribe_failed", error=str(exc)[:200])
        raise HTTPException(status_code=502, detail="We couldn't understand that recording. Please try again.")
    return {"text": text}
