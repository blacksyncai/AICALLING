import uuid
from types import SimpleNamespace
import httpx
import pytest
REAL_ASYNC_CLIENT = httpx.AsyncClient

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
        return httpx.Response(200, json=state.response or {'data':[{'id':'PN_sw','number':state.number,'capabilities':{'voice':True}}], 'links':{}})
    real = REAL_ASYNC_CLIENT
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
    sw.response={'data':[],'links':{'next':'https://attacker.test/steal'}}
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

def test_inventory_error_shows_configured_trunk_number_and_warning(client,sw,monkeypatch):
    async def rejected():
        raise signalwire.SignalWireError('SignalWire rejected number access (HTTP 401).')
    async def configured():
        return [{'sid':'sw:test','number':sw.number,'friendly':'Configured SignalWire SIP caller ID','carrier':'signalwire','trunk_sid':'','inventory_source':'livekit'}]
    monkeypatch.setattr(signalwire,'list_numbers',rejected)
    monkeypatch.setattr(signalwire,'configured_numbers',configured)
    response=client.get('/api/admin/telephony')
    assert response.status_code==200
    data=response.json()
    assert any(n['number']==sw.number and n['inventory_source']=='livekit' for n in data['owned'])
    assert data['owned_error']==''
    assert 'HTTP 401' in data['owned_warnings'][0]
    org,_=_new_account(client,name='SignalWire fallback assignment')
    assigned=client.post(f"/api/admin/orgs/{org['id']}/phone-numbers",json={'number':sw.number,'mode':'import'})
    assert assigned.status_code==201,assigned.text
    assert assigned.json()['carrier']=='signalwire'

@pytest.mark.asyncio
async def test_fallback_reads_only_selected_trunk(sw,monkeypatch):
    from app.services import outbound_call
    async def listing(req):
        assert list(req.trunk_ids)==['ST_signalwire']
        return SimpleNamespace(items=[SimpleNamespace(sip_trunk_id='ST_wrong',numbers=['+15551111111']),SimpleNamespace(sip_trunk_id='ST_signalwire',numbers=[sw.number])])
    async def close(): pass
    monkeypatch.setattr(outbound_call,'_lk',lambda:SimpleNamespace(sip=SimpleNamespace(list_outbound_trunk=listing),aclose=close))
    assert [n['number'] for n in await signalwire.configured_numbers()]==[sw.number]

def test_signalwire_records_in_worker_and_never_requests_egress(client,make_client,sw,monkeypatch):
    import json,time
    from app.services import outbound_call
    from tests.test_accounts import _login
    from tests.test_phone_numbers import _FakeLK
    org,email=_new_account(client,name='SignalWire recorder',credits=50)
    owner=_login(make_client,email)
    client.post(f"/api/admin/orgs/{org['id']}/phone-numbers",json={'number':sw.number,'mode':'import'})
    for key,value in {'recordings_s3_bucket':'test','recordings_s3_access_key':'test','recordings_s3_secret_key':'test','recording_provider':'twilio'}.items():
        monkeypatch.setattr(settings,key,value)
    log=[]; egress=[]
    monkeypatch.setattr(outbound_call,'_lk',lambda:_FakeLK(log))
    async def forbidden(*args): egress.append(args)
    monkeypatch.setattr(outbound_call,'_start_recording',forbidden)
    agent=owner.post('/api/agents/',json={'template':'sales_sdr'}).json()
    owner.patch(f"/api/agents/{agent['id']}",json={'record_calls':True})
    result=owner.post(f"/api/agents/{agent['id']}/phone-call",json={'to_phone':'+15551234567'})
    assert result.status_code==200,result.text
    call_id=result.json()['call_id']
    for _ in range(50):
        if any(kind=='sip' for kind,_ in log):break
        time.sleep(.02)
    meta=json.loads(next(req for kind,req in log if kind=='room').metadata)
    assert meta['worker_recording'] is True
    assert meta['record_key']==f"recordings/{org['id']}/{call_id}.ogg"
    assert not egress
    assert owner.get(f'/api/calls/{call_id}').json()['has_recording']
    monkeypatch.setattr(settings,'internal_token','recording-test-key')
    endpoint=f'/internal/calls/{call_id}/recording-state'
    body={'room_name':'wrong-room','state':'ready'}
    assert client.post(endpoint,json=body).status_code==403
    headers={'x-internal-token':'recording-test-key'}
    assert client.post(endpoint,json=body,headers=headers).status_code==404
    body['room_name']=next(req for kind,req in log if kind=='room').name
    body['state']='failed'
    assert client.post(endpoint,json=body,headers=headers).status_code==200
    assert not owner.get(f'/api/calls/{call_id}').json()['has_recording']
    # A delayed duplicate cannot revive a failed recording with no file.
    body['state']='ready'
    assert client.post(endpoint,json=body,headers=headers).status_code==200
    assert not owner.get(f'/api/calls/{call_id}').json()['has_recording']

