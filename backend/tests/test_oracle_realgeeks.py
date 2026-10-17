"""Native connector contracts from Oracle Fusion and Real Geeks API documentation."""
import asyncio
import json
import uuid
import httpx
import pytest
from cryptography.fernet import Fernet
from app.config import settings
from app.services.crm.http import BaseHttp, CrmError
from app.services.crm.providers import PROVIDERS, Contact, CallInfo

ORACLE = {'username': 'api-user', 'instance_url': 'https://example.fa.us2.oraclecloud.com'}
SITE = '00000000-0000-4000-8000-000000000010'
LEAD = '00000000-0000-4000-8000-000000000011'
RG = {'username': 'registered-app', 'site_uuid': SITE, 'verification_lead_id': LEAD}
ROOT = '/crmRestApi/resources/11.13.18.05/contacts'
PERSON = {'PartyNumber': 'C_1', 'PartyId': 123, 'FirstName': 'Ann', 'LastName': 'Lee', 'RawPhoneNumber': '+14155550123', 'EmailAddress': 'ann@example.test', 'DoNotCallFlag': True}
CALL = CallInfo(call_id='call-1', summary='Interested in selling.', outcome='interested', duration_seconds=30)

@pytest.fixture
def api(monkeypatch):
    state = {'handler': None, 'seen': []}
    def transport(req):
        state['seen'].append(req)
        return state['handler'](req)
    monkeypatch.setattr(BaseHttp, 'client_factory', staticmethod(lambda: httpx.AsyncClient(transport=httpx.MockTransport(transport))))
    return state

def run(coro): return asyncio.run(coro)

@pytest.mark.parametrize('url', ['http://example.oraclecloud.com', 'https://localhost', 'https://127.0.0.1', 'https://x.oraclecloud.com.evil.test', 'https://user:password@x.oraclecloud.com', 'https://x.oraclecloud.com:8080', 'https://x.oraclecloud.com:bad', 'https://x.oraclecloud.com/path', 'https://x.oraclecloud.com?redirect=elsewhere'])
def test_oracle_rejects_unsafe_instances(url):
    with pytest.raises(CrmError): PROVIDERS['oracle_sales'].native_http('password', {**ORACLE, 'instance_url': url})

def test_oracle_verify_pagination_dnc_and_basic_auth(api):
    p=PROVIDERS['oracle_sales'];http=p.native_http(' password ',ORACLE)
    def handler(req):
        assert req.url.host=='example.fa.us2.oraclecloud.com'
        assert req.url.path==ROOT and req.method=='GET'
        offset=int(req.url.params.get('offset','0'))
        rows=[PERSON] if offset==0 else [{**PERSON,'PartyNumber':'C_2','RawPhoneNumber':'+14155550124','DoNotCallFlag':False}]
        return httpx.Response(200,json={'items':rows,'hasMore':offset==0})
    api['handler']=handler
    assert 'api-user' in run(p.verify(http,ORACLE))
    people=run(p.list_contacts(http,ORACLE,limit=2))
    assert len(people)==2 and people[0].dnc and not people[1].dnc
    assert people[0].name=='Ann Lee' and people[0].external_id=='C_1'
    assert api['seen'][0].headers['authorization']==httpx.BasicAuth('api-user',' password ')._auth_header

def test_oracle_match_note_and_dnc_write(api):
    p=PROVIDERS['oracle_sales'];http=p.native_http('pass',ORACLE)
    def handler(req):
        if req.method=='GET': return httpx.Response(200,json={'items':[PERSON]} if req.url.path==ROOT else PERSON)
        if req.method=='POST':
            body=json.loads(req.content)
            assert req.url.path==ROOT+'/C_1/child/Note'
            assert body['SourceObjectCode']=='SALES_PARTY_CONTACT' and body['SourceObjectId']=='123'
            assert body['NoteTypeCode']=='GENERAL' and CALL.summary in body['NoteTxt']
            return httpx.Response(201,json={'NoteId':55})
        assert req.method=='PATCH' and json.loads(req.content)=={'DoNotCallFlag':True}
        return httpx.Response(200,json={})
    api['handler']=handler
    assert run(p.find_or_create(http,ORACLE,Contact('Ann','+14155550123','ann@example.test'),False))=='C_1'
    run(p.log_call(http,ORACLE,'C_1',CALL));run(p.mark_dnc(http,ORACLE,'C_1'))

