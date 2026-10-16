import asyncio
import json
import pytest
from tests.test_radar_automations import crm
from tests.test_crm_assistant import prepare, run

STAGES=[{'label':'verified by voicemail','kind':'active'},
        {'label':'verified contacted by AI','kind':'active'},
        {'label':'contact attempted by human','kind':'active'}]


def test_create_fub_pipeline_embeds_custom_stages_and_reads_back_ids(client,crm):
    cmd=prepare(client,'create_pipeline',name='Verified contacts',stages=STAGES)
    assert not any(method=='POST' and path=='/v1/pipelines' for method,path,_ in crm['calls'])
    result=run(client,cmd)
    assert result['status']=='succeeded', result
    pipeline=result['result']['pipeline']
    assert [s['label'] for s in pipeline['stages']]==[s['label'] for s in STAGES]
    assert all(s['id'] for s in pipeline['stages'])
    writes=[body for method,path,body in crm['calls'] if method=='POST' and path=='/v1/pipelines']
    assert writes==[{'name':'Verified contacts','stages':[
        {'name':s['label'],'closedStage':False,'orderWeight':(i+1)*10} for i,s in enumerate(STAGES)]}]
    assert not any(method=='POST' and path=='/v1/stages' for method,path,_ in crm['calls'])
    assert run(client,cmd)['status']=='succeeded'
    assert len([1 for m,p,_ in crm['calls'] if m=='POST' and p=='/v1/pipelines'])==1


def test_reusing_pipeline_appends_missing_stages_and_preserves_existing(client,crm):
    crm['pipelines'][0]['stages'][0].update(color='#123456',description='Keep this')
    cmd=prepare(client,'create_pipeline',name='Sales',stages=[{'label':'Follow-up','kind':'active'}])
    result=run(client,cmd)
    assert result['status']=='succeeded',result
    assert [s['label'] for s in result['result']['pipeline']['stages']]==['New','Follow-up']
    put=next(body for m,p,body in crm['calls'] if m=='PUT' and p=='/v1/pipelines/1')
    assert put['stages'][0]['id']==101 and put['stages'][0]['color']=='#123456'
    assert put['stages'][0]['description']=='Keep this'
    count=len([1 for m,_,_ in crm['calls'] if m in ('POST','PUT')])
    again=prepare(client,'create_pipeline',name='sales',stages=[{'label':'Follow-up'}])
    assert run(client,again)['status']=='succeeded'
    assert len([1 for m,_,_ in crm['calls'] if m in ('POST','PUT')])==count


def test_add_stages_uses_deal_pipeline_not_people_stage_endpoint(client,crm):
    cmd=prepare(client,'add_stages',pipeline_id='1',stages=[{'label':'Closed','kind':'won'}])
    result=run(client,cmd)
    assert result['status']=='succeeded',result
    assert result['result']['pipeline']['stages'][-1]['kind']=='closed'
    assert crm['pipelines'][0]['stages'][-1]['closedStage'] is True
    assert not any(p=='/v1/stages' for m,p,b in crm['calls'])


def test_different_closed_setting_is_not_silently_changed(client,crm):
    cmd=prepare(client,'add_stages',pipeline_id='1',stages=[{'label':'New','kind':'won'}])
    result=run(client,cmd)
    assert result['status']=='uncertain' and 'different open/closed' in result['error']
    assert not any(m=='PUT' for m,_,_ in crm['calls'])


def test_resource_form_accepts_fub_pipeline_stages(client,crm):
    response=client.post('/api/radar/automations/resources/followupboss',json={
        'kind':'crm_pipeline','name':'From the form','stages':STAGES})
    assert response.status_code==200,response.text
    assert len(response.json()['stages'])==3


def test_no_success_when_crm_readback_omits_requested_stage(client,crm,monkeypatch):
    from app.services.crm import fub_pipelines
    original=fub_pipelines.get_pipeline
    async def missing(http,key):
        row=await original(http,key)
        return {**row,'stages':[]}
    monkeypatch.setattr(fub_pipelines,'get_pipeline',missing)
    cmd=prepare(client,'create_pipeline',name='Missing stages',stages=STAGES)
    result=run(client,cmd)
    assert result['status']=='uncertain' and 'not confirmed all requested stages' in result['error']
    assert client.post(f"/api/radar/automations/commands/{cmd['id']}/execute",json={'confirmed':True}).status_code==400


