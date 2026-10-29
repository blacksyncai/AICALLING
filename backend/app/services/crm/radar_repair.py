"""TEMPORARY check (remove after it has run): Marissa M (Fish Audio via LiveKit Inference) speaks."""
import time

import structlog

log = structlog.get_logger(__name__)


async def run():
    from app.agent import fish_tts

    t = time.monotonic()
    try:
        wav = await fish_tts.synthesize_wav("fishaudio:v_SriZAPqzgffq", "Hi, is this Mike? This is Marissa from BlackSync.")
        log.info("fish_voice_check", ok=True, bytes=len(wav), seconds=round(time.monotonic() - t, 2))
    except Exception as exc:
        log.warning("fish_voice_check", ok=False, error=f"{type(exc).__name__}: {str(exc)[:300]}")
