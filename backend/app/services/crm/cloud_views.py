"""Read Cloud's real saved views and pipeline stage fields; never widen an unsupported filter."""
import json
from app.services.crm.http import CrmError
from app.services.crm.cloud_radar import collection


async def catalog(http):
    objects, objects_complete = await collection(http, 'metadata/objects', metadata=True)
    views, views_complete = await collection(http, 'metadata/views', metadata=True)
    if not objects_complete or not views_complete:
        raise CrmError('Too many Cloud views to load safely; narrow the CRM catalog.')
    by_id = {r['id']: r for r in objects if r.get('nameSingular') in ('person', 'company', 'opportunity')}
    fields = {f['id']: f for obj in by_id.values() for f in obj.get('fields') or []}
    return [(v, by_id[v['objectMetadataId']]) for v in views if v.get('objectMetadataId') in by_id], fields


def _value(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            pass
    return value


def matches(view, fields, row):
    def atom(f):
        field = fields.get(f.get('fieldMetadataId'))
        if not field or f.get('relationTargetFieldMetadataId'):
            raise CrmError('This saved view uses a relation filter Radar cannot safely apply yet.')
        actual = row.get(field['name'])
        if f.get('subFieldName'):
            actual = actual.get(f['subFieldName']) if isinstance(actual, dict) else None
        expected = _value(f.get('value'))
        choices = expected if isinstance(expected, list) else [expected]
        op = f.get('operand')
        if op == 'IS': return actual in choices if not isinstance(actual, list) else any(value in choices for value in actual)
        if op == 'IS_NOT': return actual not in choices if not isinstance(actual, list) else not any(value in choices for value in actual)
        if op == 'IS_EMPTY': return actual in (None, '', [])
        if op in ('IS_NOT_EMPTY', 'IS_NOT_NULL'): return actual not in (None, '', [])
        if op == 'CONTAINS': return str(expected or '').casefold() in str(actual or '').casefold()
        if op == 'DOES_NOT_CONTAIN': return str(expected or '').casefold() not in str(actual or '').casefold()
        if op in ('GREATER_THAN_OR_EQUAL', 'LESS_THAN_OR_EQUAL'):
            if actual is None: return False
            try:
                return float(actual) >= float(expected) if op == 'GREATER_THAN_OR_EQUAL' else float(actual) <= float(expected)
            except (TypeError, ValueError):
                return False
        raise CrmError(f'This Cloud saved view uses an unsupported {op} filter. No unfiltered list was substituted.')

    filters = view.get('viewFilters') or []
    groups = {g['id']: g for g in view.get('viewFilterGroups') or []}
    for group in groups.values():
        ancestors = {group['id']}
        parent = group.get('parentViewFilterGroupId')
        while parent is not None:
            if parent not in groups:
                raise CrmError('Cloud saved view has a missing parent filter group.')
            if parent in ancestors:
                raise CrmError('Cloud returned a cyclic filter group.')
            ancestors.add(parent)
            parent = groups[parent].get('parentViewFilterGroupId')
    def group_result(group_id, depth=0):
        if depth > 10: raise CrmError('Cloud returned a cyclic filter group.')
        values = [atom(f) for f in filters if f.get('viewFilterGroupId') == group_id]
        values += [group_result(g['id'], depth+1) for g in groups.values() if g.get('parentViewFilterGroupId') == group_id]
        if group_id is None: return all(values)
        op = groups[group_id].get('logicalOperator')
        if op == 'AND': return all(values)
        if op == 'OR': return any(values)
        if op == 'NOT' and len(values) == 1: return not values[0]
        raise CrmError('Cloud returned an unsupported filter group. No unfiltered list was substituted.')
    if any(f.get('viewFilterGroupId') not in (None, *groups) for f in filters):
        raise CrmError('Cloud saved view has a missing filter group.')
    needle = str(view.get('anyFieldFilterValue') or '').strip().casefold()
    return group_result(None) and (not needle or needle in json.dumps(row).casefold())


def record_for(signal, object_name):
    if object_name == 'person': return [signal.extra['cloud_person']]
    if object_name == 'company': return [signal.extra['cloud_company']]
    return signal.extra['cloud_deals']


async def apply_pipeline_stages(http, signals, state=None):
    try:
        views, fields = await catalog(http)
    except CrmError as exc:
        if state is None:
            raise
        state.setdefault('warnings', []).append('Pipeline metadata could not be read; stage-based grouping is unavailable. ' + str(exc))
        return
    for s in signals:
        candidates = []
        for view, obj in views:
            field = fields.get(view.get('mainGroupByFieldMetadataId'))
            if obj['nameSingular'] != 'opportunity' or not field:
                continue
            options = {str(o.get('value')): str(o.get('label') or o.get('value')) for o in field.get('options') or []}
            for deal in s.extra['cloud_deals']:
                try:
                    applies = matches(view, fields, deal)
                except CrmError:
                    continue
                if applies and deal.get(field['name']) is not None:
                    value = str(deal[field['name']])
                    candidates.append((deal, value, options.get(value, value)))
        if not candidates:
            continue
        active = [d for d in candidates if d[1].upper() not in ('WON', 'LOST', 'CLOSED_WON', 'CLOSED_LOST')]
        s.deal_open = bool(active)
        if active:
            deal, _, label = min(active, key=lambda d: str(d[0].get('updatedAt') or '9999'))
            s.deal_stage = label
            from app.services.crm.providers import _parse_time
            s.deal_updated_at = _parse_time(deal.get('updatedAt'))
        elif any(value.upper() in ('WON', 'CLOSED_WON') for _, value, _ in candidates):
            from app.services.crm.providers import _parse_time
            s.won_at = max(filter(None, [_parse_time(d.get('updatedAt')) for d, value, _ in candidates
                                          if value.upper() in ('WON', 'CLOSED_WON')]), default=None)
