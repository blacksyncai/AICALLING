import asyncio
import uuid
from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.billing import PhoneNumber
from app.models.agent import Agent
from app.models.campaign import Campaign
from app.services import plivo,plivo_inventory as inventory
from tests.test_accounts import _new_account

GONE='+17374503908'
KEPT='+15125474695'

@pytest.fixture
def case(client,monkeypatch):
    from app.config import settings
    from app.services import telephony
    from app.services.billing import subscriptions,stripe_api
    monkeypatch.setattr(settings,'plivo_auth_id','TESTACCOUNT')
    monkeypatch.setattr(settings,'plivo_auth_token','test-token')
    monkeypatch.setattr(settings,'livekit_sip_plivo_trunk_id','test-trunk')
    calls=[]
    async def media(**kw): calls.append(('media',kw))
    async def billing(db,org): calls.append(('billing',str(org)))
    async def cancel(sid,value):calls.append(('cancel',sid,value));return {}
    monkeypatch.setattr(telephony,'_livekit_numbers',media)
    monkeypatch.setattr(subscriptions,'sync_phone_quantity',billing)
    monkeypatch.setattr(stripe_api,'set_cancel_at_period_end',cancel)
    async def owned(): return {KEPT}
    async def exists(number):return False
    monkeypatch.setattr(plivo,'inventory_numbers',owned)
    monkeypatch.setattr(plivo,'number_exists',exists)
    org,_=_new_account(client,name='Inventory test')
    async def setup():
        async with AsyncSessionLocal() as db:
            # Numbers are unique globally. Use a unique prefix per fixture instance.
            prefix='+1415'+str(uuid.uuid4().int%1000000).zfill(6)
            gone,kept=prefix+'1',prefix+'2'
            old=datetime.now(timezone.utc)-timedelta(days=1)
            a=PhoneNumber(org_id=uuid.UUID(org['id']),number=gone,carrier='plivo',status='active',is_default=True,source='purchased',created_at=old)
            b=PhoneNumber(org_id=uuid.UUID(org['id']),number=kept,carrier='plivo',status='active',created_at=old)
            db.add_all([a,b]);await db.flush()
            agent=Agent(org_id=a.org_id,name='Caller',caller_number=gone)
            db.add(agent);await db.flush()
            outbound=Campaign(org_id=a.org_id,agent_id=agent.id,name='Rotating',status='running',number_rotation_enabled=True,caller_number_pool=[gone,kept])
            inbound=Campaign(org_id=a.org_id,agent_id=agent.id,name='Inbound',status='running',direction='inbound',phone_number_id=a.id)
            db.add_all([outbound,inbound]);await db.flush()
            a.inbound_agent_id,a.inbound_campaign_id=agent.id,inbound.id
            await db.commit()
            return {'org':org['id'],'gone':gone,'kept':kept,'id':a.id,'agent':agent.id,'out':outbound.id,'in':inbound.id,'calls':calls}
    c=asyncio.run(setup())
    async def owned_fixture():
        async with AsyncSessionLocal() as db:
            return set((await db.scalars(select(PhoneNumber.number).where(PhoneNumber.carrier=='plivo', PhoneNumber.status=='active', PhoneNumber.number!=c['gone']))).all())
    monkeypatch.setattr(plivo,'inventory_numbers',owned_fixture)
    return c


def age_missing(case):
    async def go():
        async with AsyncSessionLocal() as db:
            a=await db.get(PhoneNumber,case['id'])
            a.provider_missing_since=datetime.now(timezone.utc)-timedelta(minutes=2)
            await db.commit()
    asyncio.run(go())


def test_confirmed_provider_removal_detaches_dashboard_and_assignments(client,case):
    assert asyncio.run(inventory.sweep())==0
    age_missing(case)
    assert asyncio.run(inventory.sweep())==1
    async def verify():
        async with AsyncSessionLocal() as db:
            a=await db.get(PhoneNumber,case['id'])
            assert a.status=='released' and not a.is_default and not a.provider_cleanup_pending
            assert a.inbound_agent_id is None and a.inbound_campaign_id is None
            assert (await db.get(Agent,case['agent'])).caller_number is None
            out=await db.get(Campaign,case['out'])
            assert out.caller_number_pool==[case['kept']] and out.status=='paused'
            inc=await db.get(Campaign,case['in'])
            assert inc.phone_number_id is None and inc.status=='paused'
            kept=await db.scalar(select(PhoneNumber).where(PhoneNumber.number==case['kept']))
            assert kept.is_default and kept.status=='active'
    asyncio.run(verify())
    numbers=client.get(f"/api/admin/orgs/{case['org']}/phone-numbers").json()['numbers']
    assert [n['number'] for n in numbers]==[case['kept']]
    assert asyncio.run(inventory.sweep())==0
    assert len([c for c in case['calls'] if c[0]=='billing'])==1


def test_inventory_outage_never_retires_numbers(case,monkeypatch):
    async def fail():raise plivo.PlivoError('temporary outage')
    monkeypatch.setattr(plivo,'inventory_numbers',fail)
    with pytest.raises(plivo.PlivoError):asyncio.run(inventory.sweep())
    assert not case['calls']


