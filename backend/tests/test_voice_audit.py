"""Installed-SDK regressions; no live calls or provider writes."""
import asyncio
from types import SimpleNamespace as NS

import pytest

from app.agent.committed_actions import CommittedActions, ActionUncertain, NoAction
from app.agent.voice_trace import VoiceTrace, owning_speech, short_sentence_tokenizer
from app.services import calendar


def context(interrupted=False):
    return NS(speech_handle=NS(interrupted=interrupted, id='speech_test', num_steps=1))


def tools(cfg=None, variables=None):
    import agent_worker as w
    run = w._CallRun('audit', 'outbound')
    ctx = NS(room=NS(name='audit', remote_participants={'sip_test': NS(identity='sip_test')}))
    ts = w._build_tools(cfg or {'enable_booking': True}, run, ctx, {}, variables or {})
    return run, {t.__name__: t for t in ts}


@pytest.mark.asyncio
async def test_calendar_without_credentials_never_invents_availability_or_receipt(monkeypatch):
    monkeypatch.setattr(calendar.settings, 'calcom_api_key', '')
    monkeypatch.setattr(calendar.settings, 'calcom_event_type_id', '')
    with pytest.raises(calendar.CalendarUnavailable):
        await calendar.fetch_slots()
    with pytest.raises(calendar.CalendarUnavailable):
        await calendar.create_booking('2030-01-08T15:00:00Z', 'test@example.com', '')
    assert await calendar.fetch_slots(allow_mock=True)  # explicit playground simulator only


@pytest.mark.asyncio
async def test_cancelled_waiter_keeps_write_receipt_and_does_not_repeat():
    gate = CommittedActions()
    entered, release = asyncio.Event(), asyncio.Event()
    writes, receipts = [], []
    async def operation():
        writes.append('write')
        entered.set()
        await release.wait()
        receipts.append('receipt')
        return 'confirmed'
    task = asyncio.create_task(gate.run('booking', operation, context=context()))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    release.set()
    assert await gate.run('booking', operation, context=context()) == 'confirmed'
    assert writes == ['write'] and receipts == ['receipt']


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [TimeoutError, ConnectionError, RuntimeError])
async def test_uncertain_write_is_not_retried(failure):
    gate, writes = CommittedActions(), []
    async def write():
        writes.append(1)
        raise failure('provider disconnected')
    for _ in range(3):
        with pytest.raises(ActionUncertain): await gate.run('booking', write, context=context())
    assert writes == [1]


@pytest.mark.asyncio
async def test_interrupted_turn_cannot_start_write():
    ran = []
    async def write(): ran.append(1)
    with pytest.raises(ActionUncertain):
        await CommittedActions().run('transfer', write, context=context(True))
    assert not ran


@pytest.mark.asyncio
async def test_twenty_concurrent_duplicate_requests_issue_one_write():
    gate, writes = CommittedActions(), []
    async def write():
        writes.append(1)
        await asyncio.sleep(.01)
        return 'receipt'
    out = await asyncio.gather(*(gate.run('booking', write, context=context()) for _ in range(20)))
    assert out == ['receipt'] * 20 and writes == [1]


@pytest.mark.asyncio
async def test_prewrite_validation_failure_allows_corrected_request():
    gate = CommittedActions()
    async def stale(): raise NoAction('slot gone')
    with pytest.raises(NoAction): await gate.run('booking', stale, context=context())
    async def fresh(): return 'receipt'
    assert await gate.run('booking', fresh, context=context()) == 'receipt'


@pytest.mark.asyncio
async def test_stale_slot_does_not_book_and_returns_no_success(monkeypatch):
    run, ts = tools(variables={'email': 'test@example.com'})
    run.slots = [{'start': '2030-01-08T15:00:00Z', 'label': 'Tuesday at 3 PM UTC'}]
    async def empty(*a, **kw): return []
    async def never(*a, **kw): pytest.fail('stale availability must not book')
    monkeypatch.setattr(calendar, 'fetch_slots', empty)
    monkeypatch.setattr(calendar, 'create_booking', never)
    result = await ts['book_appointment'](run.slots[0]['label'], 'test@example.com', context())
    assert result.startswith('Not booked:') and not run.meeting_time


