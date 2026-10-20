import asyncio
import json
import uuid
import pytest
from tests.test_radar_automations import crm
BASE='/api/radar/automations'

@pytest.fixture
def agent(crm):
    from app.database import AsyncSessionLocal
    from app.models.agent import Agent
    async def go():
        async with AsyncSessionLocal() as db:
            row=Agent(org_id=uuid.UUID(crm['org_id']),name='Maya · Multifamily Owner Opportunities')
            db.add(row);await db.commit();return str(row.id)
    return asyncio.run(go())


def test_selected_agent_overrides_invented_campaign_for_both_rules_and_persists(client,crm,agent,monkeypatch):
    from app.services import llm
    seen=[]
    async def reply(payload):
        context=json.loads(payload['messages'][1]['content']);seen.append(context)
        rules=[{'name':name,'source':{'campaign_id':'maya-not-a-campaign-id'},'condition':{'kind':'verification','value':value},'actions':[{'kind':'crm_pond','target_id':'7'}]} for name,value in [('Live confirmation','name_confirmed'),('Voicemail','named_voicemail')]]
        return {'choices':[{'message':{'content':json.dumps({'message':'Review both rules.','drafts':rules})}}]}
    monkeypatch.setattr(llm,'_chat',reply)
    body={'provider':'followupboss','message':'Use Maya for both rules','selected_source':{'agent_id':agent}}
    before=len([x for x in crm['calls'] if x[0] in ('POST','PUT')])
    response=client.post(BASE+'/draft',json=body)
    assert response.status_code==200,response.text
    result=response.json();assert len(result['drafts'])==2
    for rule in result['drafts']:
        assert rule['spec']['source']['agent_id']==agent
        assert rule['spec']['source']['campaign_id'] is None
    key=result['conversation_id']
    chat=next(c for c in client.get(BASE+'/conversations/followupboss').json()['items'] if c['id']==key)
    assert chat['selected_source']['agent_id']==agent
    assert all(set(m)=={'role','text'} for m in chat['messages'])
    response=client.post(BASE+'/draft',json={'provider':'followupboss','message':'Continue those rules','conversation_id':key})
    assert response.status_code==200,response.text
    assert seen[-1]['selected_source']['agent_id']==agent
    assert response.json()['drafts'][0]['spec']['source']['agent_id']==agent
    assert len([x for x in crm['calls'] if x[0] in ('POST','PUT')])==before


@pytest.mark.parametrize('model_source',[{'campaign_id':str(uuid.uuid4())},{'agent_id':'Maya agent'}])
def test_invalid_generated_source_requests_picker_instead_of_error(client,crm,monkeypatch,model_source):
    from app.services import llm
    async def reply(payload):
        return {'choices':[{'message':{'content':json.dumps({'drafts':[{'name':'Verify','source':model_source}]})}}]}
    monkeypatch.setattr(llm,'_chat',reply)
    r=client.post(BASE+'/draft',json={'provider':'followupboss','message':'Use Maya multifamily'})
    assert r.status_code==200,r.text
    assert r.json()['needs_source'] and not r.json()['drafts'] and not r.json()['commands']


def test_missing_selected_source_rejected_before_model_or_writes(client,crm,monkeypatch):
    from app.services import llm
    async def forbidden(*a,**kw):raise AssertionError('Do not send another workspace source to the model')
    monkeypatch.setattr(llm,'_chat',forbidden)
    before=len(crm['calls'])
    for source in [{'agent_id':str(uuid.uuid4())},{}]:
        r=client.post(BASE+'/draft',json={'provider':'followupboss','message':'Use this agent','selected_source':source})
        assert r.status_code==400,r.text
    assert len(crm['calls'])==before


def test_picker_request_does_not_prepare_unrelated_crm_write(client,crm,monkeypatch):
    from app.services import llm
    async def reply(payload):
        return {'choices':[{'message':{'content':json.dumps({'message':'Choose a source.','needs_source':True,'commands':[{'action':'create_pond','name':'Should not be proposed'}]})}}]}
    monkeypatch.setattr(llm,'_chat',reply)
    before=len(client.get(BASE+'/commands').json()['items'])
    r=client.post(BASE+'/draft',json={'provider':'followupboss','message':'Build verification rules'})
    assert r.status_code==200 and r.json()['needs_source'] and not r.json()['commands']
    assert len(client.get(BASE+'/commands').json()['items'])==before