def test_unanswered_signalwire_call_clears_pending_recording(client,make_client,sw,monkeypatch):
    import time
    from app.services import outbound_call
    from tests.test_accounts import _login
    from tests.test_phone_numbers import _FakeLK
    org,email=_new_account(client,name='SignalWire unanswered recorder',credits=50)
    owner=_login(make_client,email)
    client.post(f"/api/admin/orgs/{org['id']}/phone-numbers",json={'number':sw.number,'mode':'import'})
    for key in ['recordings_s3_bucket','recordings_s3_access_key','recordings_s3_secret_key']:
        monkeypatch.setattr(settings,key,'test')
    async def no_answer(*args,**kwargs): raise RuntimeError('timed out')
    def lk():
        obj=_FakeLK([])
        obj.sip.create_sip_participant=no_answer
        return obj
    monkeypatch.setattr(outbound_call,'_lk',lk)
    agent=owner.post('/api/agents/',json={'template':'sales_sdr'}).json()
    owner.patch(f"/api/agents/{agent['id']}",json={'record_calls':True})
    result=owner.post(f"/api/agents/{agent['id']}/phone-call",json={'to_phone':'+15551234567'})
    assert result.status_code==200,result.text
    for _ in range(50):
        call=owner.get(f"/api/calls/{result.json()['call_id']}").json()
        if call['status']=='no_answer': break
        time.sleep(.02)
    assert call['status']=='no_answer'
    assert not call['has_recording']

@pytest.mark.asyncio
async def test_rest_inventory_pagination_returns_every_number(sw,monkeypatch):
    calls=[]
    real=REAL_ASYNC_CLIENT
    def handler(request):
        calls.append(str(request.url))
        assert request.url.path=='/api/relay/rest/phone_numbers'
        if not request.url.query:
            return httpx.Response(200,json={'data':[{'id':'one','number':'+14155550101','name':'First','capabilities':{'voice':True}}],
                                          'links':{'next':'https://example.signalwire.com/api/relay/rest/phone_numbers?page_number=1'}})
        return httpx.Response(200,json={'data':[{'id':'two','number':'+14155550102','name':'Second','capabilities':{'voice':True}},
                                                     {'id':'fax','number':'+14155550103','capabilities':{'voice':False}}],'links':{}})
    monkeypatch.setattr(signalwire.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    numbers=await signalwire.list_numbers()
    assert [n['number'] for n in numbers]==['+14155550101','+14155550102']
    assert len(calls)==2


def test_dynamic_script_preserves_destination_and_refuses_custom_flow():
    import copy
    original={'version':'1.0.0','sections':{'main':[{'connect':{'answer_on_bridge':True,'from':'+14154800324','to':signalwire.DYNAMIC_DESTINATION}}]}}
    patched=signalwire.dynamic_script(original)
    assert patched['sections']['main'][0]['connect']['from']==signalwire.DYNAMIC_CALLER_ID
    assert original['sections']['main'][0]['connect']['from']=='+14154800324'
    assert signalwire.dynamic_script(patched)==patched
    custom=copy.deepcopy(original)
    custom['sections']['main'].append({'record_call':{'format':'mp3'}})
    with pytest.raises(signalwire.SignalWireError,match='Custom'):
        signalwire.dynamic_script(custom)


@pytest.mark.asyncio
async def test_shared_routing_update_read_back_and_idempotent(sw,monkeypatch):
    import copy
    monkeypatch.setattr(settings,'signalwire_outbound_script_id','script-test')
    contents={'version':'1.0.0','sections':{'main':[{'connect':{'answer_on_bridge':True,'from':'+14154800324','to':signalwire.DYNAMIC_DESTINATION}}]}}
    calls=[]; real=REAL_ASYNC_CLIENT
    def handler(request):
        import json
        nonlocal contents
        calls.append(request.method)
        if request.method=='PUT':
            contents=json.loads(request.content)['contents']
            return httpx.Response(200,json={})
        return httpx.Response(200,json={'swml_script':{'contents':copy.deepcopy(contents)}})
    monkeypatch.setattr(signalwire.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    await signalwire.ensure_dynamic_routing()
    await signalwire.ensure_dynamic_routing()
    assert calls==['GET','PUT','GET','GET']
    assert contents['sections']['main'][0]['connect']['from']==signalwire.DYNAMIC_CALLER_ID