@pytest.mark.asyncio
async def test_duplicate_different_slot_requests_cannot_double_book(monkeypatch):
    run, ts = tools(variables={'email': 'test@example.com'})
    run.slots = [{'start': '2030-01-08T15:00:00Z', 'label': 'Tuesday at 3 PM UTC'},
                 {'start': '2030-01-08T16:00:00Z', 'label': 'Tuesday at 4 PM UTC'}]
    writes = []
    async def available(*a, **kw): return run.slots
    async def book(start, *a, **kw):
        writes.append(start)
        await asyncio.sleep(.01)
        return 'https://cal.com/booking/receipt'
    monkeypatch.setattr(calendar, 'fetch_slots', available)
    monkeypatch.setattr(calendar, 'create_booking', book)
    out = await asyncio.gather(*(ts['book_appointment'](s['label'], 'test@example.com', context()) for s in run.slots))
    assert len(writes) == 1 and run.meeting_time == run.slots[0]['label']
    assert all(run.meeting_time in x for x in out)


@pytest.mark.asyncio
async def test_booking_receipt_survives_interruption(monkeypatch):
    run, ts = tools(variables={'email': 'test@example.com'})
    run.slots = [{'start': '2030-01-08T15:00:00Z', 'label': 'Tuesday at 3 PM UTC'}]
    entered, release = asyncio.Event(), asyncio.Event()
    async def available(*a, **kw): return run.slots
    async def book(*a, **kw):
        entered.set()
        await release.wait()
        return 'https://cal.com/booking/receipt'
    monkeypatch.setattr(calendar, 'fetch_slots', available)
    monkeypatch.setattr(calendar, 'create_booking', book)
    task = asyncio.create_task(ts['book_appointment'](run.slots[0]['label'], 'test@example.com', context()))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    release.set()
    await asyncio.sleep(.01)
    assert run.meeting_time and run.meeting_link and run.transcript[-1]['result']['success']


@pytest.mark.asyncio
async def test_failed_booking_is_neither_receipt_nor_success(monkeypatch):
    run, ts = tools(variables={'email': 'test@example.com'})
    run.slots = [{'start': '2030-01-08T15:00:00Z', 'label': 'Tuesday at 3 PM UTC'}]
    writes = []
    async def available(*a, **kw): return run.slots
    async def fail(*a, **kw):
        writes.append(1)
        raise calendar.CalendarUnavailable('timeout')
    monkeypatch.setattr(calendar, 'fetch_slots', available)
    monkeypatch.setattr(calendar, 'create_booking', fail)
    for _ in range(2):
        result = await ts['book_appointment'](run.slots[0]['label'], 'test@example.com', context())
        assert 'not confirmed' in result
    assert writes == [1] and not run.meeting_time
    assert not run.transcript[-1]['result']['success']


@pytest.mark.asyncio
async def test_calendar_failure_is_not_reported_as_no_openings(monkeypatch):
    run, ts = tools()
    async def fail(*a, **kw): raise calendar.CalendarUnavailable('timeout')
    monkeypatch.setattr(calendar, 'fetch_slots', fail)
    result = await ts['check_availability'](context())
    assert 'unavailable, not fully booked' in result and not run.slots


def test_tool_schemas_match_installed_sdk_and_hide_context():
    from livekit.agents.llm.utils import build_strict_openai_schema
    _, ts = tools({'enable_booking': True, 'transfer_number': '+14155550100'})
    for tool in ts.values():
        spec = build_strict_openai_schema(tool)
        assert 'context' not in spec['function']['parameters']['properties']


@pytest.mark.asyncio
@pytest.mark.parametrize('text', ['Tuesday works. Would morning suit you?', 'It costs forty dollars. Is that within budget?',
                                 'No. We can try another day.', 'Yes. I can help with that.'])
