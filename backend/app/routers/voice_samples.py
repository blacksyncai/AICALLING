"""Public voice samples for the marketing site (blacksync.ai): four fixed voices saying one fixed line.

No sign-in, no custom text: each sample is generated once with the same code as the editor's voice preview,
kept in memory and in the recordings bucket, and served as a cacheable WAV.
"""
from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/public/voice-samples", tags=["public"])

LINE = "Hey, this is {name}. This is a quick preview of how I'll sound on your calls. Does this work for you?"
# key → (shown name, voice id). Bump VERSION to regenerate after changing a voice or the line.
SAMPLES = {
    "marissa": ("Marissa", "97f03c16-fab2-4747-b655-9caefbd68fcf"),
    "macco": ("Macco", "lkcartesia:v_ZMqDxhK7B6i6"),
    "lauren": ("Lauren", "inworld:v_9thNgvPeCfcX"),
    "kate": ("Kate", "inworld:v_PmKa7bajvjhe"),
}
VERSION = "1"
_cache: dict[str, bytes] = {}
_locks: dict[str, asyncio.Lock] = {k: asyncio.Lock() for k in SAMPLES}


def _bucket_key(key: str) -> str:
    return f"public/voice-samples/{key}-v{VERSION}.wav"


async def _from_bucket(key: str) -> bytes | None:
    from app.config import settings
    from app.services import recordings

    if not settings.recordings_ready:
        return None
    try:
        obj = await asyncio.to_thread(recordings._s3().get_object, Bucket=settings.recordings_s3_bucket, Key=_bucket_key(key))
        return await asyncio.to_thread(obj["Body"].read)
    except Exception:
        return None


async def _to_bucket(key: str, data: bytes) -> None:
    from app.config import settings
    from app.services import recordings

    if not settings.recordings_ready:
        return
    try:
        await asyncio.to_thread(recordings._s3().put_object, Bucket=settings.recordings_s3_bucket,
                                Key=_bucket_key(key), Body=data, ContentType="audio/wav")
    except Exception as exc:
        log.warning("voice_sample_store_failed", key=key, error=str(exc)[:200])


async def _sample(key: str) -> bytes:
    if key in _cache:
        return _cache[key]
    async with _locks[key]:
        if key in _cache:
            return _cache[key]
        data = await _from_bucket(key)
        if not data:
            from app.routers.settings import VoicePreview, preview_voice

            name, voice_id = SAMPLES[key]
            res = await preview_voice(VoicePreview(voice_id=voice_id, text=LINE.format(name=name)))
            data = bytes(res.body)
            await _to_bucket(key, data)
        _cache[key] = data
        return data


@router.get("")
async def list_samples():
    return {"samples": [{"key": k, "name": n, "url": f"/api/public/voice-samples/{k}.wav"} for k, (n, _) in SAMPLES.items()]}


@router.get("/{key}.wav")
async def sample(key: str):
    if key not in SAMPLES:
        raise HTTPException(status_code=404, detail="No such sample")
    try:
        data = await _sample(key)
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("voice_sample_failed", key=key, error=str(exc)[:200])
        raise HTTPException(status_code=503, detail="This sample isn't available right now.")
    return Response(content=data, media_type="audio/wav",
                    headers={"Cache-Control": "public, max-age=86400", "Access-Control-Allow-Origin": "*"})
