import asyncio
import json
import uuid
from types import SimpleNamespace
import pytest
from tests.test_radar_automations import crm
from app.services.crm import assistant
from app.services.crm.assistant_schema import CommandSpec
from app.services.crm.providers import PROVIDERS, Contact


def prepare(client, action, **args):
    r = client.post('/api/radar/automations/commands', json={'provider':'followupboss','spec':{'action':action, **args}})
    assert r.status_code == 200, r.text
    return r.json()


def run(client, command):
    r = client.post(f"/api/radar/automations/commands/{command['id']}/execute", json={'confirmed':True})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize('provider',[key for key,p in PROVIDERS.items() if p.category=='crm'])
def test_every_crm_has_shared_contact_tools(provider):
    actions={t['action'] for t in assistant.capabilities(provider)}
    assert {'list_contacts','find_contact','create_contact'} <= actions
    assert 'delete_contact' not in actions
    assert ('create_pipeline' in actions) == (provider in {'close','hubspot','pipedrive','followupboss'})
    assert ('mark_dnc' in actions) == (provider in {'followupboss','highlevel','salesforce'})


@pytest.mark.parametrize('provider',[key for key,p in PROVIDERS.items() if p.category=='crm'])
def test_contact_create_and_lookup_use_each_existing_adapter(provider, monkeypatch):
    p=PROVIDERS[provider]; calls=[]
    async def find(http,cfg,contact,create):
        calls.append((contact.email,create));return 'record1'
    monkeypatch.setattr(p,'find_or_create',find)
    monkeypatch.setattr(assistant.sync,'http_for',lambda c:(p,object()))
    conn=SimpleNamespace(provider=provider,config={})
    for action in ['find_contact','create_contact']:
        args={'action':action,'email':'person@example.com'}
        if action=='create_contact':args['name']='A Person'
        result=asyncio.run(assistant.perform(None,conn,CommandSpec(**args)))
        assert result['id']=='record1'
    assert calls==[('person@example.com',False),('person@example.com',True)]


def test_close_pipeline_creation_uses_real_adapter_and_reuses_existing(monkeypatch):
    from app.services.crm.providers import Close
    p=Close()
    class Http:
        def __init__(self): self.pipes=[]; self.writes=[]
        async def request(self,method,path,**kwargs):
            if method=='GET': return {'data':self.pipes}
            body=kwargs['json'];self.writes.append((path,body))
            if path=='/v1/pipeline/':
                pipe={'id':'pipe_1','name':body['name'],'statuses':[]};self.pipes.append(pipe);return dict(pipe)
            row={'id':'status_'+str(len(self.writes)),'label':body['label'],'type':body['type']}
            self.pipes[0]['statuses'].append(row);return row
    http=Http();monkeypatch.setattr(assistant.sync,'http_for',lambda c:(p,http))
    conn=SimpleNamespace(provider='close',config={})
    spec=CommandSpec(action='create_pipeline',name='Test',stages=[{'label':'New'},{'label':'Won','kind':'won'}])
    first=asyncio.run(assistant.perform(None,conn,spec));second=asyncio.run(assistant.perform(None,conn,spec))
    assert first['pipeline']['id']==second['pipeline']['id']=='pipe_1'
    assert len(http.writes)==3
    assert http.writes[-1][1]['type']=='won'


def test_command_requires_confirmation_and_runs_only_once(client, crm):
    before=len(crm['calls'])
    cmd=prepare(client,'add_note',external_id='91',text='The owner confirmed their name.')
    assert cmd['status']=='draft' and cmd['writes']
    assert not any(m in ('PUT','POST') for m,_,_ in crm['calls'][before:])
    url=f"/api/radar/automations/commands/{cmd['id']}/execute"
    assert client.post(url,json={}).status_code==422
    assert client.post(url,json={'confirmed':False}).status_code==422
    assert run(client,cmd)['status']=='succeeded'
    assert run(client,cmd)['status']=='succeeded'
    writes=[x for x in crm['calls'] if x[0]=='POST' and x[1]=='/v1/notes']
    assert len(writes)==1 and writes[0][2]['body']=='The owner confirmed their name.'


def test_commands_cannot_cross_organizations(client,crm,make_client):
    from tests.test_accounts import _new_account,_login
    cmd=prepare(client,'add_note',external_id='91',text='Private note')
    org,email=_new_account(client)
    client.post(f"/api/admin/billing/orgs/{org['id']}/overrides",json={'key':'radar','value':True,'reason':'Test'})
    owner=_login(make_client,email)
    assert owner.post(f"/api/radar/automations/commands/{cmd['id']}/execute",json={'confirmed':True}).status_code==404
    assert cmd['id'] not in {x['id'] for x in owner.get('/api/radar/automations/commands').json()['items']}


def test_unsupported_and_arbitrary_tools_are_rejected(client,crm):
    for spec in [{'action':'delete_contact','external_id':'91'}, {'action':'add_note','external_id':'../me','text':'x'},
                 {'action':'list_contacts','limit':10000}, {'action':'create_contact','name':'Nobody'},
                 {'action':'list_contacts','url':'https://example.com'}, {'action':'list_contacts','text':'unused'}]:
        assert client.post('/api/radar/automations/commands',json={'provider':'followupboss','spec':spec}).status_code==422
    r=client.post('/api/radar/automations/commands',json={'provider':'followupboss','spec':{'action':'create_pipeline','name':'Test','stages':[{'label':'New'}]}})
    assert r.status_code==400