def test_oracle_no_false_success_or_phone_only_duplicate(api):
    p=PROVIDERS['oracle_sales'];http=p.native_http('pass',ORACLE)
    api['handler']=lambda r:httpx.Response(200,json={'items':[]})
    with pytest.raises(CrmError,match='provide an email'): run(p.find_or_create(http,ORACLE,Contact('Ann','+14155550123'),True))
    assert all(r.method=='GET' for r in api['seen'])
    api['handler']=lambda r:httpx.Response(200,json=PERSON if r.method=='GET' else {})
    with pytest.raises(CrmError,match='confirm the note'):run(p.log_call(http,ORACLE,'C_1',CALL))

def test_realgeeks_verify_and_known_lead_note(api):
    p=PROVIDERS['realgeeks'];http=p.native_http('app-password',RG)
    def handler(req):
        assert req.url.host=='receivers.leadrouter.realgeeks.com'
        if req.method=='GET':return httpx.Response(200,json={'id':LEAD,'phone':'+14155550123'})
        assert req.url.path==f'/rest/sites/{SITE}/leads/{LEAD}/activities'
        assert json.loads(req.content)==[{'type':'note','description':CALL.note()}]
        return httpx.Response(200,json={})
    api['handler']=handler
    assert SITE in run(p.verify(http,RG))
    assert run(p.find_or_create(http,RG,Contact('Ann','+14155550123'),False))==LEAD
    run(p.log_call(http,RG,LEAD,CALL))
    assert not p.can_import and not p.can_new_leads

def test_realgeeks_creation_readback_and_no_write_on_auth_failure(api):
    p=PROVIDERS['realgeeks'];http=p.native_http('app-password',RG);created=[]
    target=str(uuid.uuid5(uuid.UUID(SITE),'+14155550124'))
    def handler(req):
        if req.method=='POST':created.append(json.loads(req.content));return httpx.Response(201,json={})
        if req.url.path.endswith(LEAD):return httpx.Response(200,json={'id':LEAD,'phone':'+14155550123'})
        return httpx.Response(200,json={'id':target}) if created else httpx.Response(404,json={})
    api['handler']=handler
    assert run(p.find_or_create(http,RG,Contact('Bo','+14155550124'),True))==target
    assert created[0]['id']==target and created[0]['source']=='BlackSync'
    api['handler']=lambda r:httpx.Response(401,json={'message':'Invalid credentials'})
    api['seen'].clear()
    with pytest.raises(CrmError): run(p.find_or_create(http,RG,Contact('Bo','+14155550124'),True))
    assert all(r.method=='GET' for r in api['seen'])

def test_connect_verifies_before_save_and_hides_password(client,api,monkeypatch):
    monkeypatch.setattr(settings,'secrets_encryption_key',Fernet.generate_key().decode())
    api['handler']=lambda r:httpx.Response(200,json={'items':[]})
    response=client.post('/api/integrations/crm/oracle_sales/connect',json={'fields':{**ORACLE,'api_key':' private-password '}})
    assert response.status_code==200,response.text
    assert 'private-password' not in response.text and response.json()['status']=='connected'
    assert response.json()['config']['instance_url']==ORACLE['instance_url']
    api['handler']=lambda r:httpx.Response(401,json={'message':'Invalid credentials'})
    failed=client.post('/api/integrations/crm/oracle_sales/connect',json={'fields':{**ORACLE,'api_key':'wrong'}})
    assert failed.status_code==400
    api['handler']=lambda r:httpx.Response(200,json={'items':[]})
    assert client.post('/api/integrations/crm/oracle_sales/test').status_code==200
    assert api['seen'][-1].headers['authorization']==httpx.BasicAuth('api-user',' private-password ')._auth_header
    unavailable=client.post('/api/integrations/crm/boomtown/connect',json={'fields':{'api_key':'any'}})
    assert unavailable.status_code==503
    data=client.get('/api/integrations/crm').json()
    assert not next(p for p in data['providers'] if p['key']=='boomtown')['native']
    assert not any(c['provider']=='boomtown' for c in data['connections'])

    assert client.delete('/api/integrations/crm/oracle_sales').status_code == 200


