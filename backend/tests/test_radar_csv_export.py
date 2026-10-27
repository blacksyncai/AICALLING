import asyncio
import json
import re
import uuid
import httpx
import pytest
from tests.test_radar_contact_resolution import remote,queue,person,job,linked
from tests.test_radar_automations import crm,execute_all
BASE='/api/radar/automations'


@pytest.fixture
def csv_remote(client,crm,remote,monkeypatch):
    from app.services.crm.http import BaseHttp
    previous=BaseHttp.client_factory
    state={'fields':[], 'calls':[], 'deny_create':False, 'lose_field':False,'lose_put':False,'reserved':set()}
    client.patch('/api/integrations/crm/followupboss',json={'csv_create_fields':False})
    async def handle(req):
        path,method=req.url.path,req.method
        body=json.loads(req.content) if req.content else {}
        if path=='/v1/customFields':
            state['calls'].append((method,path,body))
            if method=='GET':return httpx.Response(200,json={'customfields':state['fields']})
            if state['deny_create']:return httpx.Response(403,json={'message':'Account owner only'})
            if body['label'] in state['reserved']:return httpx.Response(400,json={'errorMessage':f'Field "{body["label"]}" is reserved by the system'})
            name='custom'+''.join(x.capitalize() for x in re.findall('[A-Za-z0-9]+',body['label']))
            item={**body,'name':name};state['fields'].append(item)
            if state['lose_field']:raise httpx.ReadTimeout('Field response lost',request=req)
            return httpx.Response(200,json=item)
        if path.startswith('/v1/people/') and method=='PUT':
            state['calls'].append((method,path,body))
            p=next(p for p in remote['people'] if str(p['id'])==path.rsplit('/',1)[-1])
            p.update(body)
            if 'addresses' in body:p['addresses']=[{**a,'type':a.get('type','home')} for a in body['addresses']]
            if state['lose_put']:raise httpx.ReadTimeout('Person response lost',request=req)
            return httpx.Response(200,json=p)
        async with previous() as client:return await client.request(method,str(req.url),content=req.content,headers=req.headers)
    monkeypatch.setattr(BaseHttp,'client_factory',staticmethod(lambda:httpx.AsyncClient(transport=httpx.MockTransport(handle))))
    yield state
    client.patch('/api/integrations/crm/followupboss',json={'csv_create_fields':False})


def extras(lead_id,fields,company='',agent_id=None,crm_fields=None):
    from app.database import AsyncSessionLocal
    from app.models.lead import Lead
    async def go():
        async with AsyncSessionLocal() as db:
            lead=await db.get(Lead,uuid.UUID(lead_id));lead.custom_fields=fields;lead.company=company;await db.commit()
    asyncio.run(go())


def test_existing_mapping_catalog_is_reused_and_address_custom_values_exported(client,crm,remote,csv_remote):
    remote['people']=[person()]
    csv_remote['fields']=[{'name':'customUnits','label':'Unit Count','type':'number'}, {'name':'customStrategy','label':'Strategy','type':'dropdown','choices':['Buy','Sell']}]
    call,lead,_=queue(client,crm)
    extras(lead,{'address':'123 Main St','city':'Austin','state':'TX','zip':'00123','unit_count':'12','strategy':'Buy','unmatched':'Keep this too'})
    execute_all();row=job(client,call)
    assert row['status']=='succeeded',row
    p=remote['people'][0]
    assert p['addresses'][0]['street']=='123 Main St' and p['addresses'][0]['code']=='00123'
    assert p['customUnits']==12 and p['customStrategy']=='Buy'
    assert 'Keep this too' in p['background'] and '123 Main St' in p['background']
    assert row['result']['csv_data']['unmapped']==['unmatched']
    assert not any(m=='POST' for m,p,b in csv_remote['calls'])
    assert remote['deals'][0]['peopleIds']==[91]


def test_creation_opt_in_creates_text_fields_and_preserves_all_data(client,crm,remote,csv_remote):
    remote['people']=[person()]
    client.patch('/api/integrations/crm/followupboss',json={'csv_create_fields':True})
    call,lead,_=queue(client,crm);extras(lead,{'property_address':'99 Oak Road','seller_motivation':'Moving soon'},company='Sample Holdings')
    execute_all();row=job(client,call)
    assert row['status']=='succeeded',row
    labels={f['label'] for f in csv_remote['fields']}
    assert labels=={'Property Address','Seller Motivation','Company'}
    p=remote['people'][0]
    assert p['customPropertyAddress']=='99 Oak Road' and 'addresses' not in p
    assert p['customSellerMotivation']=='Moving soon' and p['customCompany']=='Sample Holdings'
    assert row['result']['csv_data']['created_fields']
    assert 'pending_csv_field' not in row['result']


