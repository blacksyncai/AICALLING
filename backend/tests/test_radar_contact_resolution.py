import asyncio
import json
import uuid
import httpx
import pytest
from tests.test_radar_automations import crm,add_call,rule_body,saved,execute_all
BASE='/api/radar/automations'


@pytest.fixture
def remote(client,crm,monkeypatch):
    from app.services.crm.http import BaseHttp
    assert client.patch('/api/integrations/crm/followupboss',json={'create_contacts':False,'log_calls':True}).status_code==200
    previous=BaseHttp.client_factory
    state={'people':[], 'deals':[], 'calls':[], 'lose_response':False}
    async def handle(req):
        path,method=req.url.path,req.method
        body=json.loads(req.content) if req.content else {}
        if path.startswith('/v1/people') or path.startswith('/v1/deals'):
            state['calls'].append((method,path,body,dict(req.url.params)))
            if path=='/v1/people' and method=='GET':
                def match(p):
                    phone=req.url.params.get('phone');email=req.url.params.get('email')
                    return (phone and any(x['value']==phone for x in p.get('phones',[]))) or (email and any(x['value'].lower()==email.lower() for x in p.get('emails',[])))
                return httpx.Response(200,json={'people':[p for p in state['people'] if match(p)]})
            if path=='/v1/people' and method=='POST':
                assert req.url.params['deduplicate']=='true'
                person={'id':200+len(state['people']),'name':body.get('firstName','')+' '+body.get('lastName',''),'stage':'Lead','tags':[],**body}
                state['people'].append(person)
                if state['lose_response']:raise httpx.ReadTimeout('Response lost',request=req)
                return httpx.Response(201,json=person)
            if path.startswith('/v1/people/'):
                person=next((p for p in state['people'] if str(p['id'])==path.rsplit('/',1)[-1]),None)
                if person and method=='PUT':person.update(body)
                return httpx.Response(200 if person else 404,json=person or {'message':'Unknown person'})
            if path=='/v1/deals' and method=='GET':
                return httpx.Response(200,json={'deals':[d for d in state['deals'] if int(req.url.params['personId']) in d['peopleIds']]})
            if path=='/v1/deals' and method=='POST':
                deal={'id':300+len(state['deals']),'pipelineId':1,'status':'Active',**body};state['deals'].append(deal);return httpx.Response(201,json=deal)
            if path.startswith('/v1/deals/'):
                deal=next(d for d in state['deals'] if str(d['id'])==path.rsplit('/',1)[-1])
                if method=='PUT':deal.update(body)
                return httpx.Response(200,json=deal)
        async with previous() as client:
            return await client.request(method,str(req.url),content=req.content,headers=req.headers)
    monkeypatch.setattr(BaseHttp,'client_factory',staticmethod(lambda:httpx.AsyncClient(transport=httpx.MockTransport(handle))))
    yield state
    client.patch('/api/integrations/crm/followupboss',json={'create_contacts':False,'log_calls':True})


def unlink(lead_id,email=''):
    from app.database import AsyncSessionLocal
    from app.models.lead import Lead
    async def go():
        async with AsyncSessionLocal() as db:
            lead=await db.get(Lead,uuid.UUID(lead_id));lead.crm_refs={};lead.email=email;await db.commit()
    asyncio.run(go())


def linked(lead_id):
    from app.database import AsyncSessionLocal
    from app.models.lead import Lead
    async def go():
        async with AsyncSessionLocal() as db:return (await db.get(Lead,uuid.UUID(lead_id))).crm_refs
    return asyncio.run(go())


def queue(client,crm,email=''):
    call,lead=add_call(crm);unlink(lead,email)
    body=rule_body(target='101',kind='crm_deal_stage');body['spec']['actions'][0]['pipeline_id']='1'
    rule=saved(client,body)
    assert client.patch(f"{BASE}/{rule['id']}/state",json={'status':'active'}).status_code==200
    assert client.post(f"{BASE}/{rule['id']}/run",json={'call_ids':[call]}).json()['queued']==1
    return call,lead,rule


def job(client,call):return next(j for j in client.get(BASE+'/activity').json()['items'] if j['call_id']==call)
def person(key=91,phone='+14155550123',email=''):return {'id':key,'name':'Existing Gabe','phones':[{'value':phone}],'emails':[{'value':email}] if email else [],'stage':'Lead','tags':[],'source':'Original referral'}


