import json
import uuid
from datetime import timedelta
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.config import settings
from app.database import Base
from app.models.account import Organization, User
from app.models.billing import PhoneNumber
from app.models.number_registration import NumberRegistration as Job, RegistrationAuthorization as Authorization, RegistrationReceipt
from app.services import number_registration as reg
from app.services.number_registration import signalwire as sw
SID='22222222-2222-4222-8222-222222222222'
RID='33333333-3333-4333-8333-333333333333'

@pytest_asyncio.fixture
async def setup(monkeypatch, tmp_path):
    engine=create_async_engine('sqlite+aiosqlite:///'+str(tmp_path/'registration.db'))
    async with engine.begin() as c: await c.run_sync(Base.metadata.create_all)
    sessions=async_sessionmaker(engine,expire_on_commit=False,autoflush=False)
    monkeypatch.setattr(reg,'AsyncSessionLocal',sessions)
    for k,v in {'signalwire_space':'test.signalwire.com','signalwire_project_id':'project','signalwire_api_token':'key'}.items():monkeypatch.setattr(settings,k,v)
    async with sessions() as db:
        org=Organization(id=uuid.uuid4(),name='Acme Plumbing');user=User(id=uuid.uuid4(),email=str(uuid.uuid4())+'@example.com')
        db.add_all([org,user]);await db.flush()
        phone=PhoneNumber(id=uuid.uuid4(),org_id=org.id,number='+14155550123',carrier='signalwire',provider_sid=SID,status='active',source='purchased',created_at=reg.now())
        auth=Authorization(id=uuid.uuid4(),org_id=org.id,caller_name='ACME PLUMBING',legal_name='Acme Plumbing LLC',providers=['signalwire_cnam'],fees_authorized=['signalwire_cnam'],authorized_by=user.id,evidence='signed-test-consent')
        db.add_all([phone,auth]);await db.flush();await reg.enqueue_number(db,phone);await db.commit()
        job=(await db.execute(select(Job).where(Job.phone_number_id==phone.id,Job.provider=='signalwire_cnam'))).scalar_one()
        yield db,phone,auth,job
    await engine.dispose()

@pytest.fixture
def carrier(monkeypatch):
    state={'calls':[],'latest':None,'applied':None,'post_status':201,'timeout':False,'expected_name':'ACME PLUMBING'}
    def handler(req):
        state['calls'].append(req)
        assert req.headers['authorization'].startswith('Basic ')
        assert req.url.host=='test.signalwire.com'
        assert str(req.url.path).startswith('/api/relay/rest/phone_numbers/'+SID)
        if req.method=='GET' and not req.url.path.endswith('/cnam'):return httpx.Response(200,json={'id':SID,'number':'+14155550123','cnam':state['applied']})
        if req.method=='GET':return httpx.Response(200,json=state['latest']) if state['latest'] else httpx.Response(404,json={})
        if req.method=='POST':
            assert json.loads(req.content)=={'name':state['expected_name']}
            if state['post_status']==422:return httpx.Response(422,json={'errors':[{'detail':"Caller ID name isn't available for this number."}]})
            state['latest']={'id':RID,'phone_number_id':SID,'name':state['expected_name'],'status':'pending','reason':None,'required_action':None}
            if state['timeout']:raise httpx.ReadTimeout('response lost',request=req)
            return httpx.Response(state['post_status'],json=state['latest'],headers={'X-Request-ID':'http-receipt-1'})
        if req.method=='DELETE':return httpx.Response(204)
        raise AssertionError(req.method)
    original=sw.Client
    monkeypatch.setattr(reg,'Client',lambda **kw: original(transport=httpx.MockTransport(handler),**kw))
    return state

@pytest.mark.parametrize('value,want',[(' Acme   Plumbing ','ACME PLUMBING'),('Acme\nCo','ACMECO'),('a & b','A & B')])
def test_normalization(value,want):assert sw.normalize_name(value)==want

@pytest.mark.parametrize('value',['','1234567890123456','_ACME','ACME@HOME','ABC💥'])
def test_validation(value):
    with pytest.raises(ValueError):sw.normalize_name(value)

