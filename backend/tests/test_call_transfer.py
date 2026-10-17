from types import SimpleNamespace as NS
import pytest
from livekit import api, rtc
from app.agent import call_transfer as t
from tests.test_voice_audit import tools, context_with_playout


def test_real_sip_participant_without_identity_prefix_and_ambiguous_legs():
    browser = NS(identity='browser',kind=rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,attributes={})
    caller = NS(identity='caller-123',kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP,attributes={})
    assert t.caller_identity([browser,caller]) == 'caller-123'
    assert t.caller_identity([browser]) is None
    browser.identity = 'sip_browser'
    assert t.caller_identity([browser]) is None
    assert t.caller_identity([caller,NS(identity='second',attributes={'sip.callID':'another'})]) is None
    assert t.caller_identity([NS(identity='sip_legacy')]) == 'sip_legacy'
    assert t.caller_identity([NS(identity='sip_left',attributes={'sip.callStatus':'hangup'})]) is None


def test_transfer_number_normalization_and_explicit_ring_window():
    req = t.request('room','caller','(415) 555-0123')
    assert req.transfer_to == 'tel:+14155550123'
    assert req.ringing_timeout.seconds == 45
    assert t.REQUEST_SECONDS > req.ringing_timeout.seconds
    assert t.DEADLINE_SECONDS > t.REQUEST_SECONDS
    with pytest.raises(ValueError): t.request('room','caller','invalid')


@pytest.mark.parametrize('response,status',[
    (None,'unknown'),
    (api.TransferSIPParticipantResponse(),'unknown'),
    (api.TransferSIPParticipantResponse(status=api.SIPTransferStatus.STS_TRANSFER_FAILED),'failed'),
    (api.TransferSIPParticipantResponse(status=api.SIPTransferStatus.STS_TRANSFER_SUCCESSFUL),'completed')])
def test_response_status_is_authoritative(response,status):
    assert t.receipt(response)['status'] == status


@pytest.mark.asyncio
@pytest.mark.parametrize('status,expected',[
    (api.SIPTransferStatus.STS_TRANSFER_FAILED,'failed'),
    (api.SIPTransferStatus.STS_TRANSFER_ONGOING,'not confirmed')])
async def test_non_success_response_never_records_transfer_or_repeats(monkeypatch,status,expected):
    run, ts = tools({'transfer_number':'4155550123'})
    calls = []
    async def transfer(req,*,timeout):
        calls.append(req)
        assert timeout == t.REQUEST_SECONDS
        return api.TransferSIPParticipantResponse(status=status)
    async def close(): pass
    monkeypatch.setattr(api,'LiveKitAPI',lambda **kw:NS(sip=NS(transfer_sip_participant=transfer),aclose=close))
    for _ in range(2):
        assert expected in await ts['transfer_call'](context_with_playout())
    assert len(calls) == 1 and run.outcome is None
    assert all(not x['result']['success'] for x in run.transcript)


@pytest.mark.asyncio
async def test_invalid_legacy_number_never_requests_transfer(monkeypatch):
    run, ts = tools({'transfer_number':'bad number'})
    monkeypatch.setattr(api,'LiveKitAPI',lambda **kw:pytest.fail('Must validate before provider write'))
    assert 'not a valid phone number' in await ts['transfer_call'](context_with_playout())
    assert run.outcome is None


def test_provider_diagnostics_exclude_raw_secrets():
    err = RuntimeError('provider rejected password=secret +14155550123')
    assert t.error_details(err) == {'error_type':'RuntimeError'}


def test_saved_transfer_setting_normalizes_and_rejects_invalid_without_overwrite(client,agent_id):
    url = f'/api/agents/{agent_id}'
    response = client.patch(url,json={'transfer_number':'(415) 555-0123'})
    assert response.status_code == 200,response.text
    assert response.json()['transfer_number'] == '+14155550123'
    assert client.patch(url,json={'transfer_number':'not a phone'}).status_code == 422
    assert client.get(url).json()['transfer_number'] == '+14155550123'
    assert client.patch(url,json={'transfer_number':'  '}).json()['transfer_number'] == ''


@pytest.mark.asyncio
async def test_model_cannot_hang_up_claiming_an_unperformed_transfer():
    run, ts = tools({'transfer_number':'+14155550123'})
    result = await ts['end_call'](outcome='transferred',context=context_with_playout())
    assert 'no transfer has completed' in result
    assert run.outcome is None and not run.transcript


@pytest.mark.parametrize('status',['failed','unknown','ongoing'])
def test_dashboard_excludes_unsuccessful_transfer_attempts(status):
    from app.routers.activity import _is_real_transfer
    entry = {'role':'tool','tool':'transfer_call','result':{'success':False,'output':{'status':status}}}
    assert not _is_real_transfer([entry])
    entry['result'] = {'success':True,'output':{'status':'completed'}}
    assert _is_real_transfer([entry])


@pytest.mark.asyncio
async def test_client_cleanup_cannot_erase_confirmed_handoff(monkeypatch):
    import agent_worker as w
    run, ts = tools({'transfer_number':'+14155550123'})
    async def transfer(req,*,timeout):
        return api.TransferSIPParticipantResponse(status=api.SIPTransferStatus.STS_TRANSFER_SUCCESSFUL)
    async def close(): raise RuntimeError('cleanup failure')
    async def post(*args): pass
    monkeypatch.setattr(api,'LiveKitAPI',lambda **kw:NS(sip=NS(transfer_sip_participant=transfer),aclose=close))
    monkeypatch.setattr(w,'_post_run_outcome',post)
    assert 'completed' in await ts['transfer_call'](context_with_playout())
    assert run.outcome == 'transferred' and run.transcript[-1]['result']['success']
    await run.post_task
