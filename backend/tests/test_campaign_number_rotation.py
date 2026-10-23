import asyncio
import uuid
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.billing import PhoneNumber
from app.models.campaign import Campaign
from app.models.call_log import CallLog
from app.services.telephony import campaign_caller_id_for, TelephonyError


def run(coro): return asyncio.run(coro)

@pytest.fixture
def pool(client):
    org_id=uuid.UUID(client.get('/api/auth/me').json()['org']['id'])
    suffix=uuid.uuid4().int % 1000000
    numbers=[f'+1415{suffix:06d}{i}' for i in range(3)]
    async def seed():
        async with AsyncSessionLocal() as db:
            for i,n in enumerate(numbers): db.add(PhoneNumber(org_id=org_id,number=n,status='active',source='assigned',carrier='signalwire',is_default=i==0))
            await db.commit()
    run(seed())
    return org_id,numbers


def campaign(client,numbers,**kwargs):
    r=client.post('/api/campaigns/',json={'name':'Rotation test','number_rotation_enabled':True,'caller_number_pool':numbers,**kwargs})
    assert r.status_code==201,r.text
    return uuid.UUID(r.json()['id'])


def pick(org,cid,lead=None,commit=True,agent=None):
    async def go():
        async with AsyncSessionLocal() as db:
            number=await campaign_caller_id_for(db,org,agent,cid,lead)
            if commit:await db.commit()
            else:await db.rollback()
            return number
    return run(go())


def test_round_robin_survives_new_sessions_and_rollback(client,pool):
    org,numbers=pool;cid=campaign(client,numbers)
    assert pick(org,cid)==numbers[0]
    assert pick(org,cid,commit=False)==numbers[1]
    assert pick(org,cid)==numbers[1]
    assert pick(org,cid)==numbers[2]
    assert pick(org,cid)==numbers[0]
    # Changing the ordered pool resets the next committed selection to A.
    changed=client.patch(f'/api/campaigns/{cid}',json={'caller_number_pool':numbers[::-1]})
    assert changed.status_code==200,changed.text
    assert pick(org,cid)==numbers[2]


def test_retries_same_or_different_from_committed_call_history(client,pool):
    org,numbers=pool;cid=campaign(client,numbers)
    lead=client.post('/api/contacts',json={'name':'Retry','phone':'+14155550091','campaign_id':str(cid)}).json()
    async def seed():
        async with AsyncSessionLocal() as db:
            db.add(CallLog(org_id=org,lead_id=uuid.UUID(lead['id']),campaign_id=cid,from_phone=numbers[0],call_type='outbound',status='no_answer',livekit_room_name=str(uuid.uuid4())))
            await db.commit()
    run(seed())
    assert pick(org,cid,uuid.UUID(lead['id']))==numbers[0]
    # Same-number retry did not consume the first-attempt cursor.
    assert pick(org,cid)==numbers[0]
    assert client.patch(f'/api/campaigns/{cid}',json={'retry_caller_policy':'different'}).status_code==200
    assert pick(org,cid,uuid.UUID(lead['id']))==numbers[1]
    assert pick(org,cid,uuid.UUID(lead['id']))!=numbers[0]
    # Removing the previous number makes the same-number policy fail explicitly.
    assert client.patch(f'/api/campaigns/{cid}',json={'caller_number_pool':numbers[1:],'retry_caller_policy':'same'}).status_code==200
    with pytest.raises(TelephonyError,match='previous caller number'):pick(org,cid,uuid.UUID(lead['id']))


def test_different_retry_skips_cursor_matching_previous_number(client,pool):
    org,numbers=pool;cid=campaign(client,numbers,retry_caller_policy='different')
    lead=client.post('/api/contacts',json={'name':'Retry skip','phone':'+14155550092','campaign_id':str(cid)}).json()
    async def seed():
        async with AsyncSessionLocal() as db:
            db.add(CallLog(org_id=org,lead_id=uuid.UUID(lead['id']),campaign_id=cid,from_phone=numbers[0],call_type='outbound',status='voicemail',livekit_room_name=str(uuid.uuid4())))
            await db.commit()
    run(seed())
    assert pick(org,cid,uuid.UUID(lead['id']))==numbers[1]
    assert pick(org,cid)==numbers[2]


def test_pool_validation_and_default_off(client,pool):
    org,numbers=pool
    normal=client.post('/api/campaigns/',json={'name':'Legacy selection'}).json()
    assert normal['number_rotation_enabled'] is False and normal['retry_caller_policy']=='same'
    assert pick(org,uuid.UUID(normal['id']),agent=SimpleNamespace(caller_number=numbers[1]))==numbers[1]
    for body in [
        {'number_rotation_enabled':True},
        {'number_rotation_enabled':True,'caller_number_pool':numbers[:1]},
        {'number_rotation_enabled':True,'caller_number_pool':[numbers[0],numbers[0]]},
        {'number_rotation_enabled':True,'caller_number_pool':[numbers[0],'+19999999999']},
        {'retry_caller_policy':'random'},
    ]:
        r=client.patch('/api/campaigns/'+normal['id'],json=body)
        assert r.status_code in (400,422),r.text


