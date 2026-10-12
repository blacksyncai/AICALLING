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
