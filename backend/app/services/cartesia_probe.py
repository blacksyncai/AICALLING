"""TEMPORARY: list Cartesia's public voices in the languages we want to add (one line per voice). Remove after."""
import httpx
import structlog

from app.config import settings

log = structlog.get_logger(__name__)
WANT = {"es", "fr", "de", "pt", "it", "ar", "zh", "ja", "ko", "hi", "tr", "tl", "ru", "nl", "pl", "vi"}


async def probe() -> None:
    if not settings.cartesia_api_key:
        return
    headers = {"Authorization": f"Bearer {settings.cartesia_api_key}", "Cartesia-Version": "2025-04-16"}
    seen, after = 0, None
    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(40):
            params = {"limit": 100, "is_owner": "false"}
            if after:
                params["starting_after"] = after
            r = await client.get("https://api.cartesia.ai/voices", headers=headers, params=params)
            if r.status_code >= 400:
                log.info("cartesia_voices_probe", status=r.status_code, body=r.text[:200])
                return
            body = r.json()
            data = body.get("data", []) if isinstance(body, dict) else body
            for v in data:
                seen += 1
                if v.get("language") in WANT:
                    log.info("cv", l=v.get("language"), i=v.get("id"), n=(v.get("name") or "")[:40],
                             g=v.get("gender"), d=(v.get("description") or "")[:90])
            if not (isinstance(body, dict) and body.get("has_more")) or not data:
                break
            after = data[-1].get("id")
    log.info("cartesia_voices_probe_done", seen=seen)
