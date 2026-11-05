"""TEMPORARY: check Sonic 3.5 emotion values and the instant-clone endpoint on the account's key. Remove after."""
import httpx
import structlog

from app.config import settings

log = structlog.get_logger(__name__)
_VOICE = "97f03c16-fab2-4747-b655-9caefbd68fcf"


async def probe() -> None:
    if not settings.cartesia_api_key:
        return
    headers = {"Authorization": f"Bearer {settings.cartesia_api_key}", "Cartesia-Version": "2025-04-16"}
    async with httpx.AsyncClient(timeout=60) as client:
        def body(text, **gen):
            b = {"model_id": "sonic-3.5", "transcript": text, "language": "en",
                 "voice": {"mode": "id", "id": _VOICE},
                 "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 24000}}
            if gen:
                b["generation_config"] = gen
            return b
        for emotion in ("Content", "Enthusiastic", "Calm", "Happy", "Sympathetic"):
            r = await client.post("https://api.cartesia.ai/tts/bytes", headers=headers, json=body("Hi there.", emotion=emotion, speed=1.0))
            log.info("cartesia_probe_emotion", emotion=emotion, status=r.status_code, error=r.text[:160] if r.status_code >= 400 else "")
        # Instant clone from a generated clip, then delete it again.
        clip = await client.post("https://api.cartesia.ai/tts/bytes", headers=headers, json=body(
            "Hey, this is a short sample recording to test cloning. We help homeowners sell faster, and I'd love to "
            "tell you how it works. Give me a call back when you get a chance, thanks so much."))
        if clip.status_code != 200:
            log.info("cartesia_probe_clone", step="clip", status=clip.status_code)
            return
        r = await client.post("https://api.cartesia.ai/voices/clone", headers=headers,
                              files={"clip": ("sample.wav", clip.content, "audio/wav")},
                              data={"name": "BlackSync clone test (delete)", "language": "en", "mode": "similarity",
                                    "enhance": "false"})
        log.info("cartesia_probe_clone", step="clone", status=r.status_code, body=r.text[:300])
        vid = (r.json() or {}).get("id") if r.status_code < 300 else None
        if vid:
            d = await client.delete(f"https://api.cartesia.ai/voices/{vid}", headers=headers)
            log.info("cartesia_probe_clone", step="delete", status=d.status_code)
