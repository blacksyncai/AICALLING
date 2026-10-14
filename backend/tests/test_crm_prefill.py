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