async def test_short_sentence_released_before_upstream_finishes(text):
    fast, old = short_sentence_tokenizer(True).stream(), short_sentence_tokenizer(False).stream()
    first, rest = text.split('. ', 1)
    fast.push_text(first + '. ' + rest[:15])
    old.push_text(first + '. ' + rest[:15])
    fast_task, old_task = asyncio.create_task(anext(fast)), asyncio.create_task(anext(old))
    await asyncio.sleep(.01)
    assert fast_task.done() and fast_task.result().token == first + '.'
    if len(first + '.') < 20:
        assert not old_task.done()
    fast.end_input(); old.end_input()
    await old_task
    await fast.aclose(); await old.aclose()


@pytest.mark.parametrize('text', ['14 Main St. in San Francisco.', 'The amount is 12.50 dollars.',
                                 'Email jane.doe@example.com.', 'Call +1 415 555 0123.'])
def test_tokenizer_preserves_address_number_and_email(text):
    assert ' '.join(short_sentence_tokenizer(True).tokenize(text)) == text


@pytest.mark.asyncio
async def test_trace_stream_is_incremental_cancellable_and_content_free():
    now, events, closed = [10.0], [], []
    tr = VoiceTrace(lambda event, **kw: events.append({'event': event, **kw}), clock=lambda: now[0])
    async def source():
        try:
            yield 'private caller content'
            await asyncio.Event().wait()
        finally: closed.append(True)
    stream = tr.stream(source(), 'llm_chunk', speech=context().speech_handle)
    assert await anext(stream) == 'private caller content'
    now[0] += .1
    await stream.aclose()
    assert closed and len(events) == 2 and events[1]['offset_ms'] == 100
    assert 'private' not in str(events) and events[0]['speech_id'] == 'speech_test'


def test_sdk_context_correlates_speculative_speech_without_guessing():
    from livekit.agents.voice.agent_activity import _SpeechHandleContextVar
    h = context().speech_handle
    token = _SpeechHandleContextVar.set(h)
    try: assert owning_speech() is h
    finally: _SpeechHandleContextVar.reset(token)
    assert owning_speech() is None


def test_latency_summary_does_not_sum_overlapping_stages():
    import agent_worker as w
    run = w._CallRun('audit', 'web')
    run.lat = {'eou': [.5], 'llm': [.4], 'tts': [.2]}
    result = run.latency_summary()
    assert result['avg_response'] is None and result['response_metric'] == 'unmeasured'
    assert 'pipeline_sum_estimate' not in result


def test_agent_objective_script_and_voice_are_preserved():
    from app.agent.runtime import build_instructions
    cfg = {'system_prompt': 'Qualify commercial tenants. Ask about lease expiry.', 'voice_id': 'custom-voice',
           'first_message': 'Hello, is this {{name}}?', 'enable_booking': True}
    original = dict(cfg)
    prompt = build_instructions(cfg, {'name': 'Jamie'})
    assert cfg == original and cfg['system_prompt'] in prompt
    assert 'latest confirmed identity' in prompt and 'only when this tool confirms it' in prompt

@pytest.mark.asyncio
async def test_transfer_receipt_is_recorded_only_after_provider_accepts(monkeypatch):
    import agent_worker as w
    from livekit import api
    run, ts = tools({'transfer_number': '+14155550100'})
    entered, release = asyncio.Event(), asyncio.Event()
    requests = []
    async def transfer(req):
        requests.append(req)
        entered.set()
        await release.wait()
    async def close(): pass
    async def post(*a): pass
    monkeypatch.setattr(api, 'LiveKitAPI', lambda **kw: NS(sip=NS(transfer_sip_participant=transfer), aclose=close))
    monkeypatch.setattr(w, '_post_run_outcome', post)
    c = context()
    async def playout(): pass
    c.wait_for_playout = playout
    task = asyncio.create_task(ts['transfer_call'](c))
    await entered.wait()
    assert run.outcome is None and not run.transcript
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    release.set()
    result = await ts['transfer_call'](context_with_playout())
    assert 'accepted' in result and run.outcome == 'transferred' and len(requests) == 1
    assert run.transcript[-1]['result']['success']
    await run.post_task


