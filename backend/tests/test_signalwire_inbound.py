from types import SimpleNamespace
import httpx
import pytest
from app.config import settings
from app.services import inbound, signalwire

NUMBER='+17373654598'

@pytest.mark.asyncio
async def test_signalwire_never_reuses_another_carriers_trunk():
    class Sip:
        async def list_inbound_trunk(self,req):
            return SimpleNamespace(items=[SimpleNamespace(name='Twilio Inbound',sip_trunk_id='ST_twilio')])
    with pytest.raises(inbound.InboundError,match='not been provisioned'):
        await inbound._inbound_trunk(SimpleNamespace(sip=Sip()),signalwire=True)

@pytest.mark.asyncio
async def test_signalwire_trunk_does_not_become_default_for_legacy_numbers():
    class Sip:
        async def list_inbound_trunk(self,req):
            return SimpleNamespace(items=[SimpleNamespace(name=inbound.SIGNALWIRE_INBOUND_NAME,sip_trunk_id='ST_sw'),SimpleNamespace(name='Twilio Inbound',sip_trunk_id='ST_twilio')])
    lk=SimpleNamespace(sip=Sip())
    assert (await inbound._inbound_trunk(lk,signalwire=True)).sip_trunk_id=='ST_sw'
    assert (await inbound._inbound_trunk(lk)).sip_trunk_id=='ST_twilio'

@pytest.mark.asyncio
@pytest.mark.parametrize('mutation',['none','foreign_url','wrong_number','wrong_password','extra_step'])
async def test_provider_handoff_readback(monkeypatch,mutation):
    monkeypatch.setattr(settings,'signalwire_space','example.signalwire.com')
    monkeypatch.setattr(settings,'livekit_sip_host','example.sip.livekit.cloud')
    url='https://example.signalwire.com/relay-bins/123'
    async def req(method,path,**kw):
        assert method=='GET'
        return {'data':[{'number':NUMBER,'call_handler':'relay_script','call_relay_script_url':url if mutation!='foreign_url' else 'https://attacker.test/steal'}]}
    monkeypatch.setattr(signalwire,'_number_request',req)
    script={'sections':{'main':[{'connect':{'to':f'sip:{NUMBER}@example.sip.livekit.cloud;transport=tls','username':'user','password':'pass'}}]}}
    if mutation=='wrong_number':script['sections']['main'][0]['connect']['to']='sip:+15555550123@example.sip.livekit.cloud'
    if mutation=='wrong_password':script['sections']['main'][0]['connect']['password']='wrong'
    if mutation=='extra_step':script['sections']['main'].append({'play':'unexpected'})
    real=httpx.AsyncClient
    def handle(r):
        assert r.url.host=='example.signalwire.com'
        assert not r.headers.get('authorization')
        return httpx.Response(200,json=script)
    monkeypatch.setattr(signalwire.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handle),**kw))
    if mutation=='none':await signalwire.verify_inbound_routing(NUMBER,'user','pass')
    else:
        with pytest.raises(signalwire.SignalWireError):await signalwire.verify_inbound_routing(NUMBER,'user','pass')

@pytest.mark.asyncio
async def test_missing_number_or_digest_fails_before_dispatch(monkeypatch):
    monkeypatch.setattr(type(settings),'livekit_ready',property(lambda self:True))
    closed=[]
    class LK:
        async def aclose(self):closed.append(True)
    monkeypatch.setattr(inbound,'_lk',LK)
    async def trunk(*a,**kw):return SimpleNamespace(numbers=[],auth_username='user',auth_password='pass')
    monkeypatch.setattr(inbound,'_inbound_trunk',trunk)
    with pytest.raises(inbound.InboundError,match='securely provisioned'):await inbound.ensure_routing(NUMBER,signalwire=True)
    assert closed==[True]

@pytest.mark.asyncio
@pytest.mark.parametrize('fail',[False,True])
async def test_activation_requires_verified_routing_before_assigning(monkeypatch,fail):
    row=SimpleNamespace(carrier='signalwire',number=NUMBER,inbound_agent_id=None,inbound_campaign_id=None)
    campaign=SimpleNamespace(agent_id='agent-test',id='campaign-test')
    async def number(*a):return row
    calls=[]
    async def route(number,**kw):
        calls.append((number,kw))
        if fail:raise inbound.InboundError('Unverified handoff')
    monkeypatch.setattr(inbound,'campaign_number',number)
    monkeypatch.setattr(inbound,'ensure_routing',route)
    if fail:
        with pytest.raises(inbound.InboundError):await inbound.activate(None,campaign)
        assert row.inbound_agent_id is None
    else:
        await inbound.activate(None,campaign)
        assert row.inbound_agent_id=='agent-test' and row.inbound_campaign_id=='campaign-test'
    assert calls==[(NUMBER,{'signalwire':True})]
