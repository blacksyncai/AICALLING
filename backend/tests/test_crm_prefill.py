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
