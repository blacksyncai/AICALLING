import asyncio
import time

import pytest

from app.agent.expressions import MarkupParser, clean_markup, speech_text, synthesize_expressions, enabled_for, instructions
from app.agent.speech_guard import clean, guarded


async def chunks(*values):
    for value in values:
        yield value


def test_streaming_controls_at_every_split():
    text = '<emotion value="curious"/>Hey, James?<break time="0.2s"/>[laughter] Sure.'
    expected = '<emotion value="curious"/>Hey, James?<break time="200ms"/>[laughter] Sure.'
    for split in range(len(text)+1):
        p = MarkupParser(True)
        assert p.feed(text[:split]) + p.feed(text[split:]) + p.flush() == expected
    async def run():
        return ''.join([c async for c in speech_text(chunks(*text), True)])
    assert asyncio.run(run()) == expected


def test_encoded_invalid_and_bounded_controls():
    assert clean_markup('&lt;emotion value=&quot;calm&quot;/&gt;Hi', True) == '<emotion value="calm"/>Hi'
    for tag in ['<emotion value="invented"/>', '<break time="-2s"/>', '<break time="NaNms"/>',
                '<break time="2001ms"/>', '<break time="0ms"/>', '<break time="0.5ms"/>',
                '<audio src="http://bad"/>', '<emotion value="calm" extra="x"/>']:
        assert clean_markup(tag+'Hello', True) == 'Hello'
    assert clean_markup('<'+'x'*10000+'>Hello', True) == 'Hello'
    p = MarkupParser(True)
    assert p.feed('<'+'x'*10000) == '' and len(p.pending) <= 256
    assert p.flush() == ''
    assert clean_markup('Hello <emotion value="cur', True) == 'Hello '
    assert clean_markup('[laughter]Hi[laughter]Bye', True) == '[laughter]HiBye'
    assert clean_markup('<break time="2s"/><break time="2s"/>', True) == '<break time="2000ms"/>'


def test_opt_out_and_other_providers_never_receive_controls():
    raw='<emotion value="curious"/>Hello<break time="200ms"/>[laughter] world'
    assert clean_markup(raw) == 'Hello world'
    for voice in ['elevenlabs:x', 'fishaudio:x', 'inworld:x', 'lkcartesia:x', 'mistral:x']:
        cfg={'voice_id':voice,'voice_tuning':{'expressions_enabled':True}}
        assert not enabled_for(cfg) and instructions(cfg) == ''
    assert not enabled_for({'voice_id':'cartesia-id'})


def test_first_message_and_guarded_reply_controls_and_stage_directions():
    raw='<emotion value="curious"/>Hey James? [laughter] Good to hear. [Wait for answer] Continue.'
    expected='<emotion value="curious"/>Hey James? [laughter] Good to hear.'
    assert clean(raw, expressions=True) == expected
    async def run():
        return ''.join([c async for c in guarded(chunks(*raw), expressions=True)]).strip()
    assert asyncio.run(run()) == expected
    assert clean(raw) == 'Hey James?  Good to hear.'


def test_new_generation_for_emotion_change_without_holding_first_audio():
    async def run():
        events=[]
        release=asyncio.Event()
        async def source():
            yield '<emotion value="curious"/>Hello James? '
            await release.wait()
            yield '<emotion value="calm"/>Thanks for confirming.'
        async def synthesize(text):
            generation=[]
            events.append(generation)
            async for piece in text:
                generation.append(piece)
                yield piece
        stream=synthesize_expressions(source(), synthesize)
        assert await asyncio.wait_for(anext(stream), .1) == '<emotion value="curious"/>'
        assert await asyncio.wait_for(anext(stream), .1) == 'Hello James? '
        release.set()
        rest=[c async for c in stream]
        assert ''.join(rest)=='<emotion value="calm"/>Thanks for confirming.'
        assert [''.join(g) for g in events] == ['<emotion value="curious"/>Hello James? ',
                                               '<emotion value="calm"/>Thanks for confirming.']
    asyncio.run(run())


def test_cancel_does_not_leak_state_or_leave_generation_running():
    async def run():
        closed=[]
        async def synthesize(text):
            try:
                async for c in text:
                    yield c
            finally: closed.append(True)
        stream=synthesize_expressions(chunks('<emotion value="calm"/>Hello', '<emotion value="cur'), synthesize)
        await anext(stream)
        await stream.aclose()
        assert closed == [True]
        new=synthesize_expressions(chunks('New reply.'), synthesize)
        assert ''.join([c async for c in new]) == 'New reply.'
    asyncio.run(run())


