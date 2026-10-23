import json

from cryptography.fernet import Fernet

from app.agent.runtime import agent_to_runtime
from app.config import settings
from app.models.agent import Agent
from app.services import calendar


def test_agent_calcom_key_is_write_only(client, monkeypatch):
    monkeypatch.setattr(settings, "secrets_encryption_key", Fernet.generate_key().decode())
    a = client.post("/api/agents", json={"template": "blank"}).json()
    assert a["calcom_key_set"] is False
    r = client.patch(f"/api/agents/{a['id']}", json={
        "calcom_api_key": "cal_live_secret123", "calcom_event_type_id": " 4374694 ", "calendar_timezone": "America/New_York"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["calcom_key_set"] is True and body["calcom_event_type_id"] == "4374694"
    assert body["calendar_timezone"] == "America/New_York" and "cal_live_secret123" not in json.dumps(body)
    assert "cal_live_secret123" not in json.dumps(client.get(f"/api/agents/{a['id']}").json())

    bad = client.patch(f"/api/agents/{a['id']}", json={"calendar_timezone": "Mars/Base"})
    assert bad.status_code == 400

    cleared = client.patch(f"/api/agents/{a['id']}", json={"calcom_api_key": ""}).json()
    assert cleared["calcom_key_set"] is False


def test_runtime_includes_key_only_server_side(monkeypatch):
    monkeypatch.setattr(settings, "secrets_encryption_key", Fernet.generate_key().decode())
    from app.services.secret_store import encrypt_value

    agent = Agent(name="x", calcom_api_key_enc=encrypt_value("cal_live_k"), calendar_timezone="America/New_York")
    assert "calcom_api_key" not in agent_to_runtime(agent)
    assert agent_to_runtime(agent)["calcom_key_set"] is True
    assert agent_to_runtime(agent, secrets=True)["calcom_api_key"] == "cal_live_k"


def test_slot_labels_use_agent_timezone():
    assert calendar._label("2026-10-13T19:00:00Z", "America/New_York") == "Tuesday, October 13 at 3:00 PM EDT"
    assert calendar._label("2026-10-13T19:00:00Z") == "Tuesday, October 13 at 7:00 PM UTC"


def test_one_calendar_for_all_agents(client, make_client, monkeypatch):
    from tests.test_accounts import _login, _new_account

    monkeypatch.setattr(settings, "secrets_encryption_key", Fernet.generate_key().decode())
    _, email = _new_account(client, name="Calendar Co")
    c = _login(make_client, email)
    a = c.post("/api/agents", json={"template": "blank"}).json()
    b = c.post("/api/agents", json={"template": "blank"}).json()
    assert c.patch(f"/api/agents/{a['id']}", json={
        "enable_booking": True, "calcom_api_key": "cal_live_k1", "calcom_event_type_id": "111",
        "calendar_timezone": "America/Toronto", "calendar_all_agents": True}).status_code == 200
    other = c.get(f"/api/agents/{b['id']}").json()
    assert other["calcom_event_type_id"] == "111" and other["calcom_key_set"] and other["calendar_timezone"] == "America/Toronto"
    new = c.post("/api/agents", json={"template": "blank"}).json()  # agents made later start with it
    assert new["calcom_event_type_id"] == "111" and new["calcom_key_set"]

    # Unticked: only this agent changes.
    c.patch(f"/api/agents/{b['id']}", json={"calcom_event_type_id": "222", "calendar_all_agents": False})
    assert c.get(f"/api/agents/{a['id']}").json()["calcom_event_type_id"] == "111"
    # Another account never gets it.
    _, email2 = _new_account(client, name="Other Calendar Co")
    assert _login(make_client, email2).post("/api/agents", json={"template": "blank"}).json()["calcom_event_type_id"] == ""
