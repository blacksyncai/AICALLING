import asyncio
import uuid
import pytest
from sqlalchemy import select
from tests.test_radar_automations import crm


@pytest.fixture
def launch_case(client, crm, agent_id, monkeypatch):
    from app.database import AsyncSessionLocal
    from app.models.crm import CrmScan, CrmConnection
    from app.models.campaign import Campaign
    from app.models.lead import Lead
    from app.services.crm import sync
    async def prefill(*args):
        pass
    monkeypatch.setattr(sync, 'prefill_fields', prefill)
    async def setup():
        async with AsyncSessionLocal() as db:
            org = uuid.UUID(crm['org_id'])
            conn = await db.scalar(select(CrmConnection).where(CrmConnection.org_id == org, CrmConnection.provider == 'followupboss'))
            campaign = Campaign(org_id=org, agent_id=uuid.UUID(agent_id), name='Existing campaign', status='paused', timezone='America/Los_Angeles', total_targets=2)
            other = Campaign(org_id=org, agent_id=uuid.UUID(agent_id), name='Other', status='draft')
            db.add_all([campaign, other]); await db.flush()
            prefix = '+1415' + str(uuid.uuid4().int % 1000000).zfill(6)
            rows = [Lead(org_id=org, name='Already here', phone=prefix+'1', campaign_id=campaign.id, status='completed', attempts=3),
                    Lead(org_id=org, name='Other campaign', phone=prefix+'2', campaign_id=other.id),
                    Lead(org_id=org, name='Suppressed', phone=prefix+'3', do_not_call=True),
                    Lead(org_id=org, name='Unassigned', phone=prefix+'4')]
            db.add_all(rows)
            items = [{'external_id':str(i), 'name':str(i), 'phone':prefix+str(i)} for i in range(1, 6)]
            scan = CrmScan(org_id=org, connection_id=conn.id, result={'plays':[{'key':'cold', 'title':'Cold contacts', 'why':'Testing', 'items':items}]})
            db.add(scan); await db.commit()
            return {'scan':str(scan.id), 'campaign':str(campaign.id), 'other':str(other.id), 'agent':agent_id, 'prefix':prefix}
    return asyncio.run(setup())


def launch(client, case, **overrides):
    body = {'play':'cold', 'agent_id':case['agent'], 'mode':'campaign', 'campaign_id':case['campaign']}
    body.update(overrides)
    return client.post(f"/api/radar/scans/{case['scan']}/launch", json=body)


def test_append_preserves_settings_skips_assigned_and_is_repeat_safe(client, launch_case):
    case = launch_case
    first = launch(client, case)
    assert first.status_code == 200, first.text
    assert first.json()['contacts'] == 2 and first.json()['skipped'] == 2
    second = launch(client, case)
    assert second.status_code == 200 and second.json()['contacts'] == 0
    from app.database import AsyncSessionLocal
    from app.models.campaign import Campaign
    from app.models.lead import Lead
    async def verify():
        async with AsyncSessionLocal() as db:
            c = await db.get(Campaign, uuid.UUID(case['campaign']))
            assert c.status == 'paused' and c.timezone == 'America/Los_Angeles' and c.total_targets == 4
            leads = (await db.scalars(select(Lead).where(Lead.phone.like(case['prefix']+'%')))).all()
            by_phone = {l.phone:l for l in leads}
            assert by_phone[case['prefix']+'1'].attempts == 3
            assert by_phone[case['prefix']+'1'].status == 'completed'
            assert str(by_phone[case['prefix']+'2'].campaign_id) == case['other']
            assert by_phone[case['prefix']+'3'].campaign_id is None
    asyncio.run(verify())


@pytest.mark.parametrize('status,direction', [('cancelled','outbound'), ('completed','outbound'), ('draft','inbound')])
def test_rejects_ineligible_campaign(client, launch_case, status, direction):
    from app.database import AsyncSessionLocal
    from app.models.campaign import Campaign
    async def update():
        async with AsyncSessionLocal() as db:
            c = await db.get(Campaign, uuid.UUID(launch_case['campaign']))
            c.status, c.direction = status, direction
            await db.commit()
    asyncio.run(update())
    assert launch(client, launch_case).status_code == 400


def test_unknown_campaign_and_agent_mismatch(client, launch_case):
    assert launch(client, launch_case, campaign_id=str(uuid.uuid4())).status_code == 404
    assert launch(client, launch_case, agent_id=str(uuid.uuid4())).status_code == 400
    assert launch(client, launch_case, mode='pipeline').status_code == 400


def test_subset_only(client, launch_case):
    r = launch(client, launch_case, external_ids=['4'])
    assert r.status_code == 200 and r.json()['contacts'] == 1


def test_new_campaign_option_still_creates_draft(client, launch_case):
    r = launch(client, launch_case, campaign_id=None, external_ids=['5'])
    assert r.status_code == 200 and r.json()['contacts'] == 1
    assert r.json()['campaign_id'] != launch_case['campaign']
    assert r.json()['existing_campaign'] is False


def test_other_account_campaign_is_hidden(client, launch_case):
    from app.database import AsyncSessionLocal
    from app.models.campaign import Campaign
    from app.models.account import Organization
    async def setup():
        async with AsyncSessionLocal() as db:
            org = Organization(name='Other tenant')
            db.add(org); await db.flush()
            c = Campaign(org_id=org.id, name='Private campaign', status='draft')
            db.add(c); await db.commit()
            return str(c.id)
    key = asyncio.run(setup())
    assert launch(client, launch_case, campaign_id=key).status_code == 404
