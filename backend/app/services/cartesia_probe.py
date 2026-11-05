"""TEMPORARY: confirm which Sonic models the account's Cartesia key accepts (one tiny synth each). Remove after."""
import httpx
import structlog

from app.config import settings

log = structlog.get_logger(__name__)


async def probe() -> None:
    if not settings.cartesia_api_key:
        log.info("cartesia_probe", result="no key")
        return
    headers = {"Authorization": f"Bearer {settings.cartesia_api_key}", "Cartesia-Version": "2025-04-16"}
    async with httpx.AsyncClient(timeout=30) as client:
        for model in ("sonic-3.5", "sonic-3-5", "sonic-3-latest", "sonic-3"):
            try:
                r = await client.post("https://api.cartesia.ai/tts/bytes", headers=headers, json={
                    "model_id": model, "transcript": "Hi.", "language": "en",
                    "voice": {"mode": "id", "id": "97f03c16-fab2-4747-b655-9caefbd68fcf"},
                    "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 24000}})
                log.info("cartesia_probe", model=model, status=r.status_code, bytes=len(r.content),
                         error=r.text[:200] if r.status_code >= 400 else "")
            except Exception as exc:
                log.info("cartesia_probe", model=model, error=str(exc)[:200])