@pytest.mark.asyncio
async def test_enqueue_no_http_and_duplicates(setup,carrier):
    db,p,a,j=setup
    await reg.enqueue_number(db,p);await reg.enqueue_number(db,p);await db.commit()
    assert await db.scalar(select(func.count()).select_from(Job).where(Job.phone_number_id==p.id))==4
    assert not carrier['calls']

@pytest.mark.asyncio
async def test_pending_real_http_receipts_and_no_duplicate(setup,carrier):
    db,p,a,j=setup;await reg.process(db,j);await db.commit()
    assert j.status=='pending' and j.request_id==RID
    receipts=(await db.execute(select(RegistrationReceipt).where(RegistrationReceipt.registration_id==j.id))).scalars().all()
    posted=next(r for r in receipts if r.method=='POST')
    assert posted.request_id=='http-receipt-1' and posted.response['status']=='pending'
    await reg.process(db,j)
    assert sum(r.method=='POST' for r in carrier['calls'])==1

@pytest.mark.asyncio
async def test_applied_name_required(setup,carrier):
    db,p,a,j=setup;await reg.process(db,j);carrier['latest']['status']='approved'
    await reg.process(db,j);assert j.status=='pending'
    carrier['applied']='ACME PLUMBING';await reg.process(db,j);assert j.status=='approved'

@pytest.mark.asyncio
async def test_lost_post_response_reconciles_without_retry(setup,carrier):
    db,p,a,j=setup;carrier['timeout']=True
    with pytest.raises(sw.ProviderError):await reg.process(db,j)
    assert j.submission_intent_at
    await reg.process(db,j)
    assert j.request_id==RID and sum(r.method=='POST' for r in carrier['calls'])==1

@pytest.mark.asyncio
async def test_unknown_post_never_blind_retries(setup,carrier):
    db,p,a,j=setup;j.submission_intent_at=reg.now();j.caller_name='ACME PLUMBING';await db.commit()
    await reg.process(db,j)
    assert j.status=='verification_required' and not any(r.method=='POST' for r in carrier['calls'])

@pytest.mark.asyncio
async def test_consent_and_fee_gates(setup,carrier):
    db,p,a,j=setup;a.revoked_at=reg.now();await db.commit();await reg.process(db,j)
    assert j.prerequisite=='customer_registration_authorization_required' and not carrier['calls']
    a.revoked_at=None;a.fees_authorized=[];await db.commit();await reg.process(db,j)
    assert j.prerequisite=='carrier_fee_authorization_required' and not carrier['calls']

@pytest.mark.asyncio
async def test_cleanup_confirmation(setup,carrier):
    db,p,a,j=setup;await reg.process(db,j)
    carrier['latest']['status']='approved';carrier['applied']='ACME PLUMBING'
    p.status='released';await reg.retire_number(db,p);await db.commit();await db.refresh(j)
    await reg.process(db,j);assert j.status=='pending' and j.phase=='remove'
    carrier['applied']=None;await reg.process(db,j)
    assert j.status=='removed' and sum(r.method=='DELETE' for r in carrier['calls'])==1

@pytest.mark.asyncio
async def test_unsupported(setup,carrier):
    db,p,a,j=setup;carrier['post_status']=422
    with pytest.raises(sw.ProviderError,match='unsupported_number'):await reg.process(db,j)
    assert j.status!='approved'

@pytest.mark.asyncio
async def test_rejected(setup,carrier):
    db,p,a,j=setup;await reg.process(db,j);carrier['latest'].update(status='rejected',required_action='Provide documentation')
    await reg.process(db,j);assert j.status=='rejected' and j.prerequisite=='Provide documentation'

@pytest.mark.asyncio
async def test_claim_and_crash_recovery(setup):
    db,p,a,j=setup
    await db.execute(reg.update(Job).where(Job.id!=j.id).values(next_at=reg.now()+timedelta(days=1)));await db.commit()
    first=await reg.claim(db);assert first[0]==j.id and await reg.claim(db) is None
    await db.refresh(j);j.lease_until=reg.now()-timedelta(seconds=1);await db.commit()
    second=await reg.claim(db);assert second[0]==j.id and second[1]!=first[1]

