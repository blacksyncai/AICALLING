import asyncio
import datetime as dt
import json

import httpx
import pytest
from app.services.crm.providers import PROVIDERS
from app.services.crm.http import BaseHttp, CrmError
from app.services.crm import cloud_radar, cloud_views, radar_history

P = PROVIDERS['blacksync_cloud']
NOW = dt.datetime.now(dt.timezone.utc)
def when(days): return (NOW-dt.timedelta(days=days)).isoformat()

PEOPLE = [{'id': key, 'companyId': key+'-co', 'name': {'firstName':key.title()},
           'createdAt': when(90), 'phones': {'primaryPhoneCallingCode': '+1', 'primaryPhoneNumber': '41555501'+str(i).zfill(2)}}
          for i,key in enumerate(['hot','never','tried','cold','stuck','contacted'])]
COMPANIES = [{'id': p['companyId'], 'name':p['id']+' Company','createdAt':when(90),'leadStatus':'OPEN','leadPond':'Buyers'} for p in PEOPLE]
NOTES = [{'id':'hot-note','title':'Email received: Buying soon','createdAt':when(1)},
         {'id':'tried-note','title':'Outbound call · 0:08 · No answer','createdAt':when(5)},
         {'id':'cold-note','title':'Outbound call · 1:20 · Answered','createdAt':when(40)},
         {'id':'stuck-note','title':'Outbound call · 1:20 · Answered','createdAt':when(3)},
         {'id':'contacted-note','title':'Outbound call · 1:20 · Answered','createdAt':when(1)},
         {'id':'never-summary','title':'Imported from Close','createdAt':when(1)}]
TARGETS = [{'id':n['id']+'-target','targetPersonId':n['id'].split('-')[0],'noteId':n['id']} for n in NOTES]
DEALS = [{'id':'d1','companyId':'stuck-co','pointOfContactId':'stuck','stage':'NEW','pipeline':'SALES',
          'salesStage':'PROPOSAL','updatedAt':when(30)}]
OBJECTS = [{'id':'obj-people','nameSingular':'person','fields':[]},
           {'id':'obj-company','nameSingular':'company','fields':[{'id':'pond-field','name':'leadPond'}]},
           {'id':'obj-deal','nameSingular':'opportunity','fields':[
               {'id':'pipe-field','name':'pipeline'}, {'id':'stage-field','name':'salesStage','options':[
                   {'value':'PROPOSAL','label':'Proposal'}, {'value':'CLOSED_WON','label':'Won'}]}]}]
VIEWS = [{'id':'buyers-view','name':'Buyers','objectMetadataId':'obj-company','viewFilters':[
                {'fieldMetadataId':'pond-field','operand':'IS','value':'["Buyers"]'}]},
         {'id':'sales-view','name':'Sales','objectMetadataId':'obj-deal','type':'KANBAN','mainGroupByFieldMetadataId':'stage-field',
          'viewFilters':[{'fieldMetadataId':'pipe-field','operand':'IS','value':'["SALES"]'}]}]


