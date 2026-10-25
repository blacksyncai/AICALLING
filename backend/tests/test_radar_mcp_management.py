import uuid
from tests.test_connector import _connect, _tool
from tests.test_radar_automations import crm, rule_body
from tests.test_radar_existing_campaign import launch_case


def test_mcp_rule_lifecycle_and_confirmation(client,make_client,crm):
    anon=make_client();token=_connect(client,anon)['access_token']
    before=len([x for x in crm['calls'] if x[0] in ('POST','PUT')])
    resources,err=_tool(anon,token,'radar_automation_resources',{'crm':'followupboss'})
    assert not err and resources['crm_ponds']
    body=rule_body()
    result,err=_tool(anon,token,'radar_preview_automation',{'rule':body})
    assert not err,result
    saved,err=_tool(anon,token,'radar_save_automation',{'rule':body})
    assert not err and saved['status']=='draft',saved
    key=saved['id']
    out,err=_tool(anon,token,'radar_list_automations')
    assert not err and any(r['id']==key for r in out['rules'])
    pending,err=_tool(anon,token,'radar_set_automation_state',{'rule_id':key,'status':'active'})
    assert not err and pending['needs_confirmation']
    assert next(r for r in client.get('/api/radar/automations').json()['rules'] if r['id']==key)['status']=='draft'
    active,err=_tool(anon,token,'radar_set_automation_state',{'rule_id':key,'status':'active','confirmed':True})
    assert not err and active['status']=='active'
    body['name']='Updated draft'
    edited,err=_tool(anon,token,'radar_save_automation',{'rule_id':key,'rule':body})
    assert not err and edited['status']=='draft' and edited['version']==2
    out,err=_tool(anon,token,'radar_automation_activity')
    assert not err and 'items' in out
    out,err=_tool(anon,token,'radar_set_automation_state',{'rule_id':str(uuid.uuid4()),'status':'active','confirmed':True})
    assert err and 'not found' in out['error'].lower()
    assert len([x for x in crm['calls'] if x[0] in ('POST','PUT')])==before


def test_mcp_existing_campaign_and_empty_selection(client,make_client,launch_case):
    anon=make_client();token=_connect(client,anon)['access_token'];c=launch_case
    args={'scan_id':c['scan'],'play':'cold','agent_id':c['agent'],'mode':'campaign','campaign_id':c['campaign'],'external_ids':['5']}
    result,err=_tool(anon,token,'radar_launch',args)
    assert not err and result['campaign_id']==c['campaign'] and result['existing_campaign']
    assert result['contacts']==1 and 'existing' in result['next_step']
    result,err=_tool(anon,token,'radar_launch',{**args,'external_ids':[]})
    assert err and 'Nobody' in result['error']


def test_schemas_are_typed_and_mutations_not_marked_read_only():
    from app.connector.tools import TOOLS
    for name in ['radar_save_automation','radar_set_automation_state','radar_run_automation']:
        assert TOOLS[name].descriptor()['annotations']['readOnlyHint'] is False
    schema=TOOLS['radar_save_automation'].schema
    assert schema['properties']['rule']['properties']['spec']['properties']['actions']['minItems']==1
    assert '$ref' not in str(schema)


def test_manual_run_requires_approval_and_rejects_other_account_rule(client,make_client,crm):
    import asyncio
    from app.database import AsyncSessionLocal
    from app.models.account import Organization
    from app.models.crm import CrmConnection
    from app.models.radar_automation import RadarAutomation, RadarExecution
    from sqlalchemy import select,func
    anon=make_client();token=_connect(client,anon)['access_token']
    rule,err=_tool(anon,token,'radar_save_automation',{'rule':rule_body()})
    assert not err
    result,err=_tool(anon,token,'radar_run_automation',{'rule_id':rule['id'],'call_ids':[str(uuid.uuid4())]})
    assert not err and result['needs_confirmation'] and result['writes_performed'] is False
    result,err=_tool(anon,token,'radar_run_automation',{'rule_id':rule['id'],'call_ids':[],'confirmed':True})
    assert err and 'one to 100' in result['error']
    async def other():
        async with AsyncSessionLocal() as db:
            org=Organization(name='Private account');db.add(org);await db.flush()
            conn=CrmConnection(org_id=org.id,provider='followupboss');db.add(conn);await db.flush()
            row=RadarAutomation(org_id=org.id,connection_id=conn.id,name='Private rule',request='',spec=rule_body()['spec'],status='active')
            db.add(row);await db.commit();return str(row.id)
    foreign=asyncio.run(other())
    result,err=_tool(anon,token,'radar_set_automation_state',{'rule_id':foreign,'status':'paused','confirmed':True})
    assert err and 'not found' in result['error'].lower()
    result,err=_tool(anon,token,'radar_save_automation',{'rule_id':foreign,'rule':rule_body()})
    assert err and 'not found' in result['error'].lower()


def test_non_manager_cannot_access_rule_tools(client,crm):
    import asyncio
    import pytest
    from types import SimpleNamespace
    from app.connector.tools import TOOLS,Session,ToolError
    async def check():
        s=Session(user=SimpleNamespace(),db=None,ctx=SimpleNamespace(can_manage=False))
        for name in ['radar_list_automations','radar_automation_activity','radar_save_automation','radar_set_automation_state','radar_run_automation']:
            with pytest.raises(ToolError,match='owners and admins'):
                await TOOLS[name].handler(s,{})
    asyncio.run(check())