def test_lost_response_is_uncertain_and_never_blindly_retried(client,crm,monkeypatch):
    calls=[]
    async def fail(*args):calls.append(True);raise RuntimeError('Response lost after remote write')
    monkeypatch.setattr(assistant,'perform',fail)
    cmd=prepare(client,'add_note',external_id='91',text='Review first')
    result=run(client,cmd)
    assert result['status']=='uncertain' and 'Check the CRM' in result['error']
    assert client.post(f"/api/radar/automations/commands/{cmd['id']}/execute",json={'confirmed':True}).status_code==400
    assert len(calls)==1


def test_llm_proposes_commands_without_executing_them(client,crm,monkeypatch):
    from app.services import llm
    async def fake(*args,**kwargs):
        return {'choices':[{'message':{'content':json.dumps({'message':'Review this note before applying.','commands':[{'action':'add_note','external_id':'91','text':'Customer requested a callback.'}]})}}]}
    monkeypatch.setattr(llm,'_chat',fake)
    before=len(crm['calls'])
    result=client.post('/api/radar/automations/draft',json={'provider':'followupboss','message':'Add a note for person 91: Customer requested a callback.'})
    assert result.status_code==200,result.text
    assert result.json()['commands'][0]['status']=='draft' and not result.json()['writes_performed']
    assert not any(m in ('POST','PUT') for m,_,_ in crm['calls'][before:])


def test_expired_or_reconnected_proposals_cannot_execute(client,crm):
    from app.database import AsyncSessionLocal
    from app.models.crm_command import CrmCommand
    from app.models.crm import CrmConnection
    from datetime import datetime,timedelta,timezone
    cmd=prepare(client,'add_note',external_id='91',text='Old request')
    async def age():
        async with AsyncSessionLocal() as db:
            row=await db.get(CrmCommand,uuid.UUID(cmd['id']))
            row.created_at=datetime.now(timezone.utc)-timedelta(hours=1)
            await db.commit()
    asyncio.run(age())
    assert client.post(f"/api/radar/automations/commands/{cmd['id']}/execute",json={'confirmed':True}).status_code==400
    current=prepare(client,'add_note',external_id='91',text='New request')
    async def change_account():
        async with AsyncSessionLocal() as db:
            row=await db.get(CrmCommand,uuid.UUID(current['id']))
            conn=await db.get(CrmConnection,row.connection_id)
            conn.account_label='Different account'
            await db.commit()
    asyncio.run(change_account())
    assert client.post(f"/api/radar/automations/commands/{current['id']}/execute",json={'confirmed':True}).status_code==400


@pytest.mark.parametrize('provider,path',[('close','/v1/activity/note/'),('followupboss','/v1/notes'),
    ('highlevel','/contacts/91/notes'),('attio','/v2/notes'),('zoho','/crm/v6/Leads/91/Notes'),('sierra','/leads/91/note')])
def test_native_notes_do_not_create_fictional_calls(provider,path):
    writes=[]
    class Http:
        async def request(self,method,url,**kwargs):
            writes.append((method,url,kwargs));return {'success':True,'data':{}}
    asyncio.run(assistant.add_note(PROVIDERS[provider],Http(),{},'91','Actual note text','A note'))
    assert len(writes)==1 and writes[0][0]=='POST' and writes[0][1]==path
    assert 'Actual note text' in json.dumps(writes[0][2])
    assert 'duration' not in json.dumps(writes[0][2])


def test_do_not_call_suppresses_only_linked_local_contacts(client,crm):
    from tests.test_radar_automations import add_call
    from app.database import AsyncSessionLocal
    from app.models.lead import Lead
    key,linked=add_call(crm)
    other_key,other=add_call(crm)
    async def unlink():
        async with AsyncSessionLocal() as db:
            lead=await db.get(Lead,uuid.UUID(other));lead.crm_refs={'followupboss':'92'}
            await db.commit()
    asyncio.run(unlink())
    cmd=prepare(client,'mark_dnc',external_id='91')
    assert run(client,cmd)['status']=='succeeded'
    async def flags():
        async with AsyncSessionLocal() as db:
            return (await db.get(Lead,uuid.UUID(linked))).do_not_call,(await db.get(Lead,uuid.UUID(other))).do_not_call
    assert asyncio.run(flags())==(True,False)


def test_pipeline_preview_keeps_explicit_default_stage_kinds(monkeypatch):
    class Db:
        def add(self,row):pass
        async def flush(self):pass
    conn=SimpleNamespace(provider='close',config={},id=uuid.uuid4(),org_id=uuid.uuid4(),account_label='Test org')
    spec=CommandSpec(action='create_pipeline',name='Test',stages=[{'label':'New'},{'label':'Won','kind':'won'}])
    row=asyncio.run(assistant.prepare(Db(),conn,uuid.uuid4(),spec))
    assert row.spec['stages']==[{'label':'New','kind':'active'},{'label':'Won','kind':'won'}]
