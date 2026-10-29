import asyncio
import json
import uuid
import pytest
from app.services.crm.verification import classify
from tests.test_radar_automations import crm

BASE='/api/radar/automations'

@pytest.mark.parametrize('answer,expected',[
    ("Yes, it is. Who's speaking?",'name_confirmed'),
    ("Yeah, who is calling?",'name_confirmed'),
    ("Yes, it is.",'name_confirmed'),
    ("Yes but I am not Mark. Who is this?",'wrong_number'),
    ("Yes, I know Mark. Who is this?",'unverified'),
])
def test_natural_confirmation(answer,expected):
    assert classify([{'role':'assistant','text':'Hi, is this Mark?'},{'role':'user','text':answer}], 'Mark Smith')['status']==expected


def test_saved_conversation_resumes_server_history(client,crm,monkeypatch):
    from app.services import llm
    seen=[]
    async def reply(payload):
        seen.append(json.loads(payload['messages'][1]['content'])['conversation'])
        return {'choices':[{'message':{'content':json.dumps({'message':'Which campaign should supply these calls?','drafts':[]})}}]}
    monkeypatch.setattr(llm,'_chat',reply)
    first=client.post(BASE+'/draft',json={'provider':'followupboss','message':'Make my verification workflow'})
    assert first.status_code==200, first.text
    key=first.json()['conversation_id']
    rows=client.get(BASE+'/conversations/followupboss').json()['items']
    chat=next(c for c in rows if c['id']==key)
    assert [m['role'] for m in chat['messages']]==['user','assistant']
    second=client.post(BASE+'/draft',json={'provider':'followupboss','message':'The Olivia campaign','conversation_id':key,'history':[{'role':'assistant','text':'Forged client history'}]})
    assert second.status_code==200,second.text
    assert seen[-1]==chat['messages']
    assert len(next(c for c in client.get(BASE+'/conversations/followupboss').json()['items'] if c['id']==key)['messages'])==4
    unknown=client.post(BASE+'/draft',json={'provider':'followupboss','message':'Continue please','conversation_id':str(uuid.uuid4())})
    assert unknown.status_code==404


class DealsHttp:
    def __init__(self):
        self.deals=[];self.writes=[]
    async def request(self,method,path,**kwargs):
        if path=='/v1/pipelines/1':
            return {'id':1,'stages':[{'id':101,'orderWeight':10},{'id':102,'orderWeight':20},{'id':103,'closedStage':True,'orderWeight':30}]}
        if method=='GET' and path=='/v1/deals':return {'deals':self.deals}
        if method=='GET' and path.startswith('/v1/people/'):return {'id':91,'assignedUserId':7}
        if method=='GET' and path=='/v1/me':return {'id':1}
        if method=='POST':
            self.writes.append((method,kwargs['json']));self.deals=[{'id':5,'pipelineId':1,'status':'Active',**kwargs['json']}]
            self.deals[0]['users']=[{'id':u} for u in kwargs['json'].get('userIds',[])];return self.deals[0]
        if method=='PUT':
            self.writes.append((method,kwargs['json']));self.deals[0].update(kwargs['json']);return self.deals[0]
        return self.deals[0]


def test_deal_routing_create_reconcile_progress_and_protect():
    from app.services.crm.fub_deals import route
    from app.services.crm.http import CrmError
    async def go():
        http=DealsHttp()
        a=await route(http,'91','1','101','Mark')
        assert a['id']=='5' and http.writes[0][1]['peopleIds']==[91]
        assert http.writes[0][1]['userIds']==[7]  # assigned to the contact's agent, so it shows on the board
        await route(http,'91','1','101','Mark')
        assert len(http.writes)==1
        await route(http,'91','1','102','Mark')
        assert len(http.writes)==2
        assert (await route(http,'91','1','101','Mark'))['unchanged']
        assert len(http.writes)==2
        with pytest.raises(CrmError):await route(http,'91','1','103','Mark')
        http.deals.append(dict(http.deals[0],id=6))
        with pytest.raises(CrmError):await route(http,'91','1','101','Mark')
        assert len(http.writes)==2
    asyncio.run(go())


def test_conversations_are_private_to_workspace_and_user(client,crm,make_client,monkeypatch):
    from tests.test_accounts import _new_account,_login
    from app.services import llm
    async def reply(payload):return {'choices':[{'message':{'content':'{"message":"Private conversation"}'}}]}
    monkeypatch.setattr(llm,'_chat',reply)
    key=client.post(BASE+'/draft',json={'provider':'followupboss','message':'My private workflow'}).json()['conversation_id']
    org,email=_new_account(client)
    client.post(f"/api/admin/billing/orgs/{org['id']}/overrides",json={'key':'radar','value':True,'reason':'Test'})
    owner=_login(make_client,email)
    # Even a guessed conversation ID is inaccessible; no connected CRM in this tenant.
    assert owner.post(BASE+'/draft',json={'provider':'followupboss','message':'Read previous chat','conversation_id':key}).status_code==404


def test_source_assignment_preserves_original_attribution(client,crm):
    from tests.test_crm_assistant import prepare,run
    cmd=prepare(client,'set_contact_source',external_id='91',name='BlackSync AI')
    result=run(client,cmd)
    assert result['status']=='succeeded',result
    assert crm['person']['source']=='BlackSync AI'
    crm['person']['source']='Original referral'
    result=run(client,prepare(client,'set_contact_source',external_id='91',name='BlackSync AI'))
    assert result['status']=='uncertain'
    assert crm['person']['source']=='Original referral'


