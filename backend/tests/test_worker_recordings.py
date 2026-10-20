import asyncio
from types import SimpleNamespace

import av
import numpy as np
import pytest
from livekit import rtc
from livekit.agents.voice import io

from app.agent import call_recorder


class Sink(io.AudioOutput):
    def __init__(self):
        super().__init__(label='test', capabilities=io.AudioOutputCapabilities(pause=False))
    async def capture_frame(self, frame): pass
    def flush(self): pass
    def clear_buffer(self): pass


@pytest.mark.asyncio
async def test_recorder_encodes_both_sides_and_uploads_once(monkeypatch):
    session = SimpleNamespace(input=SimpleNamespace(audio=io.AudioInput(label='caller')),
                              output=SimpleNamespace(audio=Sink()))
    uploaded = []
    def upload(path, key):
        with av.open(str(path)) as source:
            frames = list(source.decode(audio=0))
            assert frames
            assert frames[0].layout.name == 'stereo'
            samples = np.concatenate([f.to_ndarray() for f in frames], axis=1)
            assert np.max(np.abs(samples[0])) > .05
            assert np.max(np.abs(samples[1])) > .05
        uploaded.append(key)
    monkeypatch.setattr(call_recorder, '_upload', upload)
    recorder = call_recorder.CallRecorder(session, 'recordings/org/call.ogg')
    assert await recorder.start()
    # Use actual SDK encoding with distinct tones for caller and agent, no provider or egress connection.
    t = np.arange(4800) / 48000
    def tone(hz):
        pcm = (np.sin(2*np.pi*hz*t)*12000).astype(np.int16)
        return rtc.AudioFrame(data=pcm.tobytes(), sample_rate=48000, num_channels=1, samples_per_channel=4800)
    recorder._rec._in_q.put([tone(440)])
    recorder._rec._out_q.put([tone(660)])
    assert await recorder.finish()
    assert not await recorder.finish()
    assert uploaded == ['recordings/org/call.ogg']
    assert not recorder._dir.exists()


@pytest.mark.asyncio
async def test_upload_failure_does_not_break_call_and_cleans_up(monkeypatch):
    session = SimpleNamespace(input=SimpleNamespace(audio=io.AudioInput(label='caller')),
                              output=SimpleNamespace(audio=Sink()))
    attempts = []
    def fail(*args):
        attempts.append(True)
        raise RuntimeError('Storage unavailable')
    monkeypatch.setattr(call_recorder, '_upload', fail)
    recorder = call_recorder.CallRecorder(session, 'recordings/org/call.ogg')
    assert await recorder.start()
    frame = rtc.AudioFrame(data=np.zeros(4800,dtype=np.int16).tobytes(), sample_rate=48000,
                           num_channels=1, samples_per_channel=4800)
    recorder._rec._in_q.put([frame])
    recorder._rec._out_q.put([frame])
    assert not await recorder.finish()
    assert attempts == [True]
    assert not recorder._dir.exists()


@pytest.mark.asyncio
async def test_no_audio_cleans_up_without_recording():
    recorder = call_recorder.CallRecorder(SimpleNamespace(input=SimpleNamespace(audio=None),
                                                         output=SimpleNamespace(audio=None)), 'unused')
    assert not await recorder.start()
    assert not await recorder.finish()
    assert not recorder._dir.exists()
