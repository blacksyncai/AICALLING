import asyncio
import base64
import json
from types import SimpleNamespace

import aiohttp
import pytest

from app.agent.expressions import enabled_for, instructions, opening_delivery, speech_text
from app.agent.inference_tts import make_livekit_tts, _options
from app.config import settings

MACCO='lkcartesia:v_ZMqDxhK7B6i6'


def ready(monkeypatch):
    monkeypatch.setattr(settings,'livekit_api_key','test-lk-key')
    monkeypatch.setattr(settings,'livekit_api_secret','test-lk-secret')
    monkeypatch.setattr(settings,'livekit_url','wss://test.invalid')


def test_hosted_sonic_uses_automatic_guidance_and_curiosity():
    cfg={'voice_id':MACCO,'voice_tuning':{'expressions_enabled':True,'expression_mode':'automatic'}}
    assert enabled_for(cfg)
    assert '# AUTOMATIC DELIVERY' in instructions(cfg)
    assert opening_delivery('Hey, this is James, right?',cfg)=='<emotion value="curious"/>Hey, this is James, right?'
    for voice in ['inworld:v_ZMqDxhK7B6i6','fishaudio:v_example','elevenlabs:sample','lkcartesia:x','mistral:sample']:
        assert not enabled_for({**cfg,'voice_id':voice})
    assert not enabled_for({'voice_id':MACCO})


def test_other_hosted_providers_do_not_receive_emotion_or_volume():
    assert _options('inworld:',1.0,emotion='curious',volume=1.2)=={'speaking_rate':1.0}
    assert _options('fishaudio:',1.0,emotion='curious',volume=1.2)=={'latency':'low','speed':1.0}
    with pytest.raises(ValueError):
        _options('lkcartesia:',1.0,emotion='unknown')


def test_real_inference_sdk_sends_controls_and_complete_tags(monkeypatch):
    ready(monkeypatch)
    class Socket:
        def __init__(self): self.sent=[];self.queue=asyncio.Queue();self.closed=False
        async def send_str(self,raw):
            message=json.loads(raw);self.sent.append(message)
            if message['type']=='session.flush':
                for item in [
                    {'type':'output_audio','session_id':'test-session','audio':base64.b64encode(b'\x00'*4800).decode()},
                    {'type':'done','session_id':'test-session'},
                ]:
                    await self.queue.put(SimpleNamespace(type=aiohttp.WSMsgType.TEXT,data=json.dumps(item)))
        async def receive(self,**kwargs):return await self.queue.get()
        async def close(self):self.closed=True
    class Session:
        def __init__(self,socket):self.socket=socket
        async def ws_connect(self,*args,**kwargs):return self.socket
    async def run():
        ws=Socket()
        tts=make_livekit_tts(MACCO,language='en',speed=1.0,emotion='Curious',volume=1.15,http_session=Session(ws))
        text='<emotion value="calm"/>Hello James?<break time="200ms"/>[laughter] Thanks.'
        frames=[]
        async def source():
            for char in text:yield char
        async with tts.stream() as stream:
            async def send():
                async for piece in speech_text(source(),True):stream.push_text(piece)
                stream.end_input()
            task=asyncio.create_task(send())
            frames=[event.frame async for event in stream]
            await task
        await tts.aclose()
        assert frames and sum(frame.samples_per_channel for frame in frames)>0
        created=next(packet for packet in ws.sent if packet['type']=='session.create')
        assert created['model']=='cartesia/sonic-3.5' and created['voice']=='v_ZMqDxhK7B6i6'
        assert created['extra']=={'speed':1.0,'emotion':'curious','volume':1.15}
        inputs=[packet for packet in ws.sent if packet['type']=='input_transcript']
        assert inputs and all(packet['extra']==created['extra'] for packet in inputs)
        actual=''.join(packet['transcript'] for packet in inputs)
        assert '<emotion value="calm"/>' in actual and '<break time="200ms"/>' in actual and '[laughter]' in actual
        assert ws.closed
    asyncio.run(asyncio.wait_for(run(),10))


def test_hosted_preview_passes_emotion_and_cache_separates_it(client,monkeypatch):
    from app.routers import settings as router
    ready(monkeypatch)
    sent=[]
    async def synthesize(voice,text,**kwargs):
        sent.append((voice,text,kwargs));return b'RIFF-test'
    monkeypatch.setattr(router.inference_tts,'synthesize_wav',synthesize)
    router._preview_cache.clear()
    body={'voice_id':MACCO,'text':'<emotion value="curious"/>Hey James?', 'expressions_enabled':True,
          'expression_mode':'script','default_emotion':'calm'}
    assert client.post('/api/settings/voices/preview',json=body).status_code==200
    assert sent[-1][1]=='Hey James?' and sent[-1][2]['emotion']=='curious'
    assert client.post('/api/settings/voices/preview',json=body).status_code==200 and len(sent)==1
    assert client.post('/api/settings/voices/preview',json={**body,'default_emotion':'curious'}).status_code==200
    assert sent[-1][2]['emotion']=='curious' and len(sent)==1
    assert client.post('/api/settings/voices/preview',json={**body,'expression_mode':'automatic'}).status_code==200
    assert sent[-1][2]['emotion']=='curious'
    assert client.post('/api/settings/voices/preview',json={**body,'expressions_enabled':False}).status_code==200
    assert sent[-1][1]=='Hey James?' and 'emotion' not in sent[-1][2]


def test_catalog_and_mcp_advertise_macco_v1_support(client,make_client):
    from tests.test_connector import _connect,_tool
    catalog=client.get('/api/settings/voices').json()['voices']
    assert next(v for v in catalog if v['id']==MACCO)['voice_expressions_supported'] is True
    assert next(v for v in catalog if v['id']=='inworld:v_ZMqDxhK7B6i6')['voice_expressions_supported'] is False
    anon=make_client();token=_connect(client,anon)['access_token']
    voices,err=_tool(anon,token,'list_voices')
    assert not err
    assert next(v for v in voices['voices'] if v['id']==MACCO)['voice_expressions_supported'] is True
    agent=client.post('/api/agents/',json={'template':'blank'}).json()
    updated=client.patch(f"/api/agents/{agent['id']}",json={'voice_id':MACCO,'voice_tuning':{
        'expressions_enabled':True,'expression_mode':'automatic'}})
    assert updated.status_code==200
    read,err=_tool(anon,token,'get_agent',{'agent_id':agent['id']})
    assert not err and read['voice_expressions_supported'] is True