@pytest.mark.asyncio
async def test_no_partner_or_attestation_simulation(setup,carrier):
    db,p,a,j=setup;a.providers=['signalwire_cnam','hiya','first_orion'];await db.commit()
    for provider in ['hiya','first_orion','signalwire_attestation']:
        job=(await db.execute(select(Job).where(Job.phone_number_id==p.id,Job.provider==provider))).scalar_one()
        await reg.process(db,job);assert job.status=='verification_required' and not job.request_id
    assert not carrier['calls']


def test_authorization_api(client):
    body={'legal_name':'Acme Plumbing LLC','caller_name':'Acme Plumbing','providers':['signalwire_cnam'],'fees_authorized':['signalwire_cnam'],'registration_authorized':True,'evidence':'signed terms record test-123'}
    first=client.post('/api/phone-numbers/registration/authorization',json=body)
    assert first.status_code==200,first.text
    assert client.post('/api/phone-numbers/registration/authorization',json=body).json()['id']==first.json()['id']
    assert first.json()['caller_name']=='ACME PLUMBING'
    for extra in [{'registration_authorized':False},{'caller_name':'THIS IS FAR TOO LONG'}]:
        assert client.post('/api/phone-numbers/registration/authorization',json={**body,**extra}).status_code==422
    assert client.delete('/api/phone-numbers/registration/authorization').status_code==200

@pytest.mark.asyncio
async def test_reassignment_blocks_new_identity_until_old_removed(setup,carrier):
    db,p,a,j=setup;await reg.process(db,j)
    other=Organization(id=uuid.uuid4(),name='New Owner');db.add(other);await db.flush()
    await reg.retire_number(db,p)
    p.org_id=other.id;p.created_at=reg.now()
    new_auth=Authorization(org_id=other.id,legal_name='New Owner',caller_name='NEW OWNER',
        providers=['signalwire_cnam'],fees_authorized=['signalwire_cnam'],authorized_by=a.authorized_by,evidence='new signed consent')
    db.add(new_auth);await db.flush();await reg.enqueue_number(db,p);await db.commit()
    new_job=(await db.execute(select(Job).where(Job.org_id==other.id,Job.provider=='signalwire_cnam'))).scalar_one()
    await reg.process(db,new_job)
    assert new_job.status=='queued' and new_job.prerequisite=='previous_assignment_cleanup_pending'
    assert sum(r.method=='POST' for r in carrier['calls'])==1

@pytest.mark.asyncio
async def test_revocation_reconciles_existing_cnam(setup,carrier):
    db,p,a,j=setup;await reg.process(db,j);a.revoked_at=reg.now();await db.commit()
    await reg.process(db,j)
    assert j.phase=='remove' and any(r.method=='DELETE' for r in carrier['calls'])

@pytest.mark.asyncio
async def test_cleanup_does_not_clear_external_change(setup,carrier):
    db,p,a,j=setup;await reg.process(db,j);p.status='released';await reg.retire_number(db,p);await db.commit();await db.refresh(j)
    carrier['latest']['id']=str(uuid.uuid4());carrier['latest']['name']='OTHER BUSINESS';carrier['applied']='OTHER BUSINESS'
    with pytest.raises(sw.ProviderError,match='cleanup_conflict'):await reg.process(db,j)
    assert not any(r.method=='DELETE' for r in carrier['calls'])

@pytest.mark.asyncio
async def test_receipt_must_belong_to_correct_number(setup,carrier):
    db,p,a,j=setup
    carrier['latest']={'id':RID,'phone_number_id':str(uuid.uuid4()),'name':'ACME PLUMBING','status':'approved'}
    with pytest.raises(sw.ProviderError,match='invalid_cnam_receipt'):await reg.process(db,j)
    assert j.status!='approved'

@pytest.mark.asyncio
async def test_stale_lease_cannot_finalize_receipt(setup):
    db,p,a,j=setup;j.lease_token='old';j.lease_until=reg.now()-timedelta(seconds=1);await db.commit()
    with pytest.raises(sw.ProviderError,match='lease_lost'):
        await reg._receipt(db,j,'GET','/cnam',200,{'status':'approved'},RID)
    assert not await db.scalar(select(func.count()).select_from(RegistrationReceipt))

