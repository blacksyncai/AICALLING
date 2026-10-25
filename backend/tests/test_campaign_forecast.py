import asyncio
import uuid
from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.call_log import CallLog
from app.models.account import Organization
from app.services.campaign_forecast import forecast,next_eligible
from app.services import quiet_hours
from tests.test_accounts import _new_account,_login

REAL_QUIET_CHECK=quiet_hours.ok_to_call
NOW=datetime(2026,11,2,16,0,tzinfo=timezone.utc) # Monday 8 AM Pacific

@pytest.fixture
def case(client,make_client):
    org,email=_new_account(client,name='Forecast account')
    owner=_login(make_client,email)
    agent=owner.get('/api/agents/').json()[0]['id']
    r=owner.post('/api/campaigns/',json={'name':'Pacific schedule','agent_id':agent,'timezone':'America/Los_Angeles','call_window_start':'09:00','call_window_end':'17:00','call_days':[0,1,2,3,4],'retry_schedule':[30,120]})
    assert r.status_code==201,r.text
    return org,owner,uuid.UUID(r.json()['id'])


def seed(case,rows):
    async def go():
        async with AsyncSessionLocal() as db:
            for i,fields in enumerate(rows):
                db.add(Lead(org_id=uuid.UUID(case[0]['id']),campaign_id=case[2],name=fields.pop('name',f'Contact {i}'),phone='+14155550123',**fields))
            await db.commit()
    asyncio.run(go())


def get(case,now=NOW):
    async def go():
        async with AsyncSessionLocal() as db:
            c=await db.get(Campaign,case[2]);o=await db.get(Organization,c.org_id)
            return await forecast(db,c,o,now)
    return asyncio.run(go())


def test_counts_next_window_and_actual_redial_times(case):
    seed(case,[{'status':'new'},{'status':'no_answer','attempts':1,'next_attempt_at':NOW+timedelta(hours=2)},
               {'status':'voicemail','attempts':2,'next_attempt_at':NOW-timedelta(hours=1)},
               {'status':'no_answer','attempts':3},{'status':'new','do_not_call':True}, {'status':'interested'}])
    f=get(case)
    assert f['new_contacts']==1 and f['redials']==2
    assert f['next_at']=='2026-11-02T17:00:00+00:00' and f['next_count']==2
    assert f['ready_now']==0 and f['automatic'] is False and f['reason']=='draft'
    assert sum(w['contacts'] for w in f['windows'])==3
    assert f['retry_plan']==[{'retry':1,'delay_minutes':30},{'retry':2,'delay_minutes':120}]
    assert next(c for c in f['contacts'] if c['kind']=='redial' and c['attempt']==2)['eligible_at']=='2026-11-02T18:00:00+00:00'


def test_retry_outside_hours_moves_to_next_allowed_day(case):
    friday=datetime(2026,11,6,23,0,tzinfo=timezone.utc) # Friday 3 PM Pacific
    seed(case,[{'status':'no_answer','attempts':1,'next_attempt_at':datetime(2026,11,7,2,0,tzinfo=timezone.utc)}])
    f=get(case,friday)
    assert f['next_at']=='2026-11-09T17:00:00+00:00'


def test_stale_call_recovery_is_read_only_and_does_not_retry_answered(case):
    seed(case,[{'name':'Stale unanswered','status':'calling','attempts':1,'last_called_at':NOW-timedelta(hours=1)},
               {'name':'Still calling','status':'calling','attempts':1,'last_called_at':NOW-timedelta(minutes=2)}])
    f=get(case)
    assert f['redials']==1 and f['waiting_for_outcome']==1
    async def verify():
        async with AsyncSessionLocal() as db:
            rows=(await db.scalars(select(Lead).where(Lead.campaign_id==case[2]))).all()
            assert all(l.status=='calling' and l.attempts==1 for l in rows)
            old=next(l for l in rows if l.name=='Stale unanswered')
            db.add(CallLog(org_id=old.org_id,lead_id=old.id,campaign_id=case[2],livekit_room_name='forecast-'+uuid.uuid4().hex,status='completed',answered_at=NOW-timedelta(hours=1)))
            await db.commit()
    asyncio.run(verify())
    assert get(case)['redials']==0


def test_quiet_hours_intersects_saved_campaign_window(case,monkeypatch):
    monkeypatch.setattr(quiet_hours,'ok_to_call',REAL_QUIET_CHECK)
    monkeypatch.setattr(quiet_hours,'zones_for',lambda phone:('America/Los_Angeles',))
    async def go():
        async with AsyncSessionLocal() as db:
            c=await db.get(Campaign,case[2]);c.timezone='America/New_York'
            # 9 AM New York is 6 AM Pacific, so eligibility is 11 AM New York.
            assert next_eligible(c,'+14155550123',datetime(2026,11,2,14,0,tzinfo=timezone.utc))==datetime(2026,11,2,16,0,tzinfo=timezone.utc)
    asyncio.run(go())


def test_dst_window_and_invalid_zone(case):
    async def go():
        async with AsyncSessionLocal() as db:
            c=await db.get(Campaign,case[2])
            assert next_eligible(c,'',datetime(2026,11,1,8,0,tzinfo=timezone.utc))==datetime(2026,11,2,17,0,tzinfo=timezone.utc)
            c.timezone='Invalid/Zone';await db.commit()
    asyncio.run(go())
    f=get(case)
    assert f['reason']=='invalid_timezone' and f['next_at'] is None


def test_endpoint_scopes_to_account_and_inbound_has_no_forecast(case,client):
    org,owner,key=case
    assert owner.get(f'/api/campaigns/{key}/forecast').status_code==200
    other,_=_new_account(client,name='Other account')
    async def go():
        async with AsyncSessionLocal() as db:
            c=Campaign(org_id=uuid.UUID(other['id']),name='Private',status='running');db.add(c);await db.commit();return c.id
    foreign=asyncio.run(go())
    assert owner.get(f'/api/campaigns/{foreign}/forecast').status_code==404
    async def inbound():
        async with AsyncSessionLocal() as db:
            c=await db.get(Campaign,key);c.direction='inbound';await db.commit()
    asyncio.run(inbound())
    assert get(case)['reason']=='inbound'


def test_paused_and_completed_do_not_claim_calls_will_go_out(case):
    seed(case,[{'status':'new'}])
    async def status(value):
        async with AsyncSessionLocal() as db:
            c=await db.get(Campaign,case[2]);c.status=value;await db.commit()
    asyncio.run(status('paused'))
    f=get(case);assert f['automatic'] is False and f['reason']=='paused' and f['new_contacts']==1
    asyncio.run(status('completed'))
    f=get(case);assert f['next_at'] is None and f['contacts']==[]
