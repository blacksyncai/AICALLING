"""Brivity contracts from its published Core API; no guessed note/search routes."""
import asyncio
import httpx
import pytest
from cryptography.fernet import Fernet
from app.config import settings
from app.services.crm.providers import PROVIDERS
from app.services.crm.http import BaseHttp, CrmError
from app.services.crm.sync import push_call_to

P = PROVIDERS['brivity']
ROSTER = [{'user_id': 42, 'is_owner': True, 'team': 'Test team'}]
PERSON = [{'account_id': 7, 'first_name': 'Ann', 'last_name': 'Lee', 'phone_number': '415.555.0123', 'email_address': 'ann@example.test'}]

@pytest.fixture
def api(monkeypatch):
    state = {'handler': None, 'seen': []}
    def handler(req):
        state['seen'].append(req)
        assert req.url.host == 'api.brivity.com'
        assert req.headers['authorization'] == 'Token token=test-token'
        assert req.method == 'GET'
        return state['handler'](req)
    monkeypatch.setattr(BaseHttp, 'client_factory', staticmethod(lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    return state

def run(c): return asyncio.run(c)

def test_auth_and_person_import(api):
    api['handler'] = lambda r: httpx.Response(200, json=ROSTER if r.url.path.endswith('roster') else PERSON)
    http = P.native_http('test-token', {'person_ids': '12, 12, 13'})
    assert run(P.verify(http, {})) == 'Test team'
    contacts = run(P.list_contacts(http, {'person_ids': '12, 12, 13'}))
    assert [c.external_id for c in contacts] == ['12', '13']
    assert contacts[0].name == 'Ann Lee' and contacts[0].phone == '+14155550123'
    assert contacts[0].email == 'ann@example.test'
    assert [r.url.path for r in api['seen']] == ['/api/v2/roster', '/api/people/12', '/api/people/13']

@pytest.mark.parametrize('body', [{'status': '406', 'error': 'Not Acceptable'}, {'raw': '<html>Login</html>'}, [{}], {'agents': ROSTER}])
def test_http_200_is_not_sufficient_to_verify(api, body):
    api['handler'] = lambda r: httpx.Response(200, json=body)
    with pytest.raises(CrmError): run(P.verify(P.native_http('test-token', {}), {}))

@pytest.mark.parametrize('ids', ['../admin', '0', '-1', '1&token=bad', ','.join(str(i) for i in range(1, 102))])
def test_ids_fail_before_network(ids):
    with pytest.raises(CrmError): P.native_http('test-token', {'person_ids': ids})

def test_import_needs_explicit_ids_and_rejects_partial_results(api):
    with pytest.raises(CrmError): run(P.list_contacts(P.native_http('test-token', {}), {}))
    api['handler'] = lambda r: httpx.Response(200, json=PERSON if r.url.path.endswith('/1') else [])
    with pytest.raises(CrmError): run(P.list_contacts(P.native_http('test-token', {}), {'person_ids': '1,2'}))

@pytest.mark.parametrize('token', ['Token token=abc', 'abc\r\nother: bad', '"abc"', ''])
def test_rejects_header_injection(token):
    with pytest.raises(CrmError): P.native_http(token, {})

def test_connect_encrypts_token_and_disables_unsupported_writes(client, monkeypatch, api):
    monkeypatch.setattr(settings, 'secrets_encryption_key', Fernet.generate_key().decode())
    api['handler'] = lambda r: httpx.Response(200, json=ROSTER)
    r = client.post('/api/integrations/crm/brivity/connect', json={'fields': {'api_key': 'test-token', 'person_ids': '12'}})
    assert r.status_code == 200, r.text
    assert 'test-token' not in r.text
    assert r.json()['config']['person_ids'] == '12'
    assert r.json()['settings']['log_calls'] is False
    assert r.json()['settings']['create_contacts'] is False
    for field in ['log_calls', 'create_contacts']:
        assert client.patch('/api/integrations/crm/brivity', json={field: True}).status_code == 400
    api['handler'] = lambda r: httpx.Response(401, json={'message': 'Bad Credentials'})
    assert client.post('/api/integrations/crm/brivity/connect', json={'fields': {'api_key': 'test-token'}}).status_code == 400
    assert next(c for c in client.get('/api/integrations/crm').json()['connections'] if c['provider'] == 'brivity')['config']['person_ids'] == '12'
    assert client.delete('/api/integrations/crm/brivity').status_code in (200, 204)

def test_sync_never_attempts_unsupported_writes():
    class Conn: provider = 'brivity'
    run(push_call_to(None, Conn(), {}))

def test_native_import_creates_contacts_with_real_brivity_refs(client, monkeypatch, api):
    monkeypatch.setattr(settings, 'secrets_encryption_key', Fernet.generate_key().decode())
    api['handler'] = lambda r: httpx.Response(200, json=ROSTER if r.url.path.endswith('roster') else PERSON)
    connected = client.post('/api/integrations/crm/brivity/connect', json={'fields': {'api_key': 'test-token', 'person_ids': '12'}})
    assert connected.status_code == 200
    try:
        preview = client.post('/api/integrations/crm/brivity/import/preview', json={'limit': 10})
        assert preview.status_code == 200, preview.text
        imported = client.post('/api/integrations/crm/brivity/import', json={'limit': 10})
        assert imported.status_code == 200, imported.text
        rows = client.get('/api/contacts', params={'q': 'Ann Lee'}).json()['items']
        contact = next(c for c in rows if c['phone'] == '+14155550123')
        assert contact['source'] == 'brivity' and contact['campaign_id'] is None
        assert client.post('/api/integrations/crm/brivity/import', json={'limit': 10}).status_code == 200
        assert len([c for c in client.get('/api/contacts', params={'q': 'Ann Lee'}).json()['items'] if c['phone'] == '+14155550123']) == 1
        assert all(r.method == 'GET' for r in api['seen'])
    finally:
        client.delete('/api/integrations/crm/brivity')