@pytest.mark.asyncio
async def test_parallel_claims_single_job(setup):
    import asyncio
    db,p,a,j=setup
    await db.execute(reg.update(Job).where(Job.id!=j.id).values(next_at=reg.now()+timedelta(days=1)));await db.commit()
    async def claim():
        async with reg.AsyncSessionLocal() as other:return await reg.claim(other)
    results=await asyncio.gather(claim(),claim())
    assert len([r for r in results if r])==1

@pytest.mark.asyncio
async def test_worker_maps_provider_error_and_keeps_receipts(setup,carrier):
    db,p,a,j=setup;carrier['post_status']=422
    await db.execute(reg.update(Job).where(Job.id!=j.id).values(next_at=reg.now()+timedelta(days=1)));await db.commit()
    assert await reg.run_one()
    await db.refresh(j)
    assert j.status=='unsupported' and j.lease_token is None
    assert await db.scalar(select(func.count()).select_from(RegistrationReceipt).where(RegistrationReceipt.registration_id==j.id))>=3

@pytest.mark.asyncio
async def test_assignment_enqueue_rolls_back_with_number_transaction(setup):
    db,p,a,j=setup
    p.created_at=reg.now()+timedelta(seconds=1);await reg.enqueue_number(db,p);await db.rollback()
    assert await db.scalar(select(func.count()).select_from(Job))==4

@pytest.mark.asyncio
async def test_cnam_registration_is_separate_from_attestation(setup,carrier):
    db,p,a,j=setup;await reg.process(db,j)
    carrier['latest']['status']='approved';carrier['applied']='ACME PLUMBING'
    await reg.process(db,j);await db.commit()
    summary=(await reg.summaries(db,[p]))[p.id]
    assert summary['status']=='Caller ID Registered'
    assert summary['attestation']['level']=='unknown'
    assert summary['attestation']['status']=='action_required'

@pytest.mark.asyncio
async def test_migration_replay_preserves_existing_receipt(setup,carrier):
    db,p,a,j=setup;await reg.process(db,j);await db.commit()
    async with db.bind.begin() as connection:await connection.run_sync(Base.metadata.create_all)
    assert await db.scalar(select(func.count()).select_from(RegistrationReceipt).where(RegistrationReceipt.registration_id==j.id))==3

@pytest.mark.asyncio
async def test_missing_runtime_credentials_do_not_create_remote_success(setup,carrier,monkeypatch):
    db,p,a,j=setup;monkeypatch.setattr(settings,'signalwire_api_token','')
    with pytest.raises(sw.ProviderError,match='credentials_required'):await reg.process(db,j)
    assert j.status!='approved' and not carrier['calls']

@pytest.mark.asyncio
async def test_changed_authorized_name_clears_previous_before_submission(setup,carrier):
    db,p,a,j=setup;await reg.process(db,j)
    carrier['latest']['status']='approved';carrier['applied']='ACME PLUMBING'
    await reg.process(db,j);await db.commit()
    a.revoked_at=reg.now()
    replacement=Authorization(org_id=p.org_id,legal_name='Acme Home LLC',caller_name='ACME HOME',
        providers=['signalwire_cnam'],fees_authorized=['signalwire_cnam'],authorized_by=a.authorized_by,evidence='new approved short name')
    db.add(replacement);await db.commit()
    await reg.process(db,j)
    assert j.phase=='remove' and j.status=='pending'
    carrier['applied']=None
    await reg.process(db,j)
    assert j.phase=='register' and j.status=='queued'
    carrier['expected_name']='ACME HOME'
    await reg.process(db,j)
    assert j.status=='pending' and j.caller_name=='ACME HOME'
    methods=[r.method for r in carrier['calls']]
    assert methods.count('POST')==2 and methods.index('DELETE')>methods.index('POST')