def test_existing_person_is_linked_and_routed_even_when_creation_off(client,crm,remote):
    remote['people']=[person()]
    call,lead,_=queue(client,crm)
    execute_all();row=job(client,call)
    assert row['status']=='succeeded',row
    assert linked(lead)['followupboss']=='91'
    assert row['result']['contact']['status']=='linked_existing'
    assert remote['deals'][0]['peopleIds']==[91]
    assert not any(m=='POST' and p=='/v1/people' for m,p,b,q in remote['calls'])
    assert remote['people'][0]['source']=='Original referral'


def test_missing_person_created_then_linked_and_deal_created(client,crm,remote):
    assert client.patch('/api/integrations/crm/followupboss',json={'create_contacts':True,'log_calls':False}).status_code==200
    call,lead,_=queue(client,crm)
    execute_all();row=job(client,call)
    assert row['status']=='succeeded',row
    assert linked(lead)['followupboss']=='200'
    assert row['result']['contact']['id']=='200'
    assert row['result']['contact']['status']=='created_or_deduplicated'
    assert remote['people'][0]['source']=='BlackSync AI'
    assert remote['deals'][0]['peopleIds']==[200]
    assert next(q for m,p,b,q in remote['calls'] if m=='POST' and p=='/v1/people')['deduplicate']=='true'
    execute_all()
    assert len(remote['people'])==len(remote['deals'])==1


def test_creation_off_blocks_without_creating_then_setting_allows_retry(client,crm,remote):
    call,lead,_=queue(client,crm)
    execute_all();row=job(client,call)
    assert row['status']=='failed' and 'Enable' in row['error'],row
    assert not remote['people'] and not remote['deals']
    client.patch('/api/integrations/crm/followupboss',json={'create_contacts':True})
    assert client.post(f"{BASE}/activity/{row['id']}/retry").status_code==200
    execute_all();assert job(client,call)['status']=='succeeded'
    assert linked(lead)['followupboss']=='200'


def test_ambiguous_or_conflicting_matches_never_create_or_route(client,crm,remote):
    remote['people']=[person(),person(92)]
    call,lead,_=queue(client,crm)
    execute_all();row=job(client,call)
    assert row['status']=='failed' and 'Multiple' in row['error'],row
    assert not linked(lead) and not remote['deals']
    assert not any(m=='POST' for m,p,b,q in remote['calls'])


def test_phone_and_email_matching_different_people_stop_for_review(client,crm,remote):
    remote['people']=[person(),person(92,phone='+14155550999',email='gabe@example.test')]
    call,lead,_=queue(client,crm,email='gabe@example.test')
    execute_all();row=job(client,call)
    assert row['status']=='failed' and 'different' in row['error'],row
    assert not linked(lead) and not remote['deals']


def test_lost_creation_response_reconciles_without_second_post(client,crm,remote):
    client.patch('/api/integrations/crm/followupboss',json={'create_contacts':True})
    remote['lose_response']=True
    call,lead,_=queue(client,crm)
    execute_all();row=job(client,call)
    assert row['status']=='failed' and 'pending_contact' in row['result'],row
    assert len(remote['people'])==1 and not remote['deals']
    remote['lose_response']=False
    client.post(f"{BASE}/activity/{row['id']}/retry")
    execute_all();row=job(client,call)
    assert row['status']=='succeeded',row
    assert len([1 for m,p,b,q in remote['calls'] if m=='POST' and p=='/v1/people'])==1
    assert len(remote['deals'])==1 and linked(lead)['followupboss']=='200'


def test_legacy_not_linked_failure_marker_can_resume_without_duplicate_deal(client,crm,remote):
    from app.database import AsyncSessionLocal
    from app.models.radar_automation import RadarExecution
    from app.services.crm.radar_contacts import LEGACY_UNLINKED
    remote['people']=[person()]
    call,lead,_=queue(client,crm);row=job(client,call)
    async def legacy():
        async with AsyncSessionLocal() as db:
            item=await db.get(RadarExecution,uuid.UUID(row['id']));item.status='failed';item.error=LEGACY_UNLINKED;item.result={'pending_deal':0};await db.commit()
    asyncio.run(legacy())
    client.post(f"{BASE}/activity/{row['id']}/retry")
    execute_all();assert job(client,call)['status']=='succeeded'
    assert len(remote['deals'])==1