def test_existing_values_and_background_are_preserved_and_conflicts_reported(client,crm,remote,csv_remote):
    remote['people']=[{**person(),'addresses':[{'street':'Keep my address','city':'Boston'}],'background':'Original private notes','customUnits':8}]
    csv_remote['fields']=[{'name':'customUnits','label':'Units','type':'number'}]
    call,lead,_=queue(client,crm);extras(lead,{'address':'Different CSV address','units':'12','source':'CSV portal'})
    execute_all();row=job(client,call)
    assert row['status']=='succeeded',row
    p=remote['people'][0]
    assert p['customUnits']==8 and p['addresses'][0]['street']=='Keep my address'
    assert p['source']=='Original referral' and p['background'].startswith('Original private notes')
    assert 'Different CSV address' in p['background'] and 'CSV portal' in p['background']
    assert {'units','address'}<=set(row['result']['csv_data']['conflicts'])


def test_owner_permission_denial_falls_back_to_snapshot_without_losing_values(client,crm,remote,csv_remote):
    remote['people']=[person()];csv_remote['deny_create']=True
    client.patch('/api/integrations/crm/followupboss',json={'csv_create_fields':True})
    call,lead,_=queue(client,crm);extras(lead,{'first_extra':'One','second_extra':'Two'})
    execute_all();row=job(client,call)
    assert row['status']=='succeeded',row
    assert len([1 for m,p,b in csv_remote['calls'] if m=='POST'])==1
    assert row['result']['csv_data']['warnings'] and set(row['result']['csv_data']['unmapped'])=={'first_extra','second_extra'}
    assert 'One' in remote['people'][0]['background'] and 'Two' in remote['people'][0]['background']


def test_invalid_native_types_and_long_values_are_preserved_in_snapshot(client,crm,remote,csv_remote):
    remote['people']=[person()]
    csv_remote['fields']=[{'name':'customUnits','label':'Units','type':'number'}, {'name':'customBirthday','label':'Birthday','type':'date'}]
    call,lead,_=queue(client,crm);extras(lead,{'units':'not sure','birthday':'next week','long_notes':'X'*400})
    execute_all();row=job(client,call)
    assert row['status']=='succeeded',row
    assert {'units','birthday','long_notes'}<=set(row['result']['csv_data']['unmapped'])
    p=remote['people'][0]
    assert 'customUnits' not in p and 'X'*400 in p['background']


def test_uncertain_custom_field_creation_reconciles_without_duplicate_post(client,crm,remote,csv_remote):
    remote['people']=[person()];csv_remote['lose_field']=True
    client.patch('/api/integrations/crm/followupboss',json={'csv_create_fields':True})
    call,lead,_=queue(client,crm);extras(lead,{'units':'12'})
    execute_all();row=job(client,call)
    assert row['status']=='failed' and 'pending_csv_field' in row['result'],row
    csv_remote['lose_field']=False
    client.post(f"{BASE}/activity/{row['id']}/retry")
    execute_all();row=job(client,call)
    assert row['status']=='succeeded',row
    assert len(csv_remote['fields'])==1
    assert len([1 for m,p,b in csv_remote['calls'] if m=='POST'])==1
    assert remote['people'][0]['customUnits']=='12'


def test_completed_action_can_backfill_csv_without_creating_another_deal(client,crm,remote,csv_remote):
    remote['people']=[person()]
    call,lead,_=queue(client,crm);execute_all();row=job(client,call)
    assert row['status']=='succeeded'
    extras(lead,{'address':'123 Backfill St','misc':'Anything else'})
    for _ in range(2):
        r=client.post(f"{BASE}/activity/{row['id']}/sync-data")
        assert r.status_code==200,r.text
    assert len(remote['deals'])==1 and len(remote['people'])==1
    background=remote['people'][0]['background']
    assert background.count('[BlackSync CSV ')==1 and 'Anything else' in background


def test_internal_runtime_metadata_is_not_exported(client,crm,remote,csv_remote):
    remote['people']=[person()]
    call,lead,_=queue(client,crm);extras(lead,{'crm_context':'Private runtime context','crm_fields':{'followupboss':{'unit_count':'7'}},'bs_tries':'9','property_type':'Duplex'})
    execute_all();row=job(client,call)
    assert row['status']=='succeeded',row
    text=remote['people'][0]['background']
    assert 'Duplex' in text and 'Private runtime context' not in text and 'crm_fields' not in text and 'bs_tries' not in text


def test_saved_per_agent_script_mapping_is_reused_without_replacing_inbound_flow(client,crm,remote,csv_remote):
    from app.database import AsyncSessionLocal
    from app.models.agent import Agent
    from app.models.call_log import CallLog
    remote['people']=[person()]
    csv_remote['fields']=[{'name':'customUnits','label':'Unit Count','type':'number'}]
    call,lead,_=queue(client,crm);extras(lead,{'door_count':'12'})
    async def set_agent():
        async with AsyncSessionLocal() as db:
            a=Agent(org_id=uuid.UUID(crm['org_id']),name='CSV mapping test',system_prompt='There are {{door_count}} units.')
            db.add(a);await db.flush()
            c=await db.get(CallLog,uuid.UUID(call));c.agent_id=a.id;await db.commit();return str(a.id)
    aid=asyncio.run(set_agent())
    saved=client.put('/api/integrations/crm/followupboss/variables',json={'agent_id':aid,'map':{'door_count':'unit_count'}})
    assert saved.status_code==200,saved.text
    execute_all();row=job(client,call)
    assert row['status']=='succeeded',row
    assert remote['people'][0]['customUnits']==12
    # The original inbound endpoint still resolves the same script variable using its saved choice.
    inbound=client.get('/api/integrations/crm/followupboss/variables',params={'agent_id':aid})
    assert inbound.status_code==200,inbound.text
    variable=next(v for v in inbound.json()['variables'] if v['name']=='door_count')
    assert variable['mapped_to']=='unit_count'
    assert any(f['key']=='unit_count' for f in inbound.json()['fields'])
    from tests.test_crm_assistant import prepare,run
    current=run(client,prepare(client,'contact_fields',external_id='91'))
    assert current['result']['fields']['unit_count']=='12'