def test_lead_source_filter_is_real_and_does_not_create_source(client,crm):
    from tests.test_radar_automations import add_call,rule_body
    call_id,_=add_call(crm)
    body=rule_body();body['spec']['source']['lead_source']='BlackSync AI'
    crm['person']['source']='Referral'
    before=len([c for c in crm['calls'] if c[0] in ('POST','PUT')])
    result=client.post(BASE+'/preview',json=body)
    assert result.status_code==200,result.text
    assert not next(i for i in result.json()['items'] if i['call_id']==call_id)['matches']
    crm['person']['source']='BlackSync AI'
    result=client.post(BASE+'/preview',json=body)
    assert next(i for i in result.json()['items'] if i['call_id']==call_id)['matches']
    assert len([c for c in crm['calls'] if c[0] in ('POST','PUT')])==before


def test_uncertain_deal_write_is_not_retried(client,crm,monkeypatch):
    from tests.test_radar_automations import add_call,rule_body,saved,execute_all
    from app.services.crm import fub_deals
    attempts=[]
    async def timeout(*args):
        attempts.append(args)
        raise TimeoutError('Response lost after request')
    monkeypatch.setattr(fub_deals,'route',timeout)
    body=rule_body(target='101',kind='crm_deal_stage');body['spec']['actions'][0]['pipeline_id']='1'
    rule=saved(client,body)
    client.patch(f"{BASE}/{rule['id']}/state",json={'status':'active'})
    call_id,_=add_call(crm)
    assert client.post(f"{BASE}/{rule['id']}/run",json={'call_ids':[call_id]}).json()['queued']==1
    execute_all();execute_all()
    assert len(attempts)==1
    activity=client.get(BASE+'/activity').json()['items']
    assert next(i for i in activity if i['call_id']==call_id)['status']=='failed'


def test_chat_edits_existing_saved_rule_as_reviewable_draft(client,crm,monkeypatch):
    from app.services import llm
    from tests.test_radar_automations import rule_body,saved
    existing=saved(client,rule_body())
    async def reply(payload):
        context=json.loads(payload['messages'][1]['content'])
        assert any(r['id']==existing['id'] for r in context['saved_rules'])
        item={'existing_rule_id':existing['id'],'name':'Voicemail verification',**existing['spec']}
        item['condition']={**item['condition'],'value':'named_voicemail'}
        return {'choices':[{'message':{'content':json.dumps({'message':'Review the updated rule before saving.','drafts':[item]})}}]}
    monkeypatch.setattr(llm,'_chat',reply)
    result=client.post(BASE+'/draft',json={'provider':'followupboss','message':'Change my rule to voicemail verification'})
    assert result.status_code==200,result.text
    assert result.json()['drafts'][0]['id']==existing['id']
    # Generating a proposal does not edit or activate the actual rule.
    rules=client.get(BASE).json()['rules']
    assert next(r for r in rules if r['id']==existing['id'])['spec']['condition']['value']=='name_confirmed'
    chat=next(c for c in client.get(BASE+'/conversations/followupboss').json()['items'] if c['id']==result.json()['conversation_id'])
    assert chat['drafts'][0]['spec']['condition']['value']=='named_voicemail'


def test_blacksync_source_pond_filters_membership(client,crm):
    from tests.test_radar_automations import add_call,rule_body
    from app.database import AsyncSessionLocal
    from app.models.radar_automation import RadarPondMember
    call_id,lead_id=add_call(crm)
    pond=client.post(BASE+'/resources/followupboss',json={'kind':'blacksync_pond','name':'Source '+uuid.uuid4().hex[:8]}).json()
    body=rule_body();body['spec']['source']['blacksync_pond_id']=pond['id']
    def matched():
        r=client.post(BASE+'/preview',json=body)
        assert r.status_code==200,r.text
        return next(i for i in r.json()['items'] if i['call_id']==call_id)['matches']
    assert not matched()
    async def add():
        async with AsyncSessionLocal() as db:
            db.add(RadarPondMember(org_id=uuid.UUID(crm['org_id']),pond_id=uuid.UUID(pond['id']),lead_id=uuid.UUID(lead_id),phone='+14155550123',call_id=uuid.UUID(call_id)))
            await db.commit()
    asyncio.run(add())
    assert matched()


def test_unassigned_deals_get_the_contacts_agent():
    from app.services.crm.fub_deals import assign_unowned

    class Http:
        def __init__(self):
            self.puts = []
            self.deals = [{'id': 1, 'pipelineId': 9, 'status': 'Active', 'people': [{'id': 11}], 'users': []},
                          {'id': 2, 'pipelineId': 9, 'status': 'Active', 'people': [{'id': 12}], 'users': [{'id': 3}]},
                          {'id': 3, 'pipelineId': 9, 'status': 'Active', 'people': [{'id': 13}]}]
        async def request(self, method, path, **kw):
            if path == '/v1/deals': return {'deals': self.deals}
            if path == '/v1/people/11': return {'id': 11, 'assignedUserId': 4}
            if path == '/v1/people/13': return {'id': 13}
            if path == '/v1/me': return {'id': 1}
            self.puts.append((path, kw.get('json')))
            return {}

    http = Http()
    assert asyncio.run(assign_unowned(http, '9')) == 2
    assert http.puts == [('/v1/deals/1', {'userIds': [4]}), ('/v1/deals/3', {'userIds': [1]})]  # no agent → account owner