def test_chat_history_preserves_assistant_questions_and_emits_real_proposal(client,crm,monkeypatch):
    from app.services import llm
    seen=[]
    async def fake(payload,**kwargs):
        seen.append(payload)
        return {'choices':[{'message':{'content':json.dumps({'message':'Please type yes to confirm.',
            'commands':[{'action':'create_pipeline','name':'Verified contacts','stages':STAGES}]})}}]}
    monkeypatch.setattr(llm,'_chat',fake)
    r=client.post('/api/radar/automations/draft',json={'provider':'followupboss',
        'message':'Use those three stages','history':[{'role':'user','text':'Create Verified contacts'},
          {'role':'assistant','text':'Which stages?'},{'role':'user','text':'Voicemail, AI contacted, human attempted'}]})
    assert r.status_code==200,r.text
    assert 'Please type yes' not in r.json()['message']
    context=json.loads(seen[0]['messages'][1]['content'])
    assert context['conversation'][1]=={'role':'assistant','text':'Which stages?'}
    assert r.json()['commands'][0]['spec']['stages']==STAGES
    assert not any(m=='POST' and p=='/v1/pipelines' for m,p,_ in crm['calls'])


def test_typing_yes_reopens_pending_proposal_without_llm_or_crm_write(client,crm,monkeypatch):
    from app.services import llm
    async def forbidden(*args,**kwargs):raise AssertionError('A confirmation should not regenerate the plan')
    monkeypatch.setattr(llm,'_chat',forbidden)
    cmd=prepare(client,'create_pipeline',name='Ready for review',stages=STAGES)
    before=len(crm['calls'])
    r=client.post('/api/radar/automations/draft',json={'provider':'followupboss','message':'yes, I confirm'})
    assert r.status_code==200,r.text
    assert r.json()['commands'][0]['id']==cmd['id'] and not r.json()['writes_performed']
    assert len(crm['calls'])==before


def test_confirmation_without_pending_plan_does_not_claim_execution(client,crm):
    # Use a fresh account/connection in other tenant tests; here mark house proposals attempted.
    from app.database import AsyncSessionLocal
    from app.models.crm_command import CrmCommand
    from sqlalchemy import update
    async def clear():
        async with AsyncSessionLocal() as db:
            await db.execute(update(CrmCommand).values(status='succeeded'));await db.commit()
    asyncio.run(clear())
    r=client.post('/api/radar/automations/draft',json={'provider':'followupboss','message':'yes'})
    assert r.status_code==200 and not r.json()['commands']
    assert 'no current action' in r.json()['message']


def test_live_receipt_verification_reads_existing_board_without_creating(client,crm):
    cmd=prepare(client,'create_pipeline',name='Verified contacts check',stages=STAGES)
    run(client,cmd)
    before=len([1 for m,p,_ in crm['calls'] if m in ('POST','PUT')])
    result=client.get(f"/api/radar/automations/commands/{cmd['id']}/verify")
    assert result.status_code==200,result.text
    assert result.json()['exists'] and result.json()['matches_receipt']
    assert 'Deals / Deal Tracking' in result.json()['location']
    assert len([1 for m,p,_ in crm['calls'] if m in ('POST','PUT')])==before


def test_i_dont_see_it_checks_current_crm_instead_of_generating_creation(client,crm,monkeypatch):
    from app.services import llm
    async def forbidden(*args,**kwargs):raise AssertionError('Status checks must not generate a new creation')
    monkeypatch.setattr(llm,'_chat',forbidden)
    cmd=prepare(client,'create_pipeline',name='Find my board',stages=STAGES);run(client,cmd)
    before=len([1 for m,p,_ in crm['calls'] if m in ('POST','PUT')])
    r=client.post('/api/radar/automations/draft',json={'provider':'followupboss','message':"I don't see it?"})
    assert r.status_code==200,r.text
    assert not r.json()['commands'] and r.json()['verification']['exists']
    assert 'Find my board' in r.json()['message'] and 'Deals / Deal Tracking' in r.json()['message']
    assert len([1 for m,p,_ in crm['calls'] if m in ('POST','PUT')])==before


def test_verification_reports_missing_or_changed_board_without_recreation(client,crm):
    cmd=prepare(client,'create_pipeline',name='Changed board',stages=STAGES);receipt=run(client,cmd)
    key=int(receipt['result']['pipeline']['id'])
    current=next(p for p in crm['pipelines'] if p['id']==key)
    current['name']='Renamed in CRM'
    result=client.get(f"/api/radar/automations/commands/{cmd['id']}/verify").json()
    assert result['exists'] and not result['matches_receipt']
    crm['pipelines']=[p for p in crm['pipelines'] if p['id']!=key]
    before=len([1 for m,p,_ in crm['calls'] if m in ('POST','PUT')])
    result=client.get(f"/api/radar/automations/commands/{cmd['id']}/verify").json()
    assert result['exists'] is False
    assert len([1 for m,p,_ in crm['calls'] if m in ('POST','PUT')])==before
