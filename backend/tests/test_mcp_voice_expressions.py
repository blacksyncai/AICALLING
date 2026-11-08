"""Expression controls through the real regular/admin MCP endpoints and OAuth contexts."""
from tests.test_connector import _connect, _tool, _rpc
from tests.test_admin_mcp import _admin_connect, _tool as admin_tool, _rpc as admin_rpc, _customer, SCRIPT


AUTO={'expressions_enabled':True,'expression_mode':'automatic','delivery_style':'warm',
      'delivery_direction':'Be curious for identity questions and softer if they are busy.', 'automatic_laughter':False}


def test_both_mcps_advertise_expression_write_schema(client, make_client):
    anon=make_client()
    regular=_connect(client,anon)['access_token']
    admin=_admin_connect(client,anon)
    regular_tools={t['name']:t for t in _rpc(anon,regular,'tools/list')['result']['tools']}
    admin_tools={t['name']:t for t in admin_rpc(anon,admin,'tools/list').json()['result']['tools']}
    from app.routers.agents import VoiceTuning
    for tool in ('create_agent','update_agent'):
        schema=regular_tools[tool]['inputSchema']['properties']['voice_tuning']
        assert schema==admin_tools[tool]['inputSchema']['properties']['voice_tuning']
        assert set(schema['properties'])==set(VoiceTuning.model_fields)
        assert schema['additionalProperties'] is False
        assert schema['properties']['expression_mode']['enum']==['automatic','script']
        assert schema['properties']['delivery_direction']['maxLength']==500
        assert 'curious' in schema['properties']['default_emotion']['enum']
        assert not regular_tools[tool]['annotations']['readOnlyHint']
        assert 'account_id' in admin_tools[tool]['inputSchema']['properties']


def test_mcp_expression_partial_updates_preserve_other_tuning(client, make_client):
    anon=make_client();token=_connect(client,anon)['access_token']
    agent=client.post('/api/agents/',json={'template':'blank'}).json()
    original={'tone':'calm','volume':1.25,'responsiveness':.35,'interruption':.25,
              'voicemail_min_connected_seconds':12,'pronunciations':[{'word':'Nguyen','say':'Win'}]}
    assert client.patch(f"/api/agents/{agent['id']}",json={'voice_tuning':original}).status_code==200
    out,err=_tool(anon,token,'update_agent',{'agent_id':agent['id'],'voice_tuning':AUTO})
    assert not err,out
    assert out['updated']==['voice_tuning']
    assert all(out['voice_tuning'][k]==v for k,v in {**original,**AUTO}.items())
    once,err=_tool(anon,token,'update_agent',{'agent_id':agent['id'],'voice_tuning':{'delivery_style':'calm'}})
    assert not err and once['voice_tuning']['delivery_direction']==AUTO['delivery_direction']
    twice,err=_tool(anon,token,'update_agent',{'agent_id':agent['id'],'voice_tuning':{'delivery_style':'calm'}})
    assert not err and twice['voice_tuning']==once['voice_tuning']
    read,err=_tool(anon,token,'get_agent',{'agent_id':agent['id']})
    assert not err and read['voice_tuning']==twice['voice_tuning'] and read['voice_expressions_supported']
    off,err=_tool(anon,token,'update_agent',{'agent_id':agent['id'],'voice_tuning':{'expressions_enabled':False}})
    assert not err and not off['voice_tuning']['expressions_enabled']
    assert off['voice_tuning']['delivery_direction']==AUTO['delivery_direction']
    assert off['voice_tuning']['pronunciations']==original['pronunciations']


def test_mcp_can_create_paused_agent_with_expression_settings(client, make_client):
    anon=make_client();token=_connect(client,anon)['access_token']
    created,err=_tool(anon,token,'create_agent',{'name':'Voice expression MCP test', 'system_prompt':SCRIPT,
        'first_message':'Hey, this is James, right?','voice_tuning':AUTO})
    assert not err,created
    assert created['status']=='paused'
    assert all(created['voice_tuning'][key]==value for key,value in AUTO.items())
    read,err=_tool(anon,token,'get_agent',{'agent_id':created['id']})
    assert not err and read['voice_tuning']==created['voice_tuning']
    before=_tool(anon,token,'list_agents')[0]['agents']
    bad,err=_tool(anon,token,'create_agent',{'name':'Should not be created','system_prompt':SCRIPT,
        'first_message':'Hello','voice_tuning':{'unknown':True}})
    assert err and 'Unknown voice_tuning' in bad['error']
    assert len(_tool(anon,token,'list_agents')[0]['agents'])==len(before)


def test_invalid_expression_updates_do_not_write(client, make_client):
    anon=make_client();token=_connect(client,anon)['access_token']
    agent=client.post('/api/agents/',json={'template':'blank'}).json()
    for invalid in ({},{'delivery_style':'unknown'},{'default_emotion':'unknown'},
                    {'delivery_direction':'x'*501},{'volume':10},{'unknown':True},'wrong type'):
        result,err=_tool(anon,token,'update_agent',{'agent_id':agent['id'],'voice_tuning':invalid})
        assert err,result
        saved=client.get(f"/api/agents/{agent['id']}").json()
        assert saved['voice_tuning']==agent['voice_tuning']


def test_list_voices_exposes_options_and_provider_support(client, make_client, monkeypatch):
    from app.routers import settings
    async def catalog(*args):
        return {'voices':[{'id':'voice-id','name':'Sample'},{'id':'elevenlabs:sample','name':'Other'}]}
    async def owned(*args): return {'voices':[]}
    monkeypatch.setattr(settings,'list_voices',catalog)
    monkeypatch.setattr(settings,'my_voices',owned)
    anon=make_client();token=_connect(client,anon)['access_token']
    result,err=_tool(anon,token,'list_voices')
    assert not err,result
    options=result['voice_expressions']
    assert options['modes']==['automatic','script']
    assert {s['value'] for s in options['styles']}=={'natural','warm','calm','confident','custom'}
    assert 'curious' in options['emotions'] and options['automatic_laughter_default'] is False
    assert result['voices'][0]['voice_expressions_supported'] is True
    assert result['voices'][1]['voice_expressions_supported'] is False


def test_admin_expression_updates_remain_scoped_to_target_account(client, make_client):
    first=_customer(client,'Expression account one');second=_customer(client,'Expression account two')
    anon=make_client();admin=_admin_connect(client,anon)
    created,err=admin_tool(anon,admin,'create_agent',{'account_id':first,'name':'Scoped expression agent',
        'system_prompt':SCRIPT,'first_message':'Hey, this is James, right?','voice_tuning':AUTO})
    assert not err,created
    bad,err=admin_tool(anon,admin,'update_agent',{'account_id':second,'agent_id':created['id'],
        'voice_tuning':{'delivery_style':'calm'}})
    assert err,bad
    updated,err=admin_tool(anon,admin,'update_agent',{'account_id':first,'agent_id':created['id'],
        'voice_tuning':{'delivery_style':'calm'}})
    assert not err and updated['voice_tuning']['delivery_style']=='calm'
    assert updated['voice_tuning']['delivery_direction']==AUTO['delivery_direction']
    read,err=admin_tool(anon,admin,'get_agent',{'account_id':first,'agent_id':created['id']})
    assert not err and read['voice_tuning']==updated['voice_tuning']
    regular=_connect(client,anon)['access_token']
    _,err=_tool(anon,regular,'get_agent',{'agent_id':created['id']})
    assert err  # The normal connector's selected house account cannot read this customer agent.