def test_agent_config_roundtrip_and_rejects_unknown_emotion(client, agent_id):
    from app.agent.runtime import build_instructions
    original=client.get(f'/api/agents/{agent_id}').json()
    assert not (original.get('voice_tuning') or {}).get('expressions_enabled', False)
    updated=client.patch(f'/api/agents/{agent_id}', json={'voice_tuning':{
        'expressions_enabled':True,'default_emotion':'curious'}})
    assert updated.status_code == 200, updated.text
    assert updated.json()['voice_tuning']['default_emotion'] == 'curious'
    cfg=updated.json()
    assert '# OPTIONAL VOCAL DELIVERY' in build_instructions(cfg,{},channel='phone')
    assert '# OPTIONAL VOCAL DELIVERY' not in build_instructions(cfg,{},channel='chat')
    assert client.patch(f'/api/agents/{agent_id}', json={'voice_tuning':{'default_emotion':'not-real'}}).status_code == 422
    assert '# OPTIONAL VOCAL DELIVERY' not in build_instructions(original,{},channel='phone')


def test_real_sdk_generation_config_and_same_model_fallback(monkeypatch):
    import agent_worker
    from app.config import settings
    from livekit.plugins.cartesia.tts import _to_cartesia_options
    from app.agent.voice_trace import short_sentence_tokenizer
    monkeypatch.setattr(settings, 'cartesia_api_key', 'fake-cartesia-key')
    monkeypatch.setattr(settings, 'cartesia_fallback_enabled', True)
    monkeypatch.setattr(settings, 'livekit_url', 'wss://test.invalid')
    monkeypatch.setattr(settings, 'livekit_api_key', 'fake-lk-key')
    monkeypatch.setattr(settings, 'livekit_api_secret', 'fake-lk-secret')
    async def run():
        tts=agent_worker.cartesia_tts('voice-id',language='en',speed=1.0,volume=1.1,emotion='curious',
                                    tokenizer=short_sentence_tokenizer(True),expressions_enabled=True)
        primary,backup=tts._tts_instances
        for _ in range(2):
            stream=primary.stream()
            payload=_to_cartesia_options(stream._opts, streaming=True)
            assert payload['model_id']=='sonic-3.5'
            assert payload['generation_config']=={'speed':1.0,'emotion':'curious','volume':1.1}
            await stream.aclose()
        assert backup._opts.extra_kwargs['emotion']=='curious'
        assert backup._opts.model=='cartesia/sonic-3.5'
        await tts.aclose()
    asyncio.run(run())


def test_real_tokenizer_and_pronunciations_preserve_controls():
    from app.agent.voice_tuning import pronounce
    from app.agent.voice_trace import short_sentence_tokenizer
    raw='<emotion value="curious"/>Hey James. <break time="200ms"/>[laughter] That is curious.'
    async def run():
        transformed=pronounce([('curious','CURE-ee-us'),('James','Jaymz'),('time','thyme'),('laughter','laugh')],preserve_markup=True)
        ready=''.join([c async for c in transformed(speech_text(chunks(*raw),True))])
        assert '<emotion value="curious"/>' in ready and '<break time="200ms"/>' in ready
        assert '[laughter]' in ready and 'Jaymz' in ready and 'That is CURE-ee-us.' in ready
        stream=short_sentence_tokenizer(True).stream()
        stream.push_text(ready)
        stream.end_input()
        tokens=[event.token async for event in stream]
        await stream.aclose()
        actual=' '.join(tokens)
        assert '<emotion value="curious"/>' in actual and '<break time="200ms"/>' in actual and '[laughter]' in actual
    asyncio.run(run())


def test_preview_sends_real_config_and_cleans_other_provider_markup(client, monkeypatch):
    from app.config import settings
    from app.routers import settings as router
    sent=[]
    async def synthesize(payload):
        sent.append(payload)
        return b'RIFF-test-wav'
    monkeypatch.setattr(settings,'cartesia_api_key','test-key')
    monkeypatch.setattr(router,'_synthesize',synthesize)
    router._preview_cache.clear()
    result=client.post('/api/settings/voices/preview',json={
        'voice_id':'a207b2d0-08df-4188-a63d-0578c2fce93b','expressions_enabled':True,
        'default_emotion':'calm','text':'<emotion value="curious"/>Hey James?<break time="200ms"/>'})
    assert result.status_code == 200
    assert sent[0]['model_id']=='sonic-3.5'
    assert sent[0]['generation_config']['emotion']=='calm'
    assert sent[0]['transcript']=='<emotion value="curious"/>Hey James?<break time="200ms"/>'
    async def eleven(voice,text,**kwargs):
        assert text == 'Hello there'
        return b'RIFF-other'
    monkeypatch.setattr(settings,'elevenlabs_api_key','test-key')
    monkeypatch.setattr(router.elevenlabs_tts,'synthesize_wav',eleven)
    result=client.post('/api/settings/voices/preview',json={'voice_id':'elevenlabs:WkIfOTQgqfIPfV7X7nND',
        'expressions_enabled':True,'text':'<emotion value="curious"/>Hello<break time="200ms"/>[laughter] there'})
    assert result.status_code == 200


def test_interruption_closes_upstream_text_iterator():
    async def run():
        closed=[]
        async def source():
            try:
                yield '<emotion value="calm"/>Hello'
                yield 'Never reached'
            finally:
                closed.append(True)
        async def synthesize(text):
            async for c in text: yield c
        stream=synthesize_expressions(source(),synthesize)
        await anext(stream)
        await stream.aclose()
        assert closed == [True]
    asyncio.run(run())
