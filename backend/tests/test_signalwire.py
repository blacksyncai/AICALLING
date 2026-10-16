import uuid
from types import SimpleNamespace
import httpx
import pytest
from app.config import settings
from app.services import signalwire
from tests.test_accounts import _new_account

@pytest.fixture
def sw(monkeypatch):
    for key, value in {'signalwire_space':'example.signalwire.com','signalwire_project_id':'project-test','signalwire_api_token':'test-secret','signalwire_sip_outbound_trunk_id':'ST_signalwire','twilio_account_sid':'','twilio_auth_token':'','bandwidth_account_id':''}.items():
        monkeypatch.setattr(settings, key, value)
    state = SimpleNamespace(number='+1415'+str(uuid.uuid4().int % 10000000).zfill(7), allowed=[], response=None)
    def handler(request):
        assert request.url.host == 'example.signalwire.com'
        return httpx.Response(200, json=state.response or {'incoming_phone_numbers':[{'sid':'PN_sw','phone_number':state.number,'capabilities':{'voice':True}}]})
    real = httpx.AsyncClient
    monkeypatch.setattr(signalwire.httpx,'AsyncClient',lambda **kw: real(transport=httpx.MockTransport(handler),**kw))
    async def allow(n): state.allowed.append(n)
    monkeypatch.setattr(signalwire,'allow_number',allow)
    return state

def test_assign_without_twilio_and_reject_duplicate(client,sw):
    org,_ = _new_account(client,name='SignalWire test')
    status=client.get('/api/admin/telephony')
    assert any(n['number']==sw.number and n['carrier']=='signalwire' for n in status.json()['owned'])
    result=client.post(f"/api/admin/orgs/{org['id']}/phone-numbers",json={'number':sw.number,'mode':'import'})
    assert result.status_code==201,result.text
    assert result.json()['carrier']=='signalwire'
    assert sw.allowed==[sw.number]
    other,_=_new_account(client,name='SignalWire other')
    assert client.post(f"/api/admin/orgs/{other['id']}/phone-numbers",json={'number':sw.number,'mode':'import'}).status_code==502
    removed=client.delete(f"/api/admin/phone-numbers/{result.json()['id']}")
    assert removed.status_code==200,removed.text

@pytest.mark.asyncio
async def test_inventory_rejects_foreign_pagination(sw):
    sw.response={'incoming_phone_numbers':[],'next_page_uri':'https://attacker.test/steal'}
    with pytest.raises(signalwire.SignalWireError,match='pagination'): await signalwire.list_numbers()

@pytest.mark.asyncio
async def test_inventory_validates_host(sw,monkeypatch):
    monkeypatch.setattr(settings,'signalwire_space','attacker.test')
    with pytest.raises(signalwire.SignalWireError,match='hostname'): await signalwire.list_numbers()

def test_failed_trunk_does_not_assign(client,sw,monkeypatch):
    org,_=_new_account(client,name='SignalWire rejected')
    async def fail(n): raise signalwire.SignalWireError('Trunk unavailable')
    monkeypatch.setattr(signalwire,'allow_number',fail)
    result=client.post(f"/api/admin/orgs/{org['id']}/phone-numbers",json={'number':sw.number,'mode':'import'})
    assert result.status_code==502
    assert client.get(f"/api/admin/orgs/{org['id']}/phone-numbers").json()['numbers']==[]

def test_signalwire_dials_own_trunk_with_precreated_room(client,make_client,sw,monkeypatch):
    import time
    from app.services import outbound_call,recordings
    from tests.test_accounts import _login
    from tests.test_phone_numbers import _FakeLK
    org,email=_new_account(client,name='SignalWire dial',credits=50)
    owner=_login(make_client,email)
    assigned=client.post(f"/api/admin/orgs/{org['id']}/phone-numbers",json={'number':sw.number,'mode':'import'})
    assert assigned.status_code==201,assigned.text
    monkeypatch.setattr(settings,'livekit_sip_outbound_trunk_id','')
    monkeypatch.setattr(settings,'recording_provider','twilio')
    log=[]
    monkeypatch.setattr(outbound_call,'_lk',lambda:_FakeLK(log))
    agent=owner.post('/api/agents/',json={'template':'sales_sdr'}).json()
    owner.patch(f"/api/agents/{agent['id']}",json={'record_calls':False})
    result=owner.post(f"/api/agents/{agent['id']}/phone-call",json={'to_phone':'+15551234567'})
    assert result.status_code==200,result.text
    for _ in range(50):
        if any(kind=='sip' for kind,_ in log): break
        time.sleep(.02)
    sip=next(req for kind,req in log if kind=='sip')
    assert sip.sip_trunk_id=='ST_signalwire'
    assert sip.sip_number==sw.number
    assert [kind for kind,_ in log].index('dispatch') < [kind for kind,_ in log].index('sip')