def test_uncertain_creation_without_visible_match_never_posts_again(client,crm,remote):
    client.patch('/api/integrations/crm/followupboss',json={'create_contacts':True})
    remote['lose_response']=True
    call,lead,_=queue(client,crm);execute_all();row=job(client,call)
    remote['people']=[];remote['lose_response']=False
    client.post(f"{BASE}/activity/{row['id']}/retry")
    execute_all();row=job(client,call)
    assert row['status']=='failed' and 'previous contact creation' in row['error'],row
    assert len([1 for m,p,b,q in remote['calls'] if m=='POST' and p=='/v1/people'])==1
    assert not remote['deals']


@pytest.mark.parametrize('change',[{'stage':'Trash'},{'tags':['Do Not Call']}])
def test_suppressed_fub_match_is_not_linked_or_routed(client,crm,remote,change):
    remote['people']=[{**person(),**change}]
    client.patch('/api/integrations/crm/followupboss',json={'create_contacts':True})
    call,lead,_=queue(client,crm);execute_all();row=job(client,call)
    assert row['status']=='failed' and 'suppressed' in row['error'],row
    assert not linked(lead) and not remote['deals']
    assert not any(m=='POST' for m,p,b,q in remote['calls'])


def test_preview_reports_policy_without_finding_or_creating_contacts(client,crm,remote):
    call,lead=add_call(crm);unlink(lead)
    body=rule_body(target='101',kind='crm_deal_stage');body['spec']['actions'][0]['pipeline_id']='1'
    before=len(remote['calls'])
    response=client.post(BASE+'/preview',json=body)
    assert response.status_code==200,response.text
    preview=response.json()
    assert preview['contact_resolution'] and not preview['create_missing_contacts']
    assert not next(i for i in preview['items'] if i['call_id']==call)['contact_linked']
    assert len(remote['calls'])==before and not linked(lead)


def test_csv_contact_can_complete_find_create_link_deal_flow(client,crm,remote):
    from datetime import datetime,timedelta,timezone
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.lead import Lead
    from app.models.call_log import CallLog
    from tests.test_radar_automations import turns
    client.patch('/api/integrations/crm/followupboss',json={'create_contacts':True})
    response=client.post('/api/contacts/import',json={'csv':'name,phone\nGabe Test,+14155550777'})
    assert response.status_code==201,response.text
    assert response.json()['created']==1
    async def completed_phone_call():
        async with AsyncSessionLocal() as db:
            lead=await db.scalar(select(Lead).where(Lead.org_id==uuid.UUID(crm['org_id']),Lead.phone=='+14155550777'))
            lead.crm_refs={'close':'preserve-this-link'}
            call=CallLog(org_id=lead.org_id,lead_id=lead.id,call_type='outbound',to_phone=lead.phone,
                         livekit_room_name='csv-test-'+uuid.uuid4().hex,status='completed',outcome='completed',
                         started_at=datetime.now(timezone.utc)-timedelta(minutes=5),ended_at=datetime.now(timezone.utc)-timedelta(minutes=3),
                         transcript=turns(),summary='Test verification call')
            db.add(call);await db.commit();return str(call.id),str(lead.id)
    call,lead=asyncio.run(completed_phone_call())
    body=rule_body(target='101',kind='crm_deal_stage');body['spec']['actions'][0]['pipeline_id']='1'
    rule=saved(client,body)
    preview=client.post(BASE+'/preview',json=body).json()
    assert next(i for i in preview['items'] if i['call_id']==call)['matches']
    assert not remote['people'] and not remote['deals']
    client.patch(f"{BASE}/{rule['id']}/state",json={'status':'active'})
    assert client.post(f"{BASE}/{rule['id']}/run",json={'call_ids':[call]}).json()['queued']==1
    execute_all();row=job(client,call)
    assert row['status']=='succeeded',row
    assert linked(lead)=={'close':'preserve-this-link','followupboss':'200'}
    assert remote['deals'][0]['peopleIds']==[200]
    assert client.post(f"{BASE}/{rule['id']}/run",json={'call_ids':[call]}).json()['queued']==0
    assert len(remote['people'])==len(remote['deals'])==1