def test_missing_list_but_number_still_exists_is_retained(case,monkeypatch):
    async def exists(number):return True
    monkeypatch.setattr(plivo,'number_exists',exists)
    assert asyncio.run(inventory.sweep())==0
    assert not case['calls']


def test_cleanup_failure_is_durable_and_retried_without_releasing_again(case,monkeypatch):
    from app.services import telephony
    assert asyncio.run(inventory.sweep())==0
    age_missing(case)
    async def fail(**kw):raise RuntimeError('temporary media failure')
    monkeypatch.setattr(telephony,'_livekit_numbers',fail)
    assert asyncio.run(inventory.sweep())==1
    async def pending():
        async with AsyncSessionLocal() as db:
            a=await db.get(PhoneNumber,case['id']);assert a.status=='released' and a.provider_cleanup_pending
    asyncio.run(pending())
    async def okay(**kw):pass
    monkeypatch.setattr(telephony,'_livekit_numbers',okay)
    assert asyncio.run(inventory.sweep())==0
    assert len([c for c in case['calls'] if c[0]=='billing'])==2


def test_full_inventory_includes_non_voice_and_validates_pagination(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings,'plivo_auth_id','TEST');monkeypatch.setattr(settings,'plivo_auth_token','test')
    async def request(*args,**kw):
        if kw['params']['offset']==0:return {'objects':[{'number':'17374503908','voice_enabled':False}], 'meta':{'next':'next','total_count':2}}
        return {'objects':[{'number':'15125474695'}], 'meta':{'next':None,'total_count':2}}
    monkeypatch.setattr(plivo,'_request',request)
    assert asyncio.run(plivo.inventory_numbers())=={GONE,KEPT}


@pytest.mark.parametrize('data',[{}, {'objects':[],'meta':{}}, {'objects':[],'meta':{'next':'next'}}, {'objects':[],'meta':{'next':None,'total_count':1}}])
def test_incomplete_inventory_is_not_empty_inventory(monkeypatch,data):
    from app.config import settings
    monkeypatch.setattr(settings,'plivo_auth_id','TEST');monkeypatch.setattr(settings,'plivo_auth_token','test')
    async def request(*args,**kw):return data
    monkeypatch.setattr(plivo,'_request',request)
    with pytest.raises(plivo.PlivoError):asyncio.run(plivo.inventory_numbers())


def test_only_404_counts_as_missing_number(monkeypatch):
    async def request(*args,**kw):raise plivo.PlivoError('not found',status_code=404)
    monkeypatch.setattr(plivo,'_request',request)
    assert asyncio.run(plivo.number_exists(GONE)) is False
    async def unavailable(*args,**kw):raise plivo.PlivoError('server error',status_code=500)
    monkeypatch.setattr(plivo,'_request',unavailable)
    with pytest.raises(plivo.PlivoError):asyncio.run(plivo.number_exists(GONE))


def test_recent_purchase_is_not_retired(case):
    async def fresh():
        async with AsyncSessionLocal() as db:
            a=await db.get(PhoneNumber,case['id']);a.created_at=datetime.now(timezone.utc)
            a.provider_missing_since=datetime.now(timezone.utc)-timedelta(minutes=5)
            a.provider_check_account='TESTACCOUNT'
            await db.commit()
    asyncio.run(fresh())
    assert asyncio.run(inventory.sweep())==0
    assert not case['calls']


def test_individual_lookup_error_does_not_retire(case,monkeypatch):
    assert asyncio.run(inventory.sweep())==0
    age_missing(case)
    async def fail(number):raise plivo.PlivoError('rate limited',status_code=429)
    monkeypatch.setattr(plivo,'number_exists',fail)
    assert asyncio.run(inventory.sweep())==0
    assert not case['calls']


def test_standalone_subscription_ends_renewal_and_historical_calls_remain(case):
    from app.models.call_log import CallLog
    async def setup():
        async with AsyncSessionLocal() as db:
            a=await db.get(PhoneNumber,case['id']);a.stripe_subscription_id='test-number-subscription'
            call=CallLog(org_id=a.org_id,agent_id=case['agent'],livekit_room_name='past-'+uuid.uuid4().hex,
                         call_type='outbound',status='completed',from_phone=case['gone'],to_phone='+14155550123')
            db.add(call);await db.commit();return call.id
    key=asyncio.run(setup())
    assert asyncio.run(inventory.sweep())==0
    age_missing(case)
    assert asyncio.run(inventory.sweep())==1
    assert ('cancel','test-number-subscription',True) in case['calls']
    async def verify():
        async with AsyncSessionLocal() as db:
            assert (await db.get(CallLog,key)).from_phone==case['gone']
    asyncio.run(verify())


def test_different_project_does_not_establish_release(case):
    async def bind_other():
        async with AsyncSessionLocal() as db:
            a=await db.get(PhoneNumber,case['id']);a.provider_check_account='OTHERPROJECT'
            a.provider_missing_since=datetime.now(timezone.utc)-timedelta(minutes=10)
            await db.commit()
    asyncio.run(bind_other())
    assert asyncio.run(inventory.sweep())==0
    assert not case['calls']
