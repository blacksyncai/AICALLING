"""TEMPORARY check (remove after it has run): Macco on Cartesia Sonic 3.5 and Inworld TTS 2 via LiveKit."""
import time

import structlog

log = structlog.get_logger(__name__)


async def run():
    from app.agent import inference_tts

    for vid in ("lkcartesia:v_ZMqDxhK7B6i6", "inworld:v_ZMqDxhK7B6i6"):
        t = time.monotonic()
        try:
            wav = await inference_tts.synthesize_wav(vid, "Hey, is this Mike? This is Macco from BlackSync.")
            log.info("inference_voice_check", voice=vid, ok=True, bytes=len(wav), seconds=round(time.monotonic() - t, 2))
        except Exception as exc:
            log.warning("inference_voice_check", voice=vid, ok=False, error=f"{type(exc).__name__}: {str(exc)[:300]}")