def test_oracle_create_requires_provider_receipt(api):
    p=PROVIDERS['oracle_sales'];http=p.native_http('pass',ORACLE)
    def handler(req):
        if req.method=='GET':return httpx.Response(200,json={'items':[]})
        body=json.loads(req.content)
        assert req.url.path==ROOT
        assert body['ContactPoint'][0]['ContactPointType']=='PHONE'
        assert body['ContactPoint'][1]['EmailAddress']=='new@example.test'
        return httpx.Response(201,json={'PartyNumber':'NEW_1'})
    api['handler']=handler
    assert run(p.find_or_create(http,ORACLE,Contact('New Owner','+14155550124','new@example.test'),True))=='NEW_1'


def test_realgeeks_connect_uses_verification_lead_without_writes(client,api,monkeypatch):
    monkeypatch.setattr(settings,'secrets_encryption_key',Fernet.generate_key().decode())
    api['handler']=lambda r:httpx.Response(401,json={'message':'Invalid credentials'})
    failed=client.post('/api/integrations/crm/realgeeks/connect',json={'fields':{**RG,'api_key':'bad'}})
    assert failed.status_code==400
    assert not any(c['provider']=='realgeeks' for c in client.get('/api/integrations/crm').json()['connections'])
    api['handler']=lambda r:httpx.Response(200,json={'id':LEAD,'phone':'+14155550123'})
    response=client.post('/api/integrations/crm/realgeeks/connect',json={'fields':{**RG,'api_key':' private-app-password '}})
    assert response.status_code==200,response.text
    assert 'private-app-password' not in response.text
    assert response.json()['config']['site_uuid']==SITE
    assert all(req.method=='GET' for req in api['seen'])
    assert client.delete('/api/integrations/crm/realgeeks').status_code==200


def test_oracle_reuses_email_match_without_phone_in_crm(api):
    p=PROVIDERS['oracle_sales'];http=p.native_http('pass',ORACLE)
    api['handler']=lambda r:httpx.Response(200,json={'items':[{'PartyNumber':'EMAIL_ONLY','EmailAddress':'ann@example.test'}]})
    assert run(p.find_or_create(http,ORACLE,Contact('Ann','+14155550123','ann@example.test'),True))=='EMAIL_ONLY'
    assert all(r.method=='GET' for r in api['seen'])


def test_oracle_native_import_preserves_opt_out(client,api,monkeypatch):
    monkeypatch.setattr(settings,'secrets_encryption_key',Fernet.generate_key().decode())
    person={**PERSON,'PartyNumber':'C_NATIVE_IMPORT','RawPhoneNumber':'+14155550189'}
    api['handler']=lambda r:httpx.Response(200,json={'items':[person],'hasMore':False})
    connected=client.post('/api/integrations/crm/oracle_sales/connect',json={'fields':{**ORACLE,'api_key':'fake-password'}})
    assert connected.status_code==200
    imported=client.post('/api/integrations/crm/oracle_sales/import',json={'limit':10})
    assert imported.status_code==200,imported.text
    rows=client.get('/api/contacts',params={'q':'Ann Lee'}).json()['items']
    contact=next(c for c in rows if c['phone']=='+14155550189')
    assert contact['source']=='oracle_sales' and contact['do_not_call'] is True
    assert contact['campaign_id'] is None
    assert client.delete('/api/integrations/crm/oracle_sales').status_code==200
