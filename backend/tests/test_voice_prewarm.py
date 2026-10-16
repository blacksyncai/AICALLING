import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest


def test_worker_registers_turn_models_before_cli_starts():
    # A fresh interpreter reproduces download-files startup: pytest imports must not hide late registration.
    code = '''import json
import agent_worker
from livekit.agents import Plugin
from livekit.agents.inference_runner import _InferenceRunner
print(json.dumps({'plugins':[p.package for p in Plugin.registered_plugins], 'runners':list(_InferenceRunner.registered_runners)}))
'''
    result = subprocess.run([sys.executable, '-c', code], text=True, capture_output=True, timeout=40,
                            env={**os.environ, 'LOW_RESOURCE_MODE':'true'})
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout.strip().splitlines()[-1])
    assert 'lk_end_of_utterance_multilingual' in data['runners']
    assert any('turn_detector' in name for name in data['plugins'])


def test_process_warms_vad_once_and_jobs_reuse_it(monkeypatch):
    import agent_worker as worker
    loaded = []
    def load():
        vad = object()
        loaded.append(vad)
        return vad
    monkeypatch.setattr(worker.silero.VAD, 'load', load)
    proc = SimpleNamespace(userdata={})
    worker._prewarm_process(proc)
    ctx = SimpleNamespace(proc=proc)
    assert worker._job_vad(ctx) is worker._job_vad(ctx) is loaded[0]
    assert len(loaded) == 1
    # Contexts without a prewarm hook still load once and reuse the fallback.
    ctx2 = SimpleNamespace(proc=SimpleNamespace(userdata={}))
    assert worker._job_vad(ctx2) is worker._job_vad(ctx2)
    assert len(loaded) == 2


@pytest.mark.asyncio
async def test_voice_socket_warmup_is_closed_even_without_answer():
    import agent_worker as worker
    events = []
    callbacks = []
    def warm(): events.append('warm')
    async def close(): events.append('close')
    tts = SimpleNamespace(prewarm=warm, aclose=close)
    ctx = SimpleNamespace(add_shutdown_callback=callbacks.append)
    assert worker._prewarm_tts(tts, ctx)
    assert events == ['warm']
    await callbacks[0]()
    assert events == ['warm', 'close']


def test_voice_warmup_failure_does_not_block_calls():
    import agent_worker as worker
    def fail(): raise RuntimeError('Unavailable')
    ctx = SimpleNamespace(add_shutdown_callback=lambda cb: None)
    assert not worker._prewarm_tts(SimpleNamespace(prewarm=fail), ctx)
    assert not worker._prewarm_tts(SimpleNamespace(), ctx)
