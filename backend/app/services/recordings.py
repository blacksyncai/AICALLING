"""
Call recordings — LiveKit egress records the room's audio into one two-channel OGG file (the agent on
one side, the caller on the other) and uploads it straight to an S3-compatible bucket (Railway Buckets,
Cloudflare R2, AWS S3…). Playback uses short-lived presigned URLs, so the bucket
stays private and every request goes through the account check first.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog

from app.config import settings
from app.models.agent import Agent

log = structlog.get_logger(__name__)

URL_TTL_SECONDS = 15 * 60


def enabled_for(agent: Agent | None) -> bool:
    return settings.recordings_ready and (agent is None or agent.record_calls is not False)


def key_for(org_id: uuid.UUID, call_id: uuid.UUID) -> str:
    return f"recordings/{org_id}/{call_id}.ogg"


async def start(room_name: str, key: str) -> str:
    """Start recording the room; returns the egress ID."""
    from livekit import api

    from app.services.outbound_call import _lk

    s3 = api.S3Upload(
        access_key=settings.recordings_s3_access_key,
        secret=settings.recordings_s3_secret_key,
        region=settings.recordings_s3_region or "auto",
        endpoint=settings.recordings_s3_endpoint,
        bucket=settings.recordings_s3_bucket,
        force_path_style=settings.recordings_s3_force_path_style,
    )
    lk = _lk()
    try:
        info = await lk.egress.start_room_composite_egress(api.RoomCompositeEgressRequest(
            room_name=room_name,
            audio_only=True,
            # Agent and caller on separate channels: Radar re-checks voicemail greetings on the caller's side.
            audio_mixing=api.AudioMixing.DUAL_CHANNEL_AGENT,
            file_outputs=[api.EncodedFileOutput(file_type=api.EncodedFileType.OGG, filepath=key, s3=s3)],
        ))
    finally:
        await lk.aclose()
    log.info("recording_started", room=room_name, egress_id=info.egress_id, key=key)
    return info.egress_id


def _s3():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.recordings_s3_endpoint or None,
        region_name=settings.recordings_s3_region or "auto",
        aws_access_key_id=settings.recordings_s3_access_key,
        aws_secret_access_key=settings.recordings_s3_secret_key,
        config=Config(signature_version="s3v4",
                      s3={"addressing_style": "path" if settings.recordings_s3_force_path_style else "auto"}),
    )


def _exists(key: str) -> bool:
    try:
        _s3().head_object(Bucket=settings.recordings_s3_bucket, Key=key)
        return True
    except Exception:
        return False


def _presign(key: str) -> str:
    return _s3().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.recordings_s3_bucket, "Key": key, "ResponseContentType": "audio/mpeg" if key.endswith(".mp3") else "audio/ogg"},
        ExpiresIn=URL_TTL_SECONDS,
    )


async def playback_url(key: str) -> str | None:
    """A presigned URL once the file has landed in the bucket, else None (still processing)."""
    if not settings.recordings_ready or not key:
        return None
    if not await asyncio.to_thread(_exists, key):
        return None
    return await asyncio.to_thread(_presign, key)


# ── Download as MP3 ──────────────────────────────────────────────────────────


def mp3_key(key: str) -> str:
    return key if key.endswith(".mp3") else key.rsplit(".", 1)[0] + ".mp3"


def _to_mp3(data: bytes) -> bytes:
    """Any recording (OGG/Opus from browser tests or older egress files) → MP3, keeping its channels."""
    import io

    import av

    src = av.open(io.BytesIO(data))
    ain = src.streams.audio[0]
    out_buf = io.BytesIO()
    dst = av.open(out_buf, mode="w", format="mp3")
    layout = "stereo" if (ain.codec_context.channels or 1) > 1 else "mono"
    aout = dst.add_stream("libmp3lame", rate=44100, layout=layout)
    aout.bit_rate = 96_000
    resampler = av.AudioResampler(format=aout.codec_context.format, layout=layout, rate=44100)
    for frame in src.decode(ain):
        for rf in resampler.resample(frame):
            for pkt in aout.encode(rf):
                dst.mux(pkt)
    for rf in resampler.resample(None):
        for pkt in aout.encode(rf):
            dst.mux(pkt)
    for pkt in aout.encode(None):
        dst.mux(pkt)
    dst.close()
    src.close()
    return out_buf.getvalue()


def _ensure_mp3(key: str) -> str | None:
    """The MP3 copy of a recording (converted and stored next to it the first time). None if there's no file."""
    target = mp3_key(key)
    if _exists(target):
        return target
    if target == key:
        return None
    try:
        body = _s3().get_object(Bucket=settings.recordings_s3_bucket, Key=key)["Body"].read()
    except Exception:
        return None
    _s3().put_object(Bucket=settings.recordings_s3_bucket, Key=target, Body=_to_mp3(body), ContentType="audio/mpeg")
    return target


def _presign_download(key: str, filename: str) -> str:
    return _s3().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.recordings_s3_bucket, "Key": key, "ResponseContentType": "audio/mpeg",
                "ResponseContentDisposition": f'attachment; filename="{filename}"'},
        ExpiresIn=URL_TTL_SECONDS,
    )


async def download_url(key: str, filename: str) -> str | None:
    """A short-lived link that downloads the recording as an MP3 file (None while it's still processing)."""
    if not settings.recordings_ready or not key:
        return None
    target = await asyncio.to_thread(_ensure_mp3, key)
    if not target:
        return None
    return await asyncio.to_thread(_presign_download, target, filename)
