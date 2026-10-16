import asyncio
import types

from app.services.crm import sync
from app.services.crm.variables import needs_prefill, visible_fields


class FakeProvider:
    can_map_fields = True

    async def person_fields(self, http, config, ref):
        return {"first_name": "Yanika", "address": "12 Oak St", "city": "Oakland", "stage": "Lead",
                "unit_count": "8"}


def test_prefill_puts_script_variables_and_csv_like_columns_on_contacts(monkeypatch):
    monkeypatch.setattr(sync, "http_for", lambda conn: (FakeProvider(), None))
    conn = types.SimpleNamespace(provider="followupboss", config={}, settings={"var_maps": {"a1": {"units": "unit_count"}}})
    agent = types.SimpleNamespace(id="a1", system_prompt="Ask about {{property_address}} and the {{units}} units.",
                                  first_message="Hey {{name}}", voicemail_message="", knowledge_base="")
    lead = types.SimpleNamespace(crm_refs={"followupboss": "42"}, custom_fields={"crm": "Follow Up Boss"})
    assert needs_prefill(lead)

    assert asyncio.run(sync.prefill_fields(conn, agent, [lead])) == 1
    shown = visible_fields(lead.custom_fields)
    assert shown["property_address"] == "12 Oak St" and shown["units"] == "8"
    assert shown["city"] == "Oakland" and shown["stage"] == "Lead"
    assert "crm" not in shown and "crm_fields" not in shown and "name" not in shown
    assert not needs_prefill(lead)


def test_radar_status_tags_campaign_calls_and_verified(client):
    import uuid

    from app.database import AsyncSessionLocal
    from app.models.call_log import CallLog
    from app.models.campaign import Campaign
    from app.models.lead import Lead
    from app.routers.radar import _blacksync_status

    org_id = uuid.UUID(client.get("/api/auth/me").json()["org"]["id"])

    async def scenario():
        async with AsyncSessionLocal() as db:
            camp = Campaign(id=uuid.uuid4(), org_id=org_id, name="Old leads", status="draft")
            db.add(camp)
            a = Lead(id=uuid.uuid4(), org_id=org_id, name="A", phone="+14155550991", crm_refs={"followupboss": "7"},
                     campaign_id=camp.id)
            b = Lead(id=uuid.uuid4(), org_id=org_id, name="B", phone="+14155550992", crm_refs={"followupboss": "8"})
            db.add_all([a, b])
            await db.flush()
            for lead, outcome in ((a, "voicemail"), (a, "interested"), (b, "no_answer")):
                db.add(CallLog(org_id=org_id, lead_id=lead.id, livekit_room_name="r", status="completed", outcome=outcome))
            await db.commit()
            return await _blacksync_status(db, org_id, "followupboss")

    st = asyncio.run(scenario())
    assert st["7"]["campaign"] == "Old leads" and st["7"]["calls"] == 2 and st["7"]["voicemails"] == 1
    assert not st["7"]["verified"] and not st["8"]["verified"] and st["8"]["last_outcome"] == "no_answer"


def test_csv_values_survive_crm_linking_and_repeated_prefill(monkeypatch):
    from app.services.contacts import parse_contacts_csv
    from app.agent.runtime import lead_variables, render_vars
    from app.services.crm.variables import apply

    row=parse_contacts_csv('name,phone,property address,city,unit count\nJames,4155550123,99 CSV Property Rd,CSV City,0')[0][0]
    lead=types.SimpleNamespace(**row,crm_refs={})
    agent=types.SimpleNamespace(id='a1',system_prompt='Discuss {{property_address}} in {{city}} with {{unit_count}} units.',first_message='Hi {{name}}',voicemail_message='',knowledge_base='')
    original=lead_variables(lead)
    conn=types.SimpleNamespace(provider='followupboss',config={},settings={})
    monkeypatch.setattr(sync,'http_for',lambda conn:(FakeProvider(),None))
    lead.crm_refs={'followupboss':'11204'}
    for _ in range(3):
        asyncio.run(sync.prefill_fields(conn,agent,[lead]))
        values=apply(lead_variables(lead),lead,agent,[conn])
        for key in ('name','property_address','city','unit_count'):
            assert values[key]==original[key]
        assert '99 CSV Property Rd' in render_vars(agent.system_prompt,values)
        assert 'crm_variable_values' not in visible_fields(lead.custom_fields)


def test_csv_values_survive_dial_time_crm_overlay_and_explicit_mapping_still_wins():
    from app.services.crm.variables import apply
    from app.agent.runtime import lead_variables
    lead=types.SimpleNamespace(name='James',phone='+14155550123',company='',email='',role='',custom_fields={
        'property_address':'99 CSV Property Rd','units':0,'active':False,
        'crm_fields':{'followupboss':{'address':'12 Mailing Ave','unit_count':'8','active':'yes'}}})
    agent=types.SimpleNamespace(id='a1',system_prompt='{{property_address}} {{units}} {{active}}',first_message='',voicemail_message='',knowledge_base='')
    conn=types.SimpleNamespace(provider='followupboss',settings={})
    values=apply(lead_variables(lead),lead,agent,[conn])
    assert values['property_address']=='99 CSV Property Rd' and values['units']==0 and values['active'] is False
    conn.settings={'var_maps':{'a1':{'property_address':'address','units':'unit_count'}}}
    values=apply(lead_variables(lead),lead,agent,[conn])
    assert values['property_address']=='12 Mailing Ave' and values['units']=='8'


def test_known_crm_derived_values_refresh_but_later_csv_edits_are_preserved(monkeypatch):
    from app.services.crm.variables import apply
    from app.agent.runtime import lead_variables
    conn=types.SimpleNamespace(provider='followupboss',config={},settings={})
    agent=types.SimpleNamespace(id='a1',system_prompt='{{property_address}}',first_message='',voicemail_message='',knowledge_base='')
    lead=types.SimpleNamespace(name='James',phone='',company='',email='',role='',crm_refs={'followupboss':'91'},custom_fields={})
    monkeypatch.setattr(sync,'http_for',lambda conn:(FakeProvider(),None))
    asyncio.run(sync.prefill_fields(conn,agent,[lead]))
    assert lead.custom_fields['property_address']=='12 Oak St'
    lead.custom_fields['crm_fields']['followupboss']['address']='Updated CRM address'
    assert apply(lead_variables(lead),lead,agent,[conn])['property_address']=='Updated CRM address'
    lead.custom_fields['property_address']='New CSV property'
    asyncio.run(sync.prefill_fields(conn,agent,[lead]))
    assert apply(lead_variables(lead),lead,agent,[conn])['property_address']=='New CSV property'
