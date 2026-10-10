"""
Settings router — which integrations are configured, and the voice catalog.
"""

from __future__ import annotations

import time

import httpx
import structlog
from fastapi import APIRouter

from app.config import settings

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/settings", tags=["settings"])

# Shown when no Cartesia key is set (or the API is unreachable). Any Cartesia
# voice ID can also be pasted into the agent editor.
_FALLBACK_VOICES = [
    {"id": "a167e0f3-df7e-4d52-a9c3-f949145efdab", "name": "Blake – Helpful Agent", "gender": "male", "language": "en"},
    {"id": "79a125e8-cd45-4c13-8a67-188112f4dd22", "name": "British Lady", "gender": "female", "language": "en"},
    {"id": "a0e99841-438c-4a64-b679-ae501e7d6091", "name": "Barbershop Man", "gender": "male", "language": "en"},
]

_voice_cache: dict = {"at": 0.0, "voices": None}


@router.get("/status")
async def integration_status():
    return {
        "database": "sqlite" if settings.is_sqlite else "postgres",
        "integrations": {
            "openai": bool(settings.openai_api_key),
            "livekit": settings.livekit_ready,
            "deepgram": bool(settings.deepgram_api_key),
            "cartesia": bool(settings.cartesia_api_key),
            "sip_trunk": bool(settings.livekit_sip_outbound_trunk_id),
            "calcom": bool(settings.calcom_api_key and settings.calcom_event_type_id),
        },
        "capabilities": {
            "chat_test": bool(settings.openai_api_key),
            "web_call": settings.voice_ready,
            "phone_call": settings.phone_ready,
            "post_call_analysis": bool(settings.openai_api_key),
        },
        "livekit_url": settings.livekit_url,
        "agent_name": settings.livekit_agent_name,
    }


@router.get("/voices")
async def list_voices():
    if not settings.cartesia_api_key:
        return {"source": "fallback", "voices": _FALLBACK_VOICES}
    if _voice_cache["voices"] and time.time() - _voice_cache["at"] < 3600:
        return {"source": "cartesia", "voices": _voice_cache["voices"]}
    try:
        voices: list[dict] = []
        params: dict = {"limit": 100}
        async with httpx.AsyncClient(timeout=10.0) as client:
            for _ in range(5):  # paginate a little; the public library is large
                resp = await client.get(
                    "https://api.cartesia.ai/voices",
                    headers={
                        "Authorization": f"Bearer {settings.cartesia_api_key}",
                        "X-API-Key": settings.cartesia_api_key,
                        "Cartesia-Version": "2025-04-16",
                    },
                    params=params,
                )
                resp.raise_for_status()
                body = resp.json()
                items = body.get("data", []) if isinstance(body, dict) else body
                for v in items:
                    voices.append({
                        "id": v.get("id"),
                        "name": v.get("name"),
                        "gender": v.get("gender") or "",
                        "language": v.get("language") or "",
                        "description": (v.get("description") or "")[:140],
                    })
                if not (isinstance(body, dict) and body.get("has_more") and items):
                    break
                params["starting_after"] = items[-1].get("id")
        voices = [v for v in voices if v["id"]]
        if not voices:
            return {"source": "fallback", "voices": _FALLBACK_VOICES}
        _voice_cache.update(at=time.time(), voices=voices)
        return {"source": "cartesia", "voices": voices}
    except Exception as exc:
        log.warning("cartesia_voices_failed", error=str(exc))
        return {"source": "fallback", "voices": _FALLBACK_VOICES}
