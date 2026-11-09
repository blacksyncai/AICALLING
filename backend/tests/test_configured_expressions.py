import asyncio
import base64
import io
import json
import wave
from types import SimpleNamespace

import aiohttp

from app.agent.expressions import ConfiguredExpressionAudio, synthesize_configured_expressions


async def chunks(*values):
    for value in values:
        yield value


def test_scoped_configuration_split_tags_first_audio_and_new_turn_reset():
    async def run():
        requests = []
        release = asyncio.Event()
        async def source():
            for char in '<emotion value="curious"/>Hello?':
                yield char
            await release.wait()
            yield '<emotion value="calm"/>Thanks.<emotion value="neutral"/> Goodbye.'
        async def render(text, emotion):
            request = {'emotion': emotion, 'text': ''}
            requests.append(request)
            async for part in text:
                request['text'] += part
                yield part
        stream = synthesize_configured_expressions(source(), render)
        assert await asyncio.wait_for(anext(stream), .2) == 'H'
        assert requests[0]['emotion'] == 'curious'
        release.set()
        rest = ''.join([part async for part in stream])
        assert 'H' + rest == 'Hello?Thanks. Goodbye.'
        assert requests == [{'emotion': 'curious', 'text': 'Hello?'},
                            {'emotion': 'calm', 'text': 'Thanks.'},
                            {'emotion': 'neutral', 'text': ' Goodbye.'}]
        assert ''.join([part async for part in synthesize_configured_expressions(chunks('Next turn.'), render)]) == 'Next turn.'
        assert requests[-1]['emotion'] is None
    asyncio.run(run())


def test_real_hosted_sdk_receives_per_generation_emotion_without_emotion_markup(monkeypatch):
    from app.agent.inference_tts import make_livekit_tts
    from app.config import settings
    monkeypatch.setattr(settings, 'livekit_api_key', 'test-lk-key')
    monkeypatch.setattr(settings, 'livekit_api_secret', 'test-lk-secret-long-enough-for-local-unit-tests')
    packets = []
    class Socket:
        def __init__(self): self.queue = asyncio.Queue()
        async def send_str(self, raw):
            message = json.loads(raw); packets.append(message)
            if message['type'] == 'session.flush':
                for item in [{'type': 'output_audio', 'session_id': 'test', 'audio': base64.b64encode(b'\x00' * 4800).decode()},
                             {'type': 'done', 'session_id': 'test'}]:
                    await self.queue.put(SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(item)))
        async def receive(self, **kwargs): return await self.queue.get()
        async def close(self): pass
    class Session:
        async def ws_connect(self, *args, **kwargs): return Socket()
    def factory(emotion):
        return make_livekit_tts('lkcartesia:v_ZMqDxhK7B6i6', emotion=emotion, http_session=Session())
    async def run():
        base = factory(None)
        audio = ConfiguredExpressionAudio(base, factory, conn_options=lambda: __import__('livekit.agents', fromlist=['APIConnectOptions']).APIConnectOptions())
        source = chunks(*'<emotion value="curious"/>Hey James?<emotion value="calm"/>Thanks.<emotion value="neutral"/>Bye.')
        try:
            frames = [frame async for frame in synthesize_configured_expressions(source, audio.synthesize)]
            assert frames
            created = [p for p in packets if p['type'] == 'session.create']
            assert [p['extra']['emotion'] for p in created] == ['curious', 'calm', 'neutral']
            inputs = [p for p in packets if p['type'] == 'input_transcript']
            assert ' '.join(''.join(p['transcript'] for p in inputs).split()) == 'Hey James? Thanks. Bye.'
            assert all('<emotion' not in p['transcript'] for p in inputs)
        finally:
            await audio.aclose(); await base.aclose()
    asyncio.run(asyncio.wait_for(run(), 10))


def test_preview_changes_config_and_combines_real_wav_frames(client, monkeypatch):
    from app.config import settings
    from app.routers import settings as router
    monkeypatch.setattr(settings, 'cartesia_api_key', 'test-key')
    sent = []
    async def synthesize(payload):
        sent.append(payload)
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(24000)
            audio.writeframes(b'\x00' * 480)
        return buffer.getvalue()
    monkeypatch.setattr(router, '_synthesize', synthesize)
    router._preview_cache.clear()
    result = client.post('/api/settings/voices/preview', json={
        'voice_id': '67076421-33a2-4dc5-b8b3-49dfdea3ae69', 'expressions_enabled': True,
        'text': '<emotion value="curious"/>Hey?<emotion value="neutral"/>Thanks.'})
    assert result.status_code == 200
    assert [(p['transcript'], p['generation_config']['emotion']) for p in sent] == [('Hey?', 'curious'), ('Thanks.', 'neutral')]
    with wave.open(io.BytesIO(result.content), 'rb') as audio:
        assert audio.getnframes() == 480


def test_cancel_closes_source_and_does_not_carry_emotion_to_new_speech():
    async def run():
        closed = []
        requested = []
        async def source():
            try:
                yield '<emotion value="angry"/>Hello.'
                await asyncio.Event().wait()
            finally:
                closed.append('source')
        async def render(text, emotion):
            requested.append(emotion)
            try:
                async for part in text:
                    yield part
            finally:
                closed.append('render')
        stream = synthesize_configured_expressions(source(), render)
        assert await anext(stream) == 'Hello.'
        await stream.aclose()
        assert sorted(closed) == ['render', 'source']
        assert ''.join([part async for part in synthesize_configured_expressions(chunks('New speech.'), render)]) == 'New speech.'
        assert requested == ['angry', None]
    asyncio.run(run())
