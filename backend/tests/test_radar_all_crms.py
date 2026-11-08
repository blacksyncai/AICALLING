import asyncio
import uuid

import pytest
from app.services.crm.providers import Provider, Contact, PROVIDERS
from app.services.crm.radar_discovery import capabilities, contact_signals
from app.services.crm.radar import build_plays, build_segment
from tests.test_radar_automations import crm


class FutureCRM(Provider):
    key, name = "future_test_crm", "Future CRM"

    async def list_contacts(self, http, config, limit=500, since=None, filters=None):
        assert limit == 500
        return [Contact(external_id="a", name="Available", phone="4155550101"),
                Contact(external_id="b", name="Suppressed", phone="4155550102", tags=["DNC"]),
                Contact(external_id="c", name="Local DNC", phone="4155550103"),
                Contact(external_id="d", name="Missing phone"),
                Contact(external_id="a", name="Duplicate", phone="+14155550101")]


def test_new_contact_adapter_inherits_radar_without_scan_flag():
    p = FutureCRM()
    assert not p.can_scan
    assert capabilities(p)["mode"] == "contacts"
    signals = asyncio.run(contact_signals(p, object(), {}))
    assert len(signals) == 3
    assert all(not s.calls_known for s in signals)
    assert not any(play["count"] for play in build_plays(signals)["plays"])
    result = build_segment(signals, "Contacts", "Review contacts")
    assert [r["external_id"] for r in result["plays"][0]["items"]] == ["a", "c"]
    assert result["plays"][0]["items"][0]["calls"] is None


def test_all_registered_crms_have_discovery_capabilities():
    for p in PROVIDERS.values():
        if p.category == "crm":
            result = capabilities(p)
            assert result["mode"] in ("activity", "contacts", "unavailable")
            if result["mode"] == "unavailable":
                assert result["reason"] and not result["can_scan"]
    assert capabilities(PROVIDERS["salesforce"])["mode"] == "contacts"
    assert capabilities(PROVIDERS["followupboss"])["mode"] == "activity"
    assert capabilities(PROVIDERS["realgeeks"])["mode"] == "unavailable"


@pytest.fixture
def future_connection(client, crm, monkeypatch):
    from app.database import AsyncSessionLocal
    from app.models.crm import CrmConnection
    from app.models.lead import Lead
    from app.services.crm import sync
    p = FutureCRM()
    monkeypatch.setitem(PROVIDERS, p.key, p)
    monkeypatch.setattr(sync, "http_for", lambda conn: (PROVIDERS[conn.provider], object()))

    async def setup():
        async with AsyncSessionLocal() as db:
            db.add(CrmConnection(org_id=uuid.UUID(crm["org_id"]), provider=p.key,
                                 account_label="Future account", method="native", secret_enc=""))
            db.add(Lead(org_id=uuid.UUID(crm["org_id"]), name="Suppressed", phone="+14155550103", do_not_call=True))
            db.add(CrmConnection(org_id=uuid.UUID(crm["org_id"]), provider="realgeeks",
                                 account_label="Push-only account", method="native", secret_enc=""))
            db.add(CrmConnection(org_id=uuid.UUID(crm["org_id"]), provider="slack",
                                 account_label="Alerts", method="native", secret_enc=""))
            await db.commit()
    asyncio.run(setup())
    return p


def test_radar_lists_all_crms_and_loads_real_contacts(client, future_connection):
    overview = client.get("/api/radar")
    assert overview.status_code == 200, overview.text
    crms = {r["provider"]: r for r in overview.json()["crms"]}
    assert crms[future_connection.key]["capabilities"]["mode"] == "contacts"
    assert crms["realgeeks"]["capabilities"]["mode"] == "unavailable"
    assert "slack" not in crms
    response = client.post(f"/api/radar/{future_connection.key}/scan")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["discovery_mode"] == "contacts" and result["next"] is None
    items = [item for play in result["plays"] for item in play["items"]]
    assert [r["external_id"] for r in items] == ["a"]
    assert next(p for p in result["plays"] if p["key"] == "unknown")["count"] == 1
    assert items[0]["calls"] is None and items[0]["last_touch"] is None
    assert client.post("/api/radar/realgeeks/scan").status_code == 400
    assert client.post(f"/api/radar/{future_connection.key}/scan?continue_from={result['id']}").status_code == 400
