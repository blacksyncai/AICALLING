"""Explicit contact-to-deal routing; never confuse deal stages with person stages."""
from app.services.crm.http import CrmError
from app.services.crm.fub_pipelines import get_pipeline


async def owner_ids(http, person_id):
    """Who a deal should be assigned to: the contact's agent, else the account the API key belongs to.
    Deals with no agent are hidden from Follow Up Boss's Deals board views."""
    person = await http.request('GET', f'/v1/people/{int(person_id)}', params={'fields': 'id,assignedUserId'})
    uid = person.get('assignedUserId')
    if not uid:
        uid = (await http.request('GET', '/v1/me')).get('id')
    return [int(uid)] if uid else []


TAG = 'BlackSync'


async def tag_person(http, person_id, tag=TAG):
    """Add a tag to the person, keeping their other tags. Returns True if it was added."""
    person = await http.request('GET', f'/v1/people/{int(person_id)}', params={'fields': 'id,tags'})
    tags = [t for t in person.get('tags') or [] if isinstance(t, str)]
    if any(t.casefold() == tag.casefold() for t in tags):
        return False
    await http.request('PUT', f'/v1/people/{int(person_id)}', json={'tags': [*tags, tag]})
    return True


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
        if not deal.get('users'):
            users = await owner_ids(http, person_id)
            if users:  # an earlier unassigned deal: give it an agent so it shows on the board
                await http.request('PUT', f"/v1/deals/{int(deal['id'])}", json={'userIds': users})
        if str(deal.get('stageId')) == stage_id:
            return {'id': str(deal['id']), 'stage_id': stage_id, 'unchanged': True}
        order = lambda s: float(s.get('orderWeight') or 0)
        if order(stages[str(deal['stageId'])]) > order(stages[stage_id]):
            return {'id': str(deal['id']), 'unchanged': True, 'reason': 'A later deal stage is preserved'}
        result = await http.request('PUT', f"/v1/deals/{int(deal['id'])}", json={'stageId': int(stage_id)})
    else:
        body = {'name': f'BlackSync · {name}'[:120], 'stageId': int(stage_id), 'peopleIds': [int(person_id)]}
        users = await owner_ids(http, person_id)
        if users:
            body['userIds'] = users
        result = await http.request('POST', '/v1/deals', json=body)
    result = result.get('deal', result)
    if not result.get('id'):
        raise CrmError('The CRM did not confirm a deal ID; review before retrying.')
    check = await http.request('GET', f"/v1/deals/{int(result['id'])}")
    check = check.get('deal', check)
    if str(check.get('stageId')) != stage_id or str(check.get('pipelineId')) != pipeline_id:
        raise CrmError('The CRM did not confirm the requested deal stage; review before retrying.')
    return {'id': str(check['id']), 'pipeline_id': pipeline_id, 'stage_id': stage_id}


async def in_pipeline(http, pipeline_id, stage_id="", cap=2000):
    """Active deals on one board (optionally one stage), newest first. Filters are also checked here."""
    from app.services.crm.providers import _fub_next
    if not str(pipeline_id).isascii() or not str(pipeline_id).isdigit():
        raise CrmError('Choose a numeric Follow Up Boss deal-pipeline ID.')
    params, out, req = {'pipelineId': int(pipeline_id), 'limit': 100}, [], None
    if stage_id:
        params['stageId'] = int(stage_id)
    req = ('/v1/deals', params)
    while req and len(out) < cap:
        page = await http.request('GET', req[0], params=req[1])
        rows = page.get('deals') or []
        out += [d for d in rows if str(d.get('pipelineId')) == str(pipeline_id)
                and (not stage_id or str(d.get('stageId')) == str(stage_id))
                and str(d.get('status') or 'Active').casefold() == 'active']
        req = _fub_next(page) if len(rows) >= 100 else None
    return out[:cap]


def people_ids(deals):
    """Person IDs on these deals, in order, once each."""
    seen, out = set(), []
    for d in deals:
        for p in d.get('people') or []:
            pid = str(p.get('id') or '') if isinstance(p, dict) else str(p)
            if pid.isdigit() and pid not in seen:
                seen.add(pid); out.append(pid)
        for pid in map(str, d.get('peopleIds') or []):
            if pid.isdigit() and pid not in seen:
                seen.add(pid); out.append(pid)
    return out


async def summary(http, pipeline_id, stage_id="", limit=25):
    """What the assistant reads: counts per stage and the first deals with their people."""
    from app.services.crm.fub_pipelines import get_pipeline
    pipe = await get_pipeline(http, pipeline_id)
    names = {str(s.get('id')): s.get('name') or str(s.get('id')) for s in pipe.get('stages') or []}
    if stage_id and stage_id not in names:
        raise CrmError('Choose a stage from this deal pipeline.')
    deals = await in_pipeline(http, pipeline_id, stage_id)
    counts = {names[k]: 0 for k in names if not stage_id or k == stage_id}
    for d in deals:
        label = names.get(str(d.get('stageId')), d.get('stageName') or str(d.get('stageId')))
        counts[label] = counts.get(label, 0) + 1
    rows = [{'id': str(d.get('id')), 'name': d.get('name') or '', 'stage': names.get(str(d.get('stageId')), d.get('stageName') or ''),
             'people': [{'id': str(p.get('id')), 'name': p.get('name') or ''} for p in d.get('people') or [] if isinstance(p, dict)],
             'updated': d.get('updated') or d.get('created') or ''} for d in deals[:limit]]
    return {'pipeline': {'id': str(pipe['id']), 'name': pipe.get('name') or ''}, 'total_active_deals': len(deals),
            'by_stage': counts, 'deals': rows, 'shown': len(rows),
            'scope': 'Active deals only; archived and deleted deals are not counted.'}


async def assign_unowned(http, pipeline_id):
    """Give every unassigned active deal on a board an agent (see owner_ids). Returns how many were fixed."""
    fixed = 0
    for d in await in_pipeline(http, pipeline_id):
        if d.get('users'):
            continue
        person = next((p.get('id') for p in d.get('people') or [] if isinstance(p, dict) and p.get('id')), None)
        users = await owner_ids(http, person) if person else []
        if users:
            await http.request('PUT', f"/v1/deals/{int(d['id'])}", json={'userIds': users})
            fixed += 1
    return fixed