def test_person_update_lost_response_is_reconciled_without_duplicate_snapshot(client,crm,remote,csv_remote):
    remote['people']=[person()];csv_remote['lose_put']=True
    call,lead,_=queue(client,crm);extras(lead,{'address':'123 Lost Response St'})
    execute_all();row=job(client,call)
    assert row['status']=='retry',row
    csv_remote['lose_put']=False
    client.post(f"{BASE}/activity/{row['id']}/retry")
    execute_all();row=job(client,call)
    assert row['status']=='succeeded',row
    assert remote['people'][0]['background'].count('[BlackSync CSV ')==1
    assert len(remote['deals'])==1


def test_sync_data_endpoint_is_scoped_to_workspace(client,crm,remote,csv_remote,make_client):
    from tests.test_accounts import _new_account,_login
    remote['people']=[person()]
    call,lead,_=queue(client,crm);execute_all();row=job(client,call)
    org,email=_new_account(client)
    client.post(f"/api/admin/billing/orgs/{org['id']}/overrides",json={'key':'radar','value':True,'reason':'Test'})
    owner=_login(make_client,email)
    before=len(csv_remote['calls'])
    response=owner.post(f"{BASE}/activity/{row['id']}/sync-data")
    assert response.status_code==404 and len(csv_remote['calls'])==before


def test_missing_email_is_filled_without_replacing_existing_identifiers(client,crm,remote,csv_remote):
    remote['people']=[person()]
    call,lead,_=queue(client,crm,email='gabe@example.test');extras(lead,{'address':'123 Main St'})
    execute_all();row=job(client,call)
    assert row['status']=='succeeded',row
    assert remote['people'][0]['emails']==[{'value':'gabe@example.test'}]
    assert remote['people'][0]['phones']==[{'value':'+14155550123'}]
    assert remote['people'][0]['name']=='Existing Gabe'


def test_schema_catalog_failure_never_creates_fields_or_writes_values(client,crm,remote,csv_remote,monkeypatch):
    from app.services.crm.providers import PROVIDERS
    from app.services.crm.http import CrmError
    remote['people']=[person()]
    client.patch('/api/integrations/crm/followupboss',json={'csv_create_fields':True})
    async def failed(*args,**kwargs):raise CrmError('Cannot read field catalog',403)
    monkeypatch.setattr(PROVIDERS['followupboss'],'_custom_fields',failed)
    call,lead,_=queue(client,crm);extras(lead,{'unknown':'Keep my data'})
    execute_all();row=job(client,call)
    assert row['status'] in ('retry','failed') and 'Cannot read' in row['error'],row
    assert not csv_remote['calls'] and 'background' not in remote['people'][0] and not remote['deals']


def test_fub_identifier_formatting_does_not_produce_false_failed_receipt():
    from app.services.crm.csv_export import confirmed,convert
    assert confirmed([{'value':'(415) 555-0123','type':'mobile'}],[{'value':'+14155550123'}],'phones')
    assert confirmed([{'value':'GABE@EXAMPLE.TEST'}],[{'value':'gabe@example.test'}],'emails')
    assert not confirmed([{'value':'+14155550999'}],[{'value':'+14155550123'}],'phones')
    for value in ('NaN','Infinity','1e999999','0.1234567890123456789012345'):
        with pytest.raises(ValueError):convert(value,{'type':'number'})


def test_fub_native_and_reserved_field_names_never_fail_the_push(client,crm,remote,csv_remote):
    """A CSV with first_name/last_name columns (and a label FUB reserves) still routes the deal."""
    remote['people']=[person()];csv_remote['reserved']={'Owner Type'}
    client.patch('/api/integrations/crm/followupboss',json={'csv_create_fields':True})
    call,lead,_=queue(client,crm);extras(lead,{'first_name':'Robert','last_name':'Chen','owner_type':'Trust','units':'8'})
    execute_all();row=job(client,call)
    assert row['status']=='succeeded',row
    posted={b['label'] for m,p,b in csv_remote['calls'] if m=='POST'}
    assert 'First Name' not in posted and 'Last Name' not in posted
    assert 'owner_type' in row['result']['csv_data']['unmapped'] and row['result']['csv_data']['warnings']
    assert 'Trust' in remote['people'][0]['background'] and remote['deals']