def test_release_and_tenant_guards_do_not_fall_back(client,pool):
    org,numbers=pool;cid=campaign(client,numbers)
    async def release():
        async with AsyncSessionLocal() as db:
            n=(await db.execute(select(PhoneNumber).where(PhoneNumber.number==numbers[0]))).scalar_one()
            n.status='released';await db.commit()
    run(release())
    with pytest.raises(TelephonyError,match='active numbers'):pick(org,cid)
    with pytest.raises(TelephonyError,match='not on this account'):pick(uuid.uuid4(),cid)
    # It remains possible to disable rotation even when a saved pool contains a released number.
    assert client.patch(f'/api/campaigns/{cid}',json={'number_rotation_enabled':False,'caller_number_pool':numbers}).status_code==200


def test_rechat_has_official_docs_and_no_fake_connector(client):
    catalog=client.get('/api/integrations/crm').json()
    provider=next(p for p in catalog['providers'] if p['key']=='rechat')
    assert provider['docs_url']=='https://docs.api.rechat.com/master/user.html'
    assert provider['native'] is False and provider['can_import'] is False
    r=client.post('/api/integrations/crm/rechat/connect',json={'fields':{'api_key':'not-sent'}})
    assert r.status_code==503


def _calls(org, cid, number, n, picked, hours_ago=1):
    from datetime import datetime, timedelta, timezone
    async def go():
        async with AsyncSessionLocal() as db:
            for i in range(n):
                db.add(CallLog(org_id=org, campaign_id=cid, from_phone=number, call_type='outbound',
                               status='completed' if i < picked else 'no_answer',
                               outcome='completed' if i < picked else 'no_answer',
                               answered_at=datetime.now(timezone.utc) if i < picked else None,
                               started_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
                               livekit_room_name=str(uuid.uuid4())))
            await db.commit()
    run(go())


def test_daily_cap_skips_a_number_that_has_dialed_enough(client, pool):
    org, numbers = pool
    cid = campaign(client, numbers, max_calls_per_number_day=5)
    _calls(org, cid, numbers[0], 5, picked=2)
    picks = {pick(org, cid) for _ in range(4)}
    assert numbers[0] not in picks and picks == {numbers[1], numbers[2]}


def test_low_pickup_number_is_rested_and_can_be_resumed(client, pool):
    org, numbers = pool
    cid = campaign(client, numbers, max_calls_per_number_day=500)
    _calls(org, cid, numbers[0], 25, picked=1, hours_ago=30)   # 4% pickups: likely labeled spam
    _calls(org, cid, numbers[1], 25, picked=10, hours_ago=30)  # 40%
    _calls(org, cid, numbers[2], 25, picked=9, hours_ago=30)   # 36%
    picks = {pick(org, cid) for _ in range(4)}
    assert numbers[0] not in picks
    row = next(n for n in client.get('/api/phone-numbers').json()['numbers'] if n['number'] == numbers[0])
    assert row['health']['low_pickups'] and row['health']['resting_until'] and row['health']['dials_7d'] == 25
    assert client.post(f"/api/phone-numbers/{row['id']}/resume").status_code == 200
    row = next(n for n in client.get('/api/phone-numbers').json()['numbers'] if n['number'] == numbers[0])
    assert row['health']['resting_until'] is None


def test_warm_up_rests_each_number_not_the_whole_campaign(client, pool):
    from app.routers import campaigns as c
    from app.services import number_health
    org, numbers = pool
    cid = campaign(client, numbers)
    camp = SimpleNamespace(warmup_enabled=True, number_rotation_enabled=True, caller_number_pool=numbers,
                           warmup_min_gap_seconds=180, warmup_max_gap_seconds=180, warmup_batch_size=10,
                           warmup_rest_seconds=900)
    assert c._per_number_pacing(camp)
    key = str(cid)
    first = pick(org, cid)
    c._rest_number(key, camp, first)
    blocked, free_at = c._pacing_blocked(key)
    assert blocked == {first} and free_at is not None
    # The next pick skips the resting number and dials right away from another.
    async def next_pick():
        number_health.pacing_blocked.set(blocked)
        async with AsyncSessionLocal() as db:
            n = await campaign_caller_id_for(db, org, None, cid, None)
            await db.commit()
            return n
    second = run(next_pick())
    assert second != first
    c._rest_number(key, camp, second)
    blocked, _ = c._pacing_blocked(key)
    remaining = set(numbers) - blocked
    assert len(remaining) == 1
    # All three resting: the pick says when to try again instead of dialing.
    c._rest_number(key, camp, remaining.pop())
    blocked, _ = c._pacing_blocked(key)
    async def all_blocked():
        number_health.pacing_blocked.set(blocked)
        async with AsyncSessionLocal() as db:
            await campaign_caller_id_for(db, org, None, cid, None)
    with pytest.raises(number_health.CallersResting):
        run(all_blocked())
    c._NUMBER_PACE.pop(key, None)
