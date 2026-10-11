"""
Call recordings — LiveKit egress mixes the room's audio (caller + agent) into one
OGG file and uploads it straight to an S3-compatible bucket (Railway Buckets,
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
        Params={"Bucket": settings.recordings_s3_bucket, "Key": key, "ResponseContentType": "audio/ogg"},
        ExpiresIn=URL_TTL_SECONDS,
    )


async def playback_url(key: str) -> str | None:
    """A presigned URL once the file has landed in the bucket, else None (still processing)."""
    if not settings.recordings_ready or not key:
        return None
    if not await asyncio.to_thread(_exists, key):
        return None
    return await asyncio.to_thread(_presign, key)
