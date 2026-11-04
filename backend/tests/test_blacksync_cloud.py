import asyncio
import datetime as dt
import json
from types import SimpleNamespace

import httpx
import pytest

from app.services.crm.providers import PROVIDERS, Contact, CallInfo
from app.services.crm.http import BaseHttp, CrmError
from app.services.crm.blacksync_delivery import completed_call_data

P = PROVIDERS['blacksync_cloud']
CONFIG = {'instance_url': 'https://crm.blacksync.cloud'}
PERSON = {'id': '1066b48e-11fd-4af8-8f6f-f6afea47cc21', 'name': {'firstName': 'Alex', 'lastName': 'Lee'},
          'phones': {'primaryPhoneCallingCode': '+1', 'primaryPhoneNumber': '4155550123'}}


@pytest.fixture
def api(monkeypatch):
    state = {'handler': None, 'seen': []}
    def transport(req):
        state['seen'].append(req)
        return state['handler'](req)
    monkeypatch.setattr(BaseHttp, 'client_factory', staticmethod(lambda: httpx.AsyncClient(transport=httpx.MockTransport(transport))))
    return state


def test_matches_country_code_and_rejects_ambiguous_contacts(api):
    http = P.native_http('test-key', CONFIG)
    api['handler'] = lambda req: httpx.Response(200, json={'data': {'people': [PERSON]}})
    assert asyncio.run(P.find_or_create(http, CONFIG, Contact(phone='+14155550123'), False)) == PERSON['id']
    assert api['seen'][0].headers['Authorization'] == 'Bearer test-key'
    assert 'phones.primaryPhoneNumber[eq]' in api['seen'][0].url.params['filter']
    api['handler'] = lambda req: httpx.Response(200, json={'data': {'people': [PERSON, {**PERSON, 'id': 'another'}]}})
    with pytest.raises(CrmError, match='More than one'):
        asyncio.run(P.find_or_create(http, CONFIG, Contact(phone='+14155550123'), True))


def test_same_national_number_in_another_country_does_not_match(api):
    http = P.native_http('test-key', CONFIG)
    api['handler'] = lambda req: httpx.Response(200, json={'data': {'people': [{**PERSON, 'phones': {**PERSON['phones'], 'primaryPhoneCallingCode': '+44'}}]}})
    assert asyncio.run(P.find_or_create(http, CONFIG, Contact(phone='+14155550123'), False)) is None
    assert len(api['seen']) == 1


def test_creating_contacts_is_opt_in_and_uses_documented_response(api):
    http = P.native_http('test-key', CONFIG)
    def handle(req):
        if req.method == 'GET': return httpx.Response(200, json={'data': {'people': []}})
        assert req.url.path == '/rest/people'
        body = json.loads(req.content)
        assert body['phones']['primaryPhoneNumber'] == '4155550123'
        assert body['phones']['primaryPhoneCallingCode'] == '+1'
        assert body['name'] == {'firstName': 'Alex', 'lastName': 'Lee'}
        return httpx.Response(201, json={'data': {'createPerson': {'id': PERSON['id']}}})
    api['handler'] = handle
    assert asyncio.run(P.find_or_create(http, CONFIG, Contact(name='Alex Lee', phone='+14155550123'), True)) == PERSON['id']


def test_logs_a_stable_external_id_and_preserves_sales_details_and_transcript(api):
    call = CallInfo(call_id='saved-call-123', outcome='meeting_booked', summary='Demo next week',
                    duration_seconds=120, phone='+14155550123', direction='inbound', transcript='Customer: Yes please')
    def handle(req):
        assert req.url.path == '/rest/pulse/calls'
        body = json.loads(req.content)
        assert body['source'] == 'blacksync-si' and body['externalId'] == 'saved-call-123'
        assert body['personId'] == PERSON['id'] and body['direction'] == 'inbound'
        assert body['outcome'] == 'answered' and 'Meeting booked' in body['summary']
        assert body['transcript'] == 'Customer: Yes please'
        return httpx.Response(200, json={'noteId': 'crm-note', 'created': False})
    api['handler'] = handle
    asyncio.run(P.log_call(P.native_http('test-key', CONFIG), CONFIG, PERSON['id'], call))


@pytest.mark.parametrize('url', ['http://crm.blacksync.cloud', 'https://localhost', 'https://127.0.0.1', 'https://10.0.0.1', 'https://crm.blacksync.cloud/rest', 'https://user:pass@crm.blacksync.cloud', 'https://crm.blacksync.cloud?key=secret'])
def test_rejects_unsafe_workspace_urls(url):
    with pytest.raises(CrmError): P.native_http('test-key', {'instance_url': url})


def test_api_error_or_missing_receipt_is_not_success(api):
    http = P.native_http('test-key', CONFIG)
    call = CallInfo(call_id='call-123', phone='+14155550123')
    api['handler'] = lambda req: httpx.Response(503, json={'message': 'unavailable'})
    with pytest.raises(CrmError) as error: asyncio.run(P.log_call(http, CONFIG, PERSON['id'], call))
    assert error.value.status == 503
    api['handler'] = lambda req: httpx.Response(200, json={'unexpected': True})
    with pytest.raises(CrmError, match='did not acknowledge'): asyncio.run(P.log_call(http, CONFIG, PERSON['id'], call))


def test_inbound_call_uses_the_caller_and_excludes_tool_arguments():
    call = SimpleNamespace(id='call-id', outcome='interested', summary='Interested', duration_seconds=60,
                           call_type='inbound', to_phone='+18005550123', from_phone='+14155550123', started_at=dt.datetime.now(dt.timezone.utc),
                           agreed_meeting_time=None, meeting_link=None, prospect_email=None, extracted_data={},
                           transcript=[{'role': 'assistant', 'text': 'Hello'}, {'role': 'tool', 'text': 'private arguments'}, {'role': 'user', 'text': 'Hi'}])
    data = completed_call_data(call)
    assert data['to_phone'] == '+14155550123' and data['direction'] == 'inbound'
    assert data['transcript'] == 'Agent: Hello\nCustomer: Hi'
