"""BlackSync Cloud Radar reads, matching the Cloud CRM's REST entities and call-note format."""
import datetime as dt
import json
import re
from collections import defaultdict
from app.services.crm.http import CrmError
from app.services.crm.radar import Signals
from app.services.crm.providers import _parse_time

UTC = dt.timezone.utc


async def collection(http, resource, *, cap=5000, filters=None, metadata=False, order_by=None, cursor=None, state=None):
    rows, seen = [], set()
    for _ in range(100):
        params = {"limit": min(200, cap - len(rows))}
        if cursor:
            params["starting_after"] = cursor
        if order_by:
            params["order_by"] = order_by
        if filters:
            params["filter"] = filters
        result = await http.request("GET", f"/rest/{resource}", params=params)
        data = result.get("data") if isinstance(result, dict) else None
        batch = data if metadata else data.get(resource) if isinstance(data, dict) else None
        # Older metadata responses may use the object name as a wrapper.
        if metadata and isinstance(batch, dict):
            batch = batch.get(resource.split('/')[-1])
        if not isinstance(batch, list) or any(not isinstance(r, dict) or not r.get("id") for r in batch):
            raise CrmError(f"BlackSync Cloud returned an invalid {resource} collection.")
        rows.extend(batch)
        info = result.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            if state is not None: state["next"] = None
            return rows[:cap], True
        next_cursor = info.get("endCursor")
        if not batch or not next_cursor or next_cursor in seen:
            raise CrmError(f"BlackSync Cloud returned an invalid {resource} cursor.")
        if len(rows) >= cap:
            if state is not None: state["next"] = next_cursor
            return rows[:cap], False
        seen.add(next_cursor)
        cursor = next_cursor
    return rows[:cap], False


async def related(http, resource, field, ids):
    rows, complete, seen = [], True, set()
    ids = list(set(str(v) for v in ids if v))
    for index in range(0, len(ids), 60):
        batch, done = await collection(http, resource, filters=f'{field}[in]:{json.dumps(ids[index:index+60])}')
        complete &= done
        for row in batch:
            if row['id'] not in seen:
                rows.append(row)
                seen.add(row['id'])
    return rows, complete


def activity(signal, notes, complete):
    signal.calls_known = complete
    signal.extra["activity_incomplete"] = not complete
    touches = []
    communication = False
    for note in notes:
        title = str(note.get('title') or '')
        when = _parse_time(note.get('createdAt'))
        if not when or title == 'Imported from Close':
            continue
        call = re.match(r'^(Inbound|Outbound) call\s*·\s*([\d:]+)\s*·\s*(.+)$', title, re.I)
        inbound = title.casefold().startswith(('email received:', 'text received'))
        communication |= bool(call) or title.casefold().startswith(("email received:", "email sent:", "text received", "text sent"))
        if call:
            direction, _, outcome = call.groups()
            connected = outcome.strip().casefold() in ('answered', 'connected', 'completed')
            if direction.casefold() == 'outbound':
                signal.calls += 1
                if not signal.last_call_at or when > signal.last_call_at:
                    signal.last_call_at, signal.last_call_result = when, outcome
            if connected:
                signal.connected_calls += 1
            inbound = direction.casefold() == 'inbound' and connected
        if inbound and (not signal.last_inbound_at or when > signal.last_inbound_at):
            signal.last_inbound_at, signal.inbound_kind = when, title.split('·')[0].strip()
        touches.append(when)
    signal.last_activity_at = max(touches) if touches else None
    signal.contacted = communication if complete else True if communication else None


