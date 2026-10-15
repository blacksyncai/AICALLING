"""
Recording a browser test call inside the voice worker (opt-in: "Record this call").

LiveKit's RecorderIO taps the agent session's audio input (the tester's microphone) and output (the agent's
voice as it plays) and encodes them, aligned on the playout timeline, into one stereo OGG file on a background
thread — the conversation's audio path isn't changed or delayed. The file is uploaded to the recordings bucket
after the call ends. We don't use the session's own `record=True`: that also uploads the audio to LiveKit Cloud.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


class CallRecorder:
    def __init__(self, session, key: str) -> None:
        self.session, self.key = session, key
        self._rec = None
        self._dir = Path(tempfile.mkdtemp(prefix="callrec-"))
        self._done = False

    async def start(self) -> bool:
        """Attach to the running session. Returns False (and records nothing) if the audio isn't available."""
        from livekit.agents.voice.recorder_io import RecorderIO

        if not (self.session.input.audio and self.session.output.audio):
            return False
        rec = RecorderIO(agent_session=self.session)
        self.session.input.audio = rec.record_input(self.session.input.audio)
        self.session.output.audio = rec.record_output(self.session.output.audio)
        await rec.start(output_path=self._dir / "call.ogg")
        self._rec = rec
        return True

    async def finish(self) -> bool:
        """Close the file and upload it. Safe to call more than once; never raises."""
        if self._done or self._rec is None:
            return False
        self._done = True
        try:
            await asyncio.wait_for(self._rec.aclose(), timeout=30)
            path = self._rec.output_path
            if not path or not path.exists() or path.stat().st_size == 0:
                log.warning("call_recording_empty", key=self.key)
                return False
            await asyncio.to_thread(_upload, path, self.key)
            log.info("call_recording_saved", key=self.key, bytes=path.stat().st_size)
            return True
        except Exception as exc:
            log.warning("call_recording_failed", key=self.key, error=str(exc)[:300])
            return False
        finally:
            shutil.rmtree(self._dir, ignore_errors=True)


def _upload(path: Path, key: str) -> None:
    from app.config import settings
    from app.services.recordings import _s3

    with open(path, "rb") as f:
        _s3().put_object(Bucket=settings.recordings_s3_bucket, Key=key, Body=f, ContentType="audio/ogg")
