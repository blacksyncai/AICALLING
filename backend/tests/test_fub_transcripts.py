import asyncio
import uuid

import pytest
from sqlalchemy import select

from tests.test_radar_automations import crm, add_call
from app.database import AsyncSessionLocal
from app.models.call_log import CallLog
from app.models.crm import CrmConnection
from app.services.crm import fub_transcripts, sync
from app.services.crm.http import CrmError


@pytest.fixture
def delivery(client, crm, monkeypatch):
    calls = []
    state = {'error': None}
    assert client.patch('/api/integrations/crm/followupboss', json={
        'log_calls': True, 'note_transcript': True, 'note_link': True,
        'only_connected': False, 'min_seconds': 0, 'only_outcomes': [], 'only_sentiments': [], 'skip_outcomes': [],
    }).status_code == 200

    class HTTP:
        async def request(self, method, path, **kw):
            calls.append((method, path, kw))
            if state['error']:
                raise state['error']
            return {'id': len(calls)}

    monkeypatch.setattr(sync, 'http_for', lambda conn: (None, HTTP()))
    call_id, _ = add_call(crm, transcript=[
        {'role': 'system', 'text': 'PRIVATE SYSTEM INSTRUCTIONS'},
        {'role': 'assistant', 'text': 'Is this James?'},
        {'role': 'tool', 'text': 'PRIVATE TOOL DATA'},
        {'role': 'user', 'text': 'Yes. <script>alert(1)</script>'},
    ])

    async def send(**changes):
        async with AsyncSessionLocal() as db:
            call = await db.get(CallLog, uuid.UUID(call_id))
            conn = (await db.execute(select(CrmConnection).where(CrmConnection.org_id == call.org_id,
                CrmConnection.provider == 'followupboss'))).scalar_one()
            for key, value in changes.items():
                setattr(call, key, value)
            await db.commit()
            return await fub_transcripts.send(db, conn, call, '91')

    return calls, state, lambda **kw: asyncio.run(send(**kw)), call_id


def test_transcript_notes_are_speaker_labelled_escaped_and_not_duplicated(delivery):
    calls, _, send, _ = delivery
    assert send()['status'] == 'sent'
    assert send()['status'] == 'sent'
    assert len(calls) == 1
    method, path, payload = calls[0]
    assert (method, path) == ('POST', '/v1/notes')
    note = payload['json']
    assert note['personId'] == 91
    assert 'Agent: Is this James?' in note['body']
    assert 'Contact: Yes.' in note['body'] and '&lt;script&gt;' in note['body']
    assert 'PRIVATE' not in note['body']


def test_long_transcripts_are_complete_numbered_parts(delivery):
    calls, _, send, _ = delivery
    text = 'x' * (fub_transcripts.PART_SIZE * 2 + 20)
    result = send(transcript=[{'role': 'user', 'text': text}])
    assert result['parts'] == 3 and len(calls) == 3
    assert sum(c[2]['json']['body'].count('x') for c in calls) >= len(text)
    assert [c[2]['json']['subject'] for c in calls] == [f'BlackSync call transcript ({i}/3)' for i in range(1, 4)]
    send()
    assert len(calls) == 3


def test_missing_transcript_does_not_create_empty_note(delivery):
    calls, _, send, _ = delivery
    assert send(transcript=[])['status'] == 'unavailable'
    assert calls == []


def test_unknown_write_outcome_is_not_blindly_retried(delivery):
    calls, state, send, _ = delivery
    state['error'] = CrmError('Connection lost after write')
    with pytest.raises(CrmError):
        send()
    state['error'] = None
    with pytest.raises(CrmError, match='no duplicate was sent'):
        send()
    assert len(calls) == 1


def test_rejected_note_can_retry_after_permissions_are_fixed(delivery):
    calls, state, send, _ = delivery
    state['error'] = CrmError('Forbidden', status=403)
    with pytest.raises(CrmError):
        send()
    state['error'] = None
    assert send()['status'] == 'sent'
    assert len(calls) == 2