def context_with_playout():
    c = context()
    async def playout(): pass
    c.wait_for_playout = playout
    return c


@pytest.mark.asyncio
async def test_transfer_failure_never_records_transferred_or_retries(monkeypatch):
    from livekit import api
    run, ts = tools({'transfer_number': '+14155550100'})
    writes = []
    async def transfer(req):
        writes.append(1)
        raise TimeoutError()
    async def close(): pass
    monkeypatch.setattr(api, 'LiveKitAPI', lambda **kw: NS(sip=NS(transfer_sip_participant=transfer), aclose=close))
    for _ in range(2):
        assert 'not confirmed' in await ts['transfer_call'](context_with_playout())
    assert run.outcome is None and writes == [1]
    assert all(not t['result']['success'] for t in run.transcript)


@pytest.mark.asyncio
async def test_interruption_during_handoff_line_prevents_transfer(monkeypatch):
    from livekit import api
    _, ts = tools({'transfer_number': '+14155550100'})
    monkeypatch.setattr(api, 'LiveKitAPI', lambda **kw: pytest.fail('Must not connect after correction'))
    c = context()
    async def playout(): c.speech_handle.interrupted = True
    c.wait_for_playout = playout
    assert 'cancelled before connecting' in await ts['transfer_call'](c)


@pytest.mark.asyncio
async def test_runtime_constructor_preserves_selected_voice_model_script_and_tuning(monkeypatch):
    import agent_worker as w
    captured = {}
    class StopProbe(Exception): pass
    def capture(**kwargs):
        captured.update(kwargs)
        raise StopProbe()
    monkeypatch.setattr(w, 'AgentSession', capture)
    monkeypatch.setattr(w, '_job_vad', lambda ctx: object())
    monkeypatch.setattr(w, 'MultilingualModel', lambda: object())
    monkeypatch.setattr(w.settings, 'cartesia_api_key', 'test-key')
    monkeypatch.setattr(w.settings, 'deepgram_api_key', 'test-key')
    monkeypatch.setattr(w.settings, 'openai_api_key', 'test-key')
    cfg = {'name': 'test', 'first_message': 'Hello there.', 'system_prompt': 'Custom objective untouched.',
           'voice_id': '378695da-44e9-4fc7-a9cb-efcb0d2037cc', 'voice_speed': 1.1,
           'llm_model': 'gpt-4.1-mini', 'temperature': 0.2, 'voice_tuning': {'responsiveness': .75}}
    original = dict(cfg)
    with pytest.raises(StopProbe):
        await w._run_configurable(NS(room=NS(name='probe')), {'agent':cfg,'call_type':'web'})
    assert cfg == original
    assert captured['tts']._opts.voice == cfg['voice_id'] and captured['tts']._opts.speed == 1.1
    assert captured['llm'].model == cfg['llm_model']
    assert captured['turn_handling']['endpointing'] == {'mode':'dynamic','min_delay':.35,'max_delay':2.5}
    assert captured['turn_handling']['preemptive_generation'] == {'enabled':True,'preemptive_tts':True}


def test_trace_report_does_not_sum_overlapping_stages_or_merge_clocks():
    from scripts.voice_trace_report import report
    base = {'event':'voice_trace','clock_id':'a','speech_id':'speech_1'}
    rows = [dict(base,stage='speech_created',source='generate_reply',offset_ms=1),
            dict(base,stage='llm_request',turn_key='t',offset_ms=2),
            dict(base,stage='turn_committed',turn_key='t',offset_ms=20),
            dict(base,stage='agent_speaking',offset_ms=30),
            dict(base,stage='sdk_item_metrics',role='assistant',offset_ms=100,e2e_latency=.2,
                 llm_node_ttft=.3,tts_node_ttfb=.2),
            dict(base,clock_id='b',stage='sdk_item_metrics',role='assistant',offset_ms=200,e2e_latency=.5)]
    result=report(rows)
    assert result['distributions']['ordinary_reply'] == {'n':1,'p50_ms':200,'p95_ms':200}
    assert len(result['timelines']) == 2
    assert result['speculation']['subsequently_playing'] == 1