@pytest.fixture
def cloud(monkeypatch):
    tables={'people':PEOPLE,'companies':COMPANIES,'notes':NOTES,'noteTargets':TARGETS,'opportunities':DEALS,
            'metadata/objects':OBJECTS,'metadata/views':VIEWS}
    seen=[]
    def handler(req):
        assert req.method == 'GET'  # Discovery never writes into the customer's CRM.
        assert req.headers['Authorization']=='Bearer test-cloud-key'
        resource=req.url.path.removeprefix('/rest/')
        assert resource in tables, resource
        seen.append(req)
        rows=list(tables[resource])
        filter_value=req.url.params.get('filter')
        if filter_value:
            field,ids=filter_value.split('[in]:',1)
            ids=json.loads(ids)
            rows=[r for r in rows if str(r.get(field)) in ids]
        limit=int(req.url.params['limit'])
        rows=rows[:limit]
        data=rows if resource.startswith('metadata/') else {resource:rows}
        return httpx.Response(200,json={'data':data,'pageInfo':{'hasNextPage':False}})
    monkeypatch.setattr(BaseHttp,'client_factory',staticmethod(lambda:httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    return tables,seen,P.native_http('test-cloud-key',{'instance_url':'https://crm.blacksync.cloud'})


def test_cloud_reads_real_activity_and_custom_pipeline_fields(cloud):
    tables,seen,http=cloud
    state={}
    signals=asyncio.run(P.scan_signals(http,{},state=state))
    result=radar_history.build(signals,NOW)
    groups={p['key']:[x['external_id'] for x in p['items']] for p in result['plays']}
    assert groups['hot']==['hot']
    assert groups['never_called']==['never']
    assert groups['unreached']==['tried']
    assert groups['went_cold']==['cold']
    assert groups['stuck']==['stuck']
    assert groups['contacted']==['contacted']
    assert state['next'] is None
    assert {r.url.path for r in seen} >= {'/rest/people','/rest/companies','/rest/notes','/rest/noteTargets','/rest/opportunities'}


def test_cloud_ponds_saved_views_and_pipeline_stages_are_real_lists(cloud):
    _,_,http=cloud
    options=asyncio.run(P.segment_options(http,{}))
    assert options['pond']==[{'value':'Buyers','label':'Buyers'}]
    assert any(o['value']=='view:buyers-view' for o in options['list'])
    stage=next(o for o in options['deal'] if o['label']=='Sales · Proposal')
    signals=asyncio.run(P.segment_signals(http,{},'deal',stage['value']))
    assert [s.external_id for s in signals]==['stuck']
    never=asyncio.run(P.segment_signals(http,{},'list','never-called'))
    assert [s.external_id for s in never]==['hot','never']  # An emailed contact can still be never called.
    buyers=asyncio.run(P.segment_signals(http,{},'list','view:buyers-view'))
    assert len(buyers)==6


def test_missing_notes_do_not_imply_never_contacted(cloud):
    tables,_,http=cloud
    tables['notes']=[]
    state={}
    signals=asyncio.run(P.scan_signals(http,{},state=state))
    assert all(not s.calls_known for s in signals)
    assert state['warnings']
    assert next(p for p in radar_history.build(signals,NOW)['plays'] if p['key']=='never_called')['count']==0


def test_saved_view_filter_groups_and_unknown_filters_fail_closed():
    fields={'field':{'name':'status'}}
    view={'viewFilters':[{'fieldMetadataId':'field','operand':'IS','value':'["Buyer"]','viewFilterGroupId':'g'},
                         {'fieldMetadataId':'field','operand':'IS','value':'["Seller"]','viewFilterGroupId':'g'}],
          'viewFilterGroups':[{'id':'g','logicalOperator':'OR','parentViewFilterGroupId':None}]}
    assert cloud_views.matches(view,fields,{'status':'Buyer'})
    assert not cloud_views.matches(view,fields,{'status':'Other'})
    view['viewFilters'][0]['operand']='VECTOR_SEARCH'
    with pytest.raises(CrmError,match='unsupported'):
        cloud_views.matches(view,fields,{'status':'Buyer'})


def test_invalid_cloud_cursor_is_not_silently_truncated():
    class Bad:
        async def request(self,*args,**kwargs):
            return {'data':{'people':[{'id':'x'}]},'pageInfo':{'hasNextPage':True,'endCursor':None}}
    with pytest.raises(CrmError,match='cursor'):
        asyncio.run(cloud_radar.collection(Bad(),'people'))


@pytest.mark.parametrize('groups', [
    [{'id':'g','parentViewFilterGroupId':'missing','logicalOperator':'AND'}],
    [{'id':'g','parentViewFilterGroupId':'g','logicalOperator':'AND'}],
])
def test_orphan_or_cyclic_groups_cannot_open_unfiltered_list(groups):
    with pytest.raises(CrmError):
        cloud_views.matches({'viewFilterGroups':groups}, {}, {})


def test_collection_continues_with_actual_cursor_and_order():
    class Pages:
        def __init__(self): self.requests=[]
        async def request(self, method, path, params):
            self.requests.append(dict(params))
            second = params.get('starting_after') == 'next-page'
            return {'data':{'people':[{'id':'second' if second else 'first'}]},
                    'pageInfo':{'hasNextPage':not second,'endCursor':None if second else 'next-page'}}
    http=Pages()
    rows,complete=asyncio.run(cloud_radar.collection(http,'people',order_by='createdAt[Asc]'))
    assert complete and [r['id'] for r in rows]==['first','second']
    assert http.requests[1]['starting_after']=='next-page'
    assert all(r['order_by']=='createdAt[Asc]' for r in http.requests)


def test_cloud_list_does_not_silently_return_partial_account(monkeypatch, cloud):
    async def incomplete(*args, **kwargs): return [], False
    monkeypatch.setattr(cloud_radar, 'snapshot', incomplete)
    with pytest.raises(CrmError, match='no partial list'):
        asyncio.run(P.segment_signals(cloud[2], {}, 'list', 'all'))
