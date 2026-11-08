import asyncio
import datetime as dt
import uuid

import pytest
from app.services.crm import radar_history, radar_lists
from app.services.crm.providers import Provider, Contact
from app.services.crm.radar import Signals
from app.services.crm.http import CrmError
from tests.test_radar_automations import crm

NOW = dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc)


def test_shared_groups_use_evidence_and_keep_unknown_separate():
    ago = lambda days: NOW - dt.timedelta(days=days)
    signals = [
        Signals('hot', 'Hot', '+14155550101', calls_known=False, last_inbound_at=ago(1)),
        Signals('never', 'Never', '+14155550102', created_at=ago(2), calls_known=False, contacted=False),
        Signals('tried', 'Tried', '+14155550103', calls_known=False, calls=2, last_call_at=ago(4)),
        Signals('cold', 'Cold', '+14155550104', calls_known=False, connected_calls=1, last_call_at=ago(40)),
        Signals('stuck', 'Stuck', '+14155550105', calls_known=False, deal_open=True, deal_stage='Proposal', deal_updated_at=ago(25)),
        Signals('contacted', 'Contacted', '+14155550106', calls_known=False, contacted=True),
        Signals('unknown', 'Unknown', '+14155550107', calls_known=False, created_at=ago(500)),
        Signals('dnc', 'DNC', '+14155550108', dnc=True),
    ]
    result = radar_history.build(signals, NOW)
    mapping = {play['key']: [x['external_id'] for x in play['items']] for play in result['plays']}
    assert mapping['hot'] == ['hot']
    assert mapping['never_called'] == ['never']
    assert mapping['unreached'] == ['tried']
    assert mapping['went_cold'] == ['cold']
    assert mapping['stuck'] == ['stuck']
    assert mapping['contacted'] == ['contacted']
    assert mapping['unknown'] == ['unknown']
    assert mapping['revive'] == []  # Old creation date alone is not quiet-time evidence.
    assert all('dnc' not in ids for ids in mapping.values())


class FilterCRM(Provider):
    key, name = 'filters_test', 'Filtered CRM'

    def __init__(self):
        self.filters_seen = None

    async def import_options(self, http, config):
        return [{'key': 'tags', 'label': 'Tags', 'type': 'multi', 'options': [{'value': 'buyers', 'label': 'Buyers'}]},
                {'key': 'pipeline', 'label': 'Pipeline', 'type': 'pipeline', 'stage_key': 'opp_status',
                 'options': [{'value': 'sales', 'label': 'Sales', 'stages': [{'value': 'proposal', 'label': 'Proposal'}]}]}]

    async def list_contacts(self, http, config, limit=500, since=None, filters=None):
        self.filters_seen = filters
        return [Contact(external_id='1', name='Buyer', phone='+14155550101')]


def test_generic_lists_forward_actual_provider_filters_and_reject_stale_ids():
    p = FilterCRM()
    async def check():
        options, _ = await radar_lists.catalog(p, None, {})
        assert options['list'][0]['value'] == radar_lists.ALL
        buyers = next(x for x in options['list'] if x['label'] == 'Tags · Buyers')
        signals = await radar_lists.read(p, None, {}, 'list', buyers['value'])
        assert signals[0].external_id == '1' and p.filters_seen == {'tags': ['buyers']}
        stage = next(x for x in options['list'] if x['label'] == 'Sales · Proposal')
        await radar_lists.read(p, None, {}, 'list', stage['value'])
        assert p.filters_seen == {'pipeline': ['sales'], 'opp_status': ['proposal']}
        with pytest.raises(CrmError, match='no longer available'):
            await radar_lists.read(p, None, {}, 'list', 'contacts:forged')
    asyncio.run(check())


def test_saved_call_history_is_tenant_and_phone_scoped(client, crm, agent_id):
    from app.database import AsyncSessionLocal
    from app.models.lead import Lead
    from app.models.call_log import CallLog

    async def check():
        async with AsyncSessionLocal() as db:
            org_id = uuid.UUID(crm['org_id'])
            lead = Lead(org_id=org_id, name='Matched', phone='+14155550111', crm_refs={'blacksync_cloud': 'cloud-1'})
            db.add(lead)
            await db.flush()
            for phone, kind in [('+14155550111', 'outbound'), ('+14155550199', 'outbound'), ('+14155550111', 'web')]:
                db.add(CallLog(org_id=org_id, agent_id=uuid.UUID(agent_id), lead_id=lead.id,
                    livekit_room_name=f"test-{uuid.uuid4()}", call_type=kind, status='completed', outcome='voicemail', duration_seconds=8,
                    to_phone=phone, from_phone='+18005550123', started_at=NOW-dt.timedelta(days=4), ended_at=NOW-dt.timedelta(days=4)))
            await db.commit()
            signal = Signals('cloud-1', 'Matched', '+14155550111', calls_known=False, contacted=False)
            await radar_history.enrich(db, org_id, 'blacksync_cloud', [signal])
            assert signal.calls == 1 and signal.connected_calls == 0
            assert signal.contacted is None
            result = radar_history.build([signal], NOW)
            tried = next(p for p in result['plays'] if p['key'] == 'unreached')
            assert tried['count'] == 1 and 'BlackSync call history' in tried['items'][0]['reason']
            stranger = Signals('cloud-1', 'Other phone', '+14155550112', calls_known=False)
            await radar_history.enrich(db, org_id, 'blacksync_cloud', [stranger])
            assert stranger.calls == 0
            await radar_history.enrich(db, uuid.uuid4(), 'blacksync_cloud', [stranger])
            assert stranger.calls == 0
    asyncio.run(check())