@pytest.mark.asyncio
async def test_purchase_commits_outbox_without_waiting_for_cnam(setup,carrier,monkeypatch):
    from sqlalchemy import delete
    from app.services import telephony, signalwire
    db,p,a,j=setup;org_id=p.org_id
    await db.execute(delete(Job));await db.delete(p);await db.commit()
    monkeypatch.setattr(settings,'signalwire_sip_outbound_trunk_id','ST_test')
    async def buy(number):return {'sid':SID,'number':number}
    async def allow(number):pass
    monkeypatch.setattr(signalwire,'buy',buy);monkeypatch.setattr(signalwire,'allow_number',allow)
    purchased=await telephony.purchase(db,org_id,'+14155550123',carrier='signalwire')
    assert purchased.provider_sid==SID and not carrier['calls']
    job=(await db.execute(select(Job).where(Job.phone_number_id==purchased.id,Job.provider=='signalwire_cnam'))).scalar_one()
    assert job.status=='queued'
    await reg.process(db,job)
    assert job.request_id==RID and job.status=='pending'


def test_carrier_order_tracking_never_claims_level_a(client):
    org_id=client.get('/api/auth/me').json()['org']['id']
    r=client.put(f'/api/phone-numbers/registration/admin/carrier-orders/{org_id}',json={
        'order_reference':'test-manually-submitted-order','evidence':'carrier confirmation reference for test'})
    assert r.status_code==200,r.text
    assert r.json()['business_verification_status']=='submitted'
    assert r.json()['attestation_level']=='unknown'
    assert client.get('/api/phone-numbers/registration/admin/carrier-actions').status_code==200


@pytest.mark.asyncio
async def test_reassigned_number_summary_does_not_leak_old_tenant_receipt(setup,carrier):
    db,p,a,j=setup;await reg.process(db,j)
    other=Organization(id=uuid.uuid4(),name='New Tenant');db.add(other);await db.flush()
    p.org_id=other.id;p.created_at=reg.now();await db.flush();await reg.enqueue_number(db,p);await db.commit()
    summary=(await reg.summaries(db,[p]))[p.id]
    assert all(item['request_id'] != RID for item in summary['providers'])
    assert len(summary['providers'])==4

@pytest.mark.asyncio
@pytest.mark.parametrize('http_status',[429,500])
async def test_temporary_http_errors_schedule_safe_retry(setup,carrier,http_status):
    db,p,a,j=setup;carrier['post_status']=http_status
    await db.execute(reg.update(Job).where(Job.id!=j.id).values(next_at=reg.now()+timedelta(days=1)));await db.commit()
    await reg.run_one();await db.refresh(j)
    assert j.status=='retry' and j.attempts==1 and j.submission_intent_at
    assert sum(r.method=='POST' for r in carrier['calls'])==1


def test_account_delete_waits_for_cleanup_receipt(client):
    import asyncio
    from app.database import AsyncSessionLocal
    from tests.test_accounts import _new_account
    org,_=_new_account(client,name='Pending Caller Identity Cleanup')
    async def seed():
        async with AsyncSessionLocal() as db:
            phone=PhoneNumber(org_id=uuid.UUID(org['id']),number='+14155550992',carrier='signalwire',
                provider_sid=SID,status='released',source='purchased',created_at=reg.now())
            db.add(phone);await db.flush()
            db.add(Job(phone_number_id=phone.id,org_id=phone.org_id,assignment_key=reg.assignment_key(phone),
                number=phone.number,carrier='signalwire',carrier_number_id=SID,provider='signalwire_cnam',
                phase='remove',status='pending',request_id=RID,caller_name='ACME PLUMBING'))
            await db.commit()
    asyncio.run(seed())
    r=client.request('DELETE',f"/api/admin/orgs/{org['id']}",json={'confirm_name':org['name']})
    assert r.status_code==409 and 'cleanup' in r.json()['detail'].lower()

@pytest.mark.asyncio
async def test_known_rejection_does_not_block_release_cleanup(setup,carrier):
    db,p,a,j=setup;carrier['post_status']=422
    with pytest.raises(sw.ProviderError):await reg.process(db,j)
    assert j.submission_intent_at is None
    p.status='released';await reg.retire_number(db,p);await db.commit();await db.refresh(j)
    await reg.process(db,j)
    assert j.status=='removed'