async def snapshot(provider, http, config, *, history=True, cap=500, cursor=None, depth="recent", state=None):
    people, people_complete = await collection(http, 'people', cap=cap, cursor=cursor, state=state,
        order_by="createdAt[Asc]" if depth == "old" else "createdAt[Desc]")
    companies, _ = await related(http, 'companies', 'id', [p.get('companyId') for p in people])
    company_by_id = {r['id']: r for r in companies}
    opportunities, deals_complete = await related(http, 'opportunities', 'companyId', company_by_id)
    direct_deals, direct_complete = await related(http, 'opportunities', 'pointOfContactId', [p['id'] for p in people])
    opportunities = list({r['id']: r for r in opportunities + direct_deals}.values())
    targets, targets_complete = ([], True)
    notes, notes_complete = ([], True)
    if history:
        person_targets, pc = await related(http, 'noteTargets', 'targetPersonId', [p['id'] for p in people])
        company_targets, cc = await related(http, 'noteTargets', 'targetCompanyId', company_by_id)
        targets = list({r['id']: r for r in person_targets + company_targets}.values())
        targets_complete = pc and cc
        notes, notes_complete = await related(http, 'notes', 'id', [r.get('noteId') for r in targets])
    note_by_id = {r['id']: r for r in notes}
    notes_complete &= all(t.get('noteId') in note_by_id for t in targets)
    if state is not None and not (targets_complete and notes_complete):
        state.setdefault('warnings', []).append('Some CRM activity history was incomplete; those contacts are not treated as never contacted.')
    person_notes, company_notes = defaultdict(dict), defaultdict(dict)
    for target in targets:
        note = note_by_id.get(target.get('noteId'))
        if not note:
            continue
        if target.get('targetPersonId'):
            person_notes[target['targetPersonId']][note['id']] = note
        if target.get('targetCompanyId'):
            company_notes[target['targetCompanyId']][note['id']] = note
    out = []
    for person in people:
        contact = provider._contact(person)
        if not contact.phone:
            continue
        company = company_by_id.get(person.get('companyId'), {})
        status = str(company.get('leadStatus') or '').replace('_', ' ')
        s = Signals(contact.external_id, contact.name, contact.phone, email=contact.email,
                    company=str(company.get('name') or ''), created_at=_parse_time(company.get("createdAt")) or contact.created_at,
                    status=status, pond=str(company.get('leadPond') or ''), tags=contact.tags,
                    dnc=contact.dnc or status.casefold() in ('dnc', 'do not call', 'do not contact'), calls_known=False)
        if history:
            own_notes = {**company_notes.get(person.get('companyId'), {}), **person_notes.get(person['id'], {})}
            activity(s, list(own_notes.values()), targets_complete and notes_complete)
        deals = [r for r in opportunities if r.get('pointOfContactId') == person['id'] or
                 (person.get('companyId') and r.get('companyId') == person['companyId'])]
        active = [r for r in deals if str(r.get('stage') or '').upper() not in ('CLOSED_WON', 'CLOSED_LOST', 'WON', 'LOST')]
        if active:
            # An old updatedAt proves no field (including the stage) changed since then.
            deal = min(active, key=lambda r: str(r.get('updatedAt') or '9999'))
            s.deal_stage = str(deal.get('stage') or '')
            s.deal_open = True
            s.deal_updated_at = _parse_time(deal.get('updatedAt'))
        else:
            won = [r for r in deals if str(r.get('stage') or '').upper() in ('CLOSED_WON', 'WON')]
            if won:
                s.won_at = max(filter(None, [_parse_time(r.get('updatedAt')) for r in won]), default=None)
        s.extra.update(cloud_person=person, cloud_company=company, cloud_deals=deals)
        out.append(s)
    return out, people_complete and deals_complete and direct_complete


async def scan(provider, http, config, limit=500, state=None, depth="recent", cursor=None):
    signals, complete = await snapshot(provider, http, config, cap=min(limit, 50 if depth == "quick" else 500),
                                       cursor=cursor, depth=depth, state=state)
    from app.services.crm import cloud_views
    await cloud_views.apply_pipeline_stages(http, signals, state)
    if state is not None:
        state['coverage'] = 'complete contact batch' if complete else 'bounded contact batch'
    return signals


