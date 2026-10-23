import pytest
from app.agent.voicemail_timing import minimum_connected_seconds, wait_for_voicemail_minimum

@pytest.mark.asyncio
@pytest.mark.parametrize('elapsed,expected',[(1.0,6.0),(6.0,1.0),(7.0,0),(10,0)])
async def test_connected_floor_not_additional_delay(elapsed,expected):
    waits=[]
    async def sleep(seconds): waits.append(seconds)
    await wait_for_voicemail_minimum(100,{},clock=lambda:100+elapsed,sleep=sleep)
    assert sum(waits)==pytest.approx(expected)

@pytest.mark.asyncio
async def test_custom_floor_and_never_under_seven():
    waits=[]
    async def sleep(seconds):waits.append(seconds)
    await wait_for_voicemail_minimum(100,{'voicemail_min_connected_seconds':8},clock=lambda:102,sleep=sleep)
    # A saved value under the 7 s floor (old default 6.2, or 0) still waits until 7 s.
    await wait_for_voicemail_minimum(100,{'voicemail_min_connected_seconds':0},clock=lambda:102,sleep=sleep)
    assert waits==[6, 5]

@pytest.mark.parametrize('raw',[None,{}, {'voicemail_min_connected_seconds':None},
    {'voicemail_min_connected_seconds':float('nan')}, {'voicemail_min_connected_seconds':'bad'}])
def test_existing_or_invalid_config_defaults(raw):
    assert minimum_connected_seconds(raw)==7.0

def test_setting_persists_and_validation(client,agent_id):
    url=f'/api/agents/{agent_id}'
    before=client.get(url).json()
    response=client.patch(url,json={'voice_tuning':{'voicemail_min_connected_seconds':6.2}})
    assert response.status_code==200
    saved=client.get(url).json()
    assert saved['voice_tuning']['voicemail_min_connected_seconds']==6.2
    assert saved['voice_id']==before['voice_id'] and saved['system_prompt']==before['system_prompt']
    for value in [-1,61]:
        assert client.patch(url,json={'voice_tuning':{'voicemail_min_connected_seconds':value}}).status_code==422

@pytest.mark.asyncio
async def test_final_report_follows_hold_and_hangup():
    from app.agent.voicemail_timing import finish_voicemail
    now=[102.0]
    events=[]
    async def sleep(delay):
        events.append(('wait',delay))
        now[0]+=delay
    async def hangup():events.append(('hangup',now[0]))
    async def report():events.append(('report',now[0]))
    await finish_voicemail(100,{},hangup=hangup,report=report,clock=lambda:now[0],sleep=sleep)
    assert [e[0] for e in events]==['wait','hangup','report']
    assert events[0][1]==pytest.approx(5.0)
    assert events[1][1]==pytest.approx(107.0)
    assert events[2][1]==pytest.approx(107.0)