@pytest.mark.asyncio
async def test_read_timeout_before_write_allows_later_valid_booking(monkeypatch):
    run, ts = tools(variables={'email': 'test@example.com'})
    run.slots = [{'start':'2030-01-08T15:00:00Z','label':'Tuesday at 3 PM UTC'}]
    reads, writes = [], []
    async def available(*a, **kw):
        reads.append(1)
        if len(reads) == 1: raise calendar.CalendarUnavailable('timeout before write')
        return run.slots
    async def book(*a, **kw):
        writes.append(1)
        return 'https://cal.com/booking/receipt'
    monkeypatch.setattr(calendar,'fetch_slots',available)
    monkeypatch.setattr(calendar,'create_booking',book)
    assert 'availability could not be verified' in await ts['book_appointment'](run.slots[0]['label'],'test@example.com',context())
    assert 'Booked for' in await ts['book_appointment'](run.slots[0]['label'],'test@example.com',context())
    assert len(reads) == 2 and len(writes) == 1


@pytest.mark.asyncio
async def test_generated_pcm_is_counted_but_never_claimed_published_or_heard():
    import numpy as np
    from livekit import rtc
    events=[]
    trace=VoiceTrace(lambda event,**fields:events.append({'event':event,**fields}))
    async def pcm():
        for _ in range(3):
            yield rtc.AudioFrame(data=np.zeros(2400,dtype=np.int16).tobytes(),sample_rate=24000,
                                 num_channels=1,samples_per_channel=2400)
    output=[f async for f in trace.stream(pcm(),'tts_audio',speech=context().speech_handle,audio=True)]
    assert len(output)==3 and events[-1]['generated_audio_seconds']==.3
    assert not any('audible' in e['stage'] or 'published' in e['stage'] for e in events)

@pytest.mark.asyncio
async def test_single_available_slot_never_claims_two(monkeypatch):
    _, ts=tools()
    async def one(*a,**kw): return [{'start':'2030-01-08T15:00:00Z','label':'Tuesday at 3 PM UTC'}]
    monkeypatch.setattr(calendar,'fetch_slots',one)
    result=await ts['check_availability'](context())
    assert 'Offer this verified time' in result and 'both' not in result


@pytest.mark.asyncio
async def test_playground_booking_failure_does_not_set_booked_state(monkeypatch):
    from app.services import llm
    import json
    replies=iter([
        {'choices':[{'message':{'role':'assistant','content':"It's booked!",'tool_calls':[
            {'id':'audit-book','type':'function','function':{'name':'book_appointment',
             'arguments':json.dumps({'slot':'Tuesday at 3 PM UTC','email':'test@example.com'})}}]}}]},
        {'choices':[{'message':{'role':'assistant','content':'I could not confirm that booking.'}}]},
    ])
    async def chat(*a,**kw): return next(replies)
    async def fail(*a,**kw): return ''
    monkeypatch.setattr(llm,'_chat',chat)
    monkeypatch.setattr(calendar,'create_booking',fail)
    result=await llm.playground_reply({'enable_booking':True},{'email':'test@example.com'},
        [{'role':'user','content':'Yes, book it.'}],
        {'slots':[{'start':'2030-01-08T15:00:00Z','label':'Tuesday at 3 PM UTC'}]})
    assert not result['state'].get('booked') and 'could not confirm' in result['reply']


def test_trace_report_accepts_actual_console_and_railway_rows():
    import json
    from scripts.voice_trace_report import parse_line
    line='2026-10-17 01:00:00 [info ] voice_trace clock_id=123-test offset_ms=12.5 speech_id=speech_1 stage=speech_done interrupted=True'
    row=parse_line(line)
    assert row['offset_ms']==12.5 and row['interrupted'] is True
    assert parse_line(json.dumps({'message':line}))==row
    assert parse_line('unrelated worker started') is None