async def options(provider, http, config):
    signals, complete = await snapshot(provider, http, config, history=False, cap=5000)
    if not complete:
        raise CrmError('Cloud list catalog exceeds the safe read limit. Use a paged Radar scan instead.')
    stages = sorted({s.status for s in signals if s.status})
    ponds = sorted({s.pond for s in signals if s.pond})
    deal_stages = sorted({str(d.get('stage')) for s in signals for d in s.extra['cloud_deals'] if d.get('stage')})
    out = {'pond': [{'value': x, 'label': x} for x in ponds],
            'stage': [{'value': x, 'label': x} for x in stages], 'source': [],
            'deal': [{'value': x, 'label': x.replace('_', ' ').title()} for x in deal_stages],
            'list': [{'value': x, 'label': label} for x, label in (
                ('all', 'All leads'), ('never-called', 'Never called'), ('gone-quiet', 'No touch in 7 days'),
                ('with-deals', 'Leads with deals'))]}
    from app.services.crm import cloud_views
    views, fields = await cloud_views.catalog(http)
    for view, obj in views:
        out['list'].append({'value': 'view:' + view['id'], 'label': str(view.get('name') or view['id'])})
        field = fields.get(view.get('mainGroupByFieldMetadataId'))
        if obj['nameSingular'] == 'opportunity' and field:
            for option in field.get('options') or []:
                if option.get('value'):
                    token = json.dumps([view['id'], field['id'], option['value']], separators=(',', ':'))
                    out['deal'].append({'value': token, 'label': f"{view.get('name') or 'Pipeline'} · {option.get('label') or option['value']}"})
    return out


async def segment(provider, http, config, kind, value):
    signals, complete = await snapshot(provider, http, config, history=kind == 'list', cap=5000)
    if not complete:
        raise CrmError('This Cloud list exceeds the safe read limit. Use a paged Radar scan instead; no partial list was opened.')
    now = dt.datetime.now(UTC)
    if (kind == 'list' and value.startswith('view:')) or (kind == 'deal' and value.startswith('[')):
        from app.services.crm import cloud_views
        views, fields = await cloud_views.catalog(http)
        stage_field = stage_value = None
        if kind == 'list':
            view_id = value[5:]
        else:
            try:
                view_id, stage_field, stage_value = json.loads(value)
            except (ValueError, TypeError):
                raise CrmError('Invalid Cloud pipeline selection.')
        selected = next(((v, obj) for v, obj in views if v['id'] == view_id), None)
        if not selected:
            raise CrmError('That Cloud view no longer exists. Refresh the list picker.')
        view, obj = selected
        if stage_field and view.get('mainGroupByFieldMetadataId') != stage_field:
            raise CrmError('The pipeline stage field changed. Refresh the list picker.')
        field = fields.get(stage_field) if stage_field else None
        if stage_field and (not field or stage_value not in [o.get('value') for o in field.get('options') or []]):
            raise CrmError('That pipeline stage no longer exists.')
        return [s for s in signals if any(cloud_views.matches(view, fields, row) and
                (not field or row.get(field['name']) == stage_value)
                for row in cloud_views.record_for(s, obj['nameSingular']))]
    def matches(s):
        if kind == 'pond': return s.pond == value
        if kind == 'stage': return s.status == value
        if kind == 'deal': return any(str(d.get('stage') or '') == value for d in s.extra['cloud_deals'])
        if kind != 'list': raise CrmError('Choose a Cloud pond, lead status, deal stage or list.')
        if value == 'all': return True
        if value == 'never-called': return s.calls_known and s.calls == 0
        if value == 'gone-quiet': return s.calls_known and (not s.last_activity_at or (now-s.last_activity_at).days >= 7)
        if value == 'with-deals': return bool(s.extra['cloud_deals'])
        raise CrmError('That BlackSync Cloud list is not supported. Refresh the list picker.')
    return [s for s in signals if matches(s)]
