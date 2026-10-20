"""Explicit contact-to-deal routing; never confuse deal stages with person stages."""
from app.services.crm.http import CrmError
from app.services.crm.fub_pipelines import get_pipeline


async def route(http, person_id, pipeline_id, stage_id, name):
    pipe = await get_pipeline(http, pipeline_id)
    stages = {str(s.get('id')): s for s in pipe.get('stages', [])}
    if stage_id not in stages or stages[stage_id].get('closedStage'):
        raise CrmError('Choose an open deal stage; closed deals require manual review.')
    page = await http.request('GET', '/v1/deals', params={'personId': int(person_id), 'pipelineId': int(pipeline_id), 'includeArchived': 1, 'limit': 100})
    if (page.get('_metadata') or {}).get('nextLink'):
        raise CrmError('Too many matching deals; review this contact in Follow Up Boss.')
    # personId is the documented FUB filter; independently enforce the board.
    rows = [d for d in page.get('deals', []) if str(d.get('pipelineId')) == pipeline_id]
    if len(rows) > 1:
        raise CrmError('Multiple deals on this board; choose the intended deal manually.')
    if rows:
        deal = rows[0]
        if str(deal.get('status', 'Active')).casefold() != 'active' or str(deal.get('stageId')) not in stages or stages[str(deal.get('stageId'))].get('closedStage'):
            raise CrmError('The existing deal is closed or unavailable; manual review required.')
        if str(deal.get('stageId')) == stage_id:
            return {'id': str(deal['id']), 'stage_id': stage_id, 'unchanged': True}
        order = lambda s: float(s.get('orderWeight') or 0)
        if order(stages[str(deal['stageId'])]) > order(stages[stage_id]):
            return {'id': str(deal['id']), 'unchanged': True, 'reason': 'A later deal stage is preserved'}
        result = await http.request('PUT', f"/v1/deals/{int(deal['id'])}", json={'stageId': int(stage_id)})
    else:
        result = await http.request('POST', '/v1/deals', json={'name': f'BlackSync · {name}'[:120], 'stageId': int(stage_id), 'peopleIds': [int(person_id)]})
    result = result.get('deal', result)
    if not result.get('id'):
        raise CrmError('The CRM did not confirm a deal ID; review before retrying.')
    check = await http.request('GET', f"/v1/deals/{int(result['id'])}")
    check = check.get('deal', check)
    if str(check.get('stageId')) != stage_id or str(check.get('pipelineId')) != pipeline_id:
        raise CrmError('The CRM did not confirm the requested deal stage; review before retrying.')
    return {'id': str(check['id']), 'pipeline_id': pipeline_id, 'stage_id': stage_id}
