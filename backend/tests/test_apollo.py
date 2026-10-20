"""Native saved-contact API contract and the existing encrypted connection/import flow."""
import asyncio
import datetime as dt
import json
import httpx
import pytest
from cryptography.fernet import Fernet
from app.config import settings
from app.services.crm.http import BaseHttp, CrmError
from app.services.crm.providers import PROVIDERS, Contact

@pytest.fixture
def api(monkeypatch):
    state = {"seen": [], "health": {"is_logged_in": True}, "rows": []}
    def handler(req):
        state["seen"].append(req)
        assert req.url.host == "api.apollo.io"
        assert req.headers["x-api-key"] == "apollo-test-secret"
        if req.url.path == "/api/v1/auth/health": return httpx.Response(200, json=state["health"])
        assert req.method == "POST" and req.url.path == "/api/v1/contacts/search"
        if state.get("error"):return httpx.Response(state["error"], json={"message":"API permission denied"})
        body = json.loads(req.content)
        rows = state["rows"]
        if state.get("repeat"): rows = rows[:100]
        else: rows = rows[(body["page"]-1)*body["per_page"]:body["page"]*body["per_page"]]
        return httpx.Response(200, json=state.get("response", {"contacts": rows}))
    monkeypatch.setattr(BaseHttp,"client_factory",staticmethod(lambda:httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    return state

def run(coro):return asyncio.run(coro)
def provider():
    p=PROVIDERS["apollo"]
    return p,p.native_http("apollo-test-secret",{})
def person(i, **extra):return {"id":str(i),"first_name":"Jo","last_name":"Park","email":"jo@example.test","phone_numbers":[{"sanitized_number":f"+1415555{i:04d}"}],"organization":{"name":"Example"},**extra}

def test_verify_and_capabilities(api):
    p,h=provider()
    assert run(p.verify(h,{}))=="Apollo account"
    assert [r.url.path for r in api['seen']]==['/api/v1/auth/health','/api/v1/contacts/search']
    assert json.loads(api['seen'][-1].content)=={'page':1,'per_page':1}
    assert p.native and p.can_import and not p.can_log_calls and not p.can_new_leads
    assert all(r.method=='GET' or r.url.path.endswith('/contacts/search') for r in api['seen'])

@pytest.mark.parametrize('health',[{}, {'is_logged_in':False},{'is_logged_in':'true'}])
def test_health_must_confirm_login(api,health):
    api['health']=health;p,h=provider()
    with pytest.raises(CrmError,match='verify'):run(p.verify(h,{}))
    assert len(api['seen'])==1

@pytest.mark.parametrize('status',[401,403])
def test_missing_search_permission_prevents_connection(api,status):
    api['error']=status;p,h=provider()
    with pytest.raises(CrmError):run(p.verify(h,{}))

def test_pagination_fixed_size_limit_and_keywords(api):
    api['rows']=[person(i) for i in range(1,202)];p,h=provider()
    contacts=run(p.list_contacts(h,{'search':'  Acme  '},limit=150))
    assert len(contacts)==150 and contacts[-1].external_id=='150'
    assert [json.loads(r.content) for r in api['seen']]==[{'page':1,'per_page':100,'sort_by_field':'contact_created_at','sort_ascending':False,'q_keywords':'Acme'},{'page':2,'per_page':100,'sort_by_field':'contact_created_at','sort_ascending':False,'q_keywords':'Acme'}]
    assert contacts[0].phone=='+14155550001' and contacts[0].company=='Example'
    assert contacts[0].name=='Jo Park' and contacts[0].contacted is None

def test_empty_and_missing_phone_are_not_fabricated(api):
    p,h=provider();assert run(p.list_contacts(h,{}))==[]
    api['rows']=[{'id':'1','name':'No phone'},person(2,phone_numbers=[{'raw_number':'(415) 555-0100'}])]
    got=run(p.list_contacts(h,{}));assert len(got)==1 and got[0].phone=='+14155550100'

def test_opt_out_data_preserved(api):
    api['rows']=[person(1,labels=[{'name':'Do not call'}]),person(2,do_not_call=True),person(3,phone_numbers=[{'raw_number':'+14155550123','dnc_status':'dnc'}])]
    p,h=provider();assert all(c.dnc for c in run(p.list_contacts(h,{})))

@pytest.mark.parametrize('response',[{}, {'contacts':{}},{'contacts':[{}]},{'contacts':['bad']}])
def test_bad_response_fails_instead_of_success(api,response):
    api['response']=response;p,h=provider()
    with pytest.raises(CrmError,match='valid saved-contact'):run(p.list_contacts(h,{}))

def test_repeat_page_stops_without_partial_import(api):
    api['rows']=[person(i) for i in range(100)];api['repeat']=True;p,h=provider()
    with pytest.raises(CrmError,match='repeated'):run(p.list_contacts(h,{},limit=200))

def test_unsupported_filters_and_actions_never_write(api):
    p,h=provider()
    for args in [{'since':dt.datetime.now(dt.timezone.utc)},{'filters':{'skip_contacted':True}},{'filters':{'made_up':['a']}}]:
        with pytest.raises(CrmError):run(p.list_contacts(h,{},**args))
    with pytest.raises(CrmError):run(p.find_or_create(h,{},Contact(),True))
    with pytest.raises(CrmError):run(p.log_call(h,{},'id',None))
    assert not api['seen']

def test_connect_import_dedupe_disconnect(client,api,monkeypatch):
    monkeypatch.setattr(settings,'secrets_encryption_key',Fernet.generate_key().decode())
    api['rows']=[person(8001),person(8002,do_not_call=True)]
    r=client.post('/api/integrations/crm/apollo/connect',json={'fields':{'api_key':'apollo-test-secret'}})
    assert r.status_code==200,r.text
    assert r.json()['settings']['log_calls'] is False and 'apollo-test-secret' not in r.text
    catalog=client.get('/api/integrations/crm').json()
    assert next(p for p in catalog['providers'] if p['key']=='apollo')['native'] is True
    assert 'apollo-test-secret' not in json.dumps(catalog)
    preview=client.post('/api/integrations/crm/apollo/import/preview',json={})
    assert preview.status_code==200,preview.text
    assert preview.json()['found']==2
    imported=client.post('/api/integrations/crm/apollo/import',json={})
    assert imported.status_code==200,imported.text
    assert imported.json()['created']==2 and imported.json()['do_not_call']==1
    repeated=client.post('/api/integrations/crm/apollo/import',json={})
    assert repeated.status_code==200 and repeated.json()['created']==0
    assert client.delete('/api/integrations/crm/apollo').status_code==200
