import io
import wave
import httpx
import pytest
from app.agent import elevenlabs_tts as eleven
from app.config import settings
from app.routers import settings as catalog
MATT='elevenlabs:iRh44YCGcZyLpQjPFMsh'

def test_matt_premium_without_cartesia(client,monkeypatch):
    monkeypatch.setattr(settings,'cartesia_api_key','')
    monkeypatch.setattr(settings,'elevenlabs_api_key','test-key')
    body=client.get('/api/settings/voices').json()
    matt=next(v for v in body['voices'] if v['id']==MATT)
    assert matt['name']=='Matt' and matt['category']=='premium' and matt['provider']=='elevenlabs'
    assert matt['models']==['eleven_flash_v2_5'] and matt['preview'] is True
    assert body['preview_available'] is True

@pytest.mark.asyncio
async def test_sdk_constructor(monkeypatch):
    monkeypatch.setattr(settings,'elevenlabs_api_key','test-key')
    tts=eleven.make_livekit_tts(MATT,speed=1.1)
    assert tts._opts.voice_id=='iRh44YCGcZyLpQjPFMsh'
    assert tts._opts.model=='eleven_flash_v2_5'
    assert tts.sample_rate==24000 and tts._opts.encoding=='pcm_24000'
    assert tts._opts.voice_settings.speed==1.1
    await tts.aclose()

def test_missing_key_never_falls_back(monkeypatch):
    monkeypatch.setattr(settings,'elevenlabs_api_key','')
    with pytest.raises(ValueError,match='API key'):eleven.make_livekit_tts(MATT)

@pytest.mark.parametrize('voice',['elevenlabs:../../admin','elevenlabs:','cartesia:iRh44YCGcZyLpQjPFMsh'])
def test_invalid_ids(voice):
    with pytest.raises(ValueError):eleven.provider_voice_id(voice)

def test_agent_speed_validation_preserves_script(client,agent_id):
    before=client.get(f'/api/agents/{agent_id}').json()
    assert client.patch(f'/api/agents/{agent_id}',json={'voice_id':MATT,'voice_speed':1.3}).status_code==422
    assert client.get(f'/api/agents/{agent_id}').json()['voice_id']==before['voice_id']
    good=client.patch(f'/api/agents/{agent_id}',json={'voice_id':MATT,'voice_speed':1.0})
    assert good.status_code==200 and good.json()['voice_id']==MATT
    assert good.json()['system_prompt']==before['system_prompt']

def test_preview_routing_cache(client,monkeypatch):
    monkeypatch.setattr(settings,'elevenlabs_api_key','test-key');catalog._preview_cache.clear()
    calls=[]
    async def fake(voice,text,**kw):calls.append(voice);return b'RIFFmatt'
    async def wrong(*a,**kw):pytest.fail('Matt must not use Cartesia')
    monkeypatch.setattr(eleven,'synthesize_wav',fake);monkeypatch.setattr(catalog,'_synthesize',wrong)
    for _ in range(2):
        r=client.post('/api/settings/voices/preview',json={'voice_id':MATT,'text':'Hello from Matt.'})
        assert r.status_code==200 and r.content==b'RIFFmatt'
    assert calls==[MATT];catalog._preview_cache.clear()

@pytest.mark.asyncio
async def test_pcm_to_wav(monkeypatch):
    monkeypatch.setattr(settings,'elevenlabs_api_key','test-key');calls=[]
    class Client:
        def __init__(self,**kw):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        async def post(self,url,**kw):
            calls.append((url,kw))
            return httpx.Response(200,content=b'\x00\x00'*2400,request=httpx.Request('POST',url))
    monkeypatch.setattr(eleven.httpx,'AsyncClient',Client)
    audio=await eleven.synthesize_wav(MATT,'Hello.')
    with wave.open(io.BytesIO(audio),'rb') as wav:
        assert wav.getframerate()==24000 and wav.getnchannels()==1 and wav.getnframes()==2400
    assert calls[0][0].endswith('/iRh44YCGcZyLpQjPFMsh')
    assert calls[0][1]['json']['model_id']=='eleven_flash_v2_5'

def test_provider_errors_hide_secrets(client,monkeypatch):
    monkeypatch.setattr(settings,'elevenlabs_api_key','secret-test-key');catalog._preview_cache.clear()
    async def fail(*a,**kw):raise httpx.HTTPStatusError('secret-test-key',request=httpx.Request('POST','https://api.elevenlabs.io'),response=httpx.Response(401))
    monkeypatch.setattr(eleven,'synthesize_wav',fail)
    r=client.post('/api/settings/voices/preview',json={'voice_id':MATT,'text':'failure'})
    assert r.status_code==502 and 'secret-test-key' not in r.text