def test_transcript_setting_and_browser_exclusion(client, delivery):
    calls, _, send, _ = delivery
    assert client.patch('/api/integrations/crm/followupboss', json={'note_transcript': False}).status_code == 200
    assert send()['status'] == 'disabled' and not calls
    assert client.get('/api/integrations/crm').json()['connections'][0]['settings']['note_transcript'] is False
    client.patch('/api/integrations/crm/followupboss', json={'note_transcript': True})
    with pytest.raises(CrmError, match='browser test'):
        send(call_type='web')
    assert not calls


def test_cross_workspace_and_wrong_contact_are_blocked(delivery):
    calls, _, send, _ = delivery
    with pytest.raises(CrmError, match='workspace'):
        send(org_id=uuid.uuid4())
    assert calls == []


def test_normal_call_sync_sends_transcript_from_stored_call(delivery, monkeypatch):
    from app.models.lead import Lead
    from app.services.crm.providers import FollowUpBoss
    calls, _, _, call_id = delivery
    original = sync.http_for
    monkeypatch.setattr(sync, 'http_for', lambda conn: (FollowUpBoss(), original(conn)[1]))
    async def noop(*args):
        return None
    monkeypatch.setattr(sync, '_move_stage', noop)
    monkeypatch.setattr(sync, '_move_installed_deal', noop)

    async def go():
        async with AsyncSessionLocal() as db:
            call = await db.get(CallLog, uuid.UUID(call_id))
            lead = await db.get(Lead, call.lead_id)
            conn = (await db.execute(select(CrmConnection).where(CrmConnection.org_id == call.org_id,
                CrmConnection.provider == 'followupboss'))).scalar_one()
            await sync.push_call_to(db, conn, {'call_id': call_id, 'outcome': 'completed',
                'contact': {'id': str(lead.id), 'name': lead.name, 'phone': lead.phone}})
            await db.commit()
    asyncio.run(go())
    assert any(path == '/v1/calls' for _, path, _ in calls)
    notes = [kw['json'] for _, path, kw in calls if path == '/v1/notes']
    assert len(notes) == 1 and 'Agent: Is this James?' in notes[0]['body']


def test_radar_historical_transcript_sync_never_repeats_routing(client, crm, monkeypatch):
    import httpx
    import json
    from tests.test_radar_automations import saved, rule_body, execute_all
    from app.services.crm.http import BaseHttp
    old = BaseHttp.client_factory
    notes = []
    async def handle(req):
        if req.url.path == '/v1/notes' and req.method == 'POST':
            notes.append(json.loads(req.content))
            return httpx.Response(201, json={'id': len(notes)})
        async with old() as c:
            return await c.request(req.method, str(req.url), content=req.content, headers=req.headers)
    monkeypatch.setattr(BaseHttp, 'client_factory', staticmethod(lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle))))
    client.patch('/api/integrations/crm/followupboss', json={'note_transcript': False, 'log_calls': True})
    call_id, _ = add_call(crm)
    rule = saved(client, rule_body())
    client.patch(f"/api/radar/automations/{rule['id']}/state", json={'status': 'active'})
    assert client.post(f"/api/radar/automations/{rule['id']}/run", json={'call_ids': [call_id]}).status_code == 200
    execute_all()
    row = next(x for x in client.get('/api/radar/automations/activity').json()['items'] if x['call_id'] == call_id)
    assert row['status'] == 'succeeded' and not notes
    client.patch('/api/integrations/crm/followupboss', json={'note_transcript': True})
    before = len([x for x in crm['calls'] if x[0] in ('POST', 'PUT')])
    for _ in range(2):
        r = client.post(f"/api/radar/automations/activity/{row['id']}/sync-transcript")
        assert r.status_code == 200, r.text
        assert r.json()['result']['transcript']['status'] == 'sent'
    assert len(notes) == 1
    assert len([x for x in crm['calls'] if x[0] in ('POST', 'PUT')]) == before
    assert client.post(f'/api/radar/automations/activity/{uuid.uuid4()}/sync-transcript').status_code == 404
