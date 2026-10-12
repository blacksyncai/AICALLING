import asyncio
import datetime as dt
import json
import uuid

import httpx
import pytest
from cryptography.fernet import Fernet

from app.config import settings
from app.services.crm import sync
from app.services.crm.http import BaseHttp
from app.services.crm.providers import PROVIDERS, CallInfo, Contact

NOW = dt.datetime.now(dt.timezone.utc)

# Plausible responses per provider, keyed by (METHOD, path suffix or fragment).
RESPONSES = {
    "close": {
        ("GET", "/v1/me/"): {"first_name": "Jo", "last_name": "Agent", "organizations": [{"name": "Acme"}]},
        ("GET", "/v1/lead/"): {"data": [], "has_more": False},
        ("POST", "/v1/lead/"): {"id": "lead_1"},
        ("POST", "/v1/activity/call/"): {"id": "acti_1"},
    },
    "followupboss": {
        ("GET", "/v1/me"): {"name": "Jo", "email": "jo@acme.com", "account": {"name": "Acme"}},
        ("GET", "/v1/people"): {"people": []},
        ("POST", "/v1/events"): {"person": {"id": 42}},
        ("POST", "/v1/calls"): {"id": 1},
        ("POST", "/v1/notes"): {"id": 1},
    },
    "hubspot": {
        ("GET", "/account-info/v3/details"): {"portalId": 123},
        ("POST", "/crm/v3/objects/contacts/search"): {"results": []},
        ("POST", "/crm/v3/objects/contacts"): {"id": "901"},
        ("POST", "/crm/v3/objects/calls"): {"id": "1"},
    },
    "pipedrive": {
        ("GET", "/v1/users/me"): {"data": {"name": "Jo", "company_name": "Acme"}},
        ("GET", "/v1/persons/search"): {"data": {"items": []}},
        ("POST", "/v1/persons"): {"data": {"id": 7}},
        ("POST", "/v1/activities"): {"data": {"id": 1}},
        ("GET", "/v1/persons"): {"data": [], "additional_data": {}},
    },
    "highlevel": {
        ("GET", "/locations/loc1"): {"location": {"name": "Acme Roofing"}},
        ("POST", "/contacts/upsert"): {"contact": {"id": "c1"}},
        ("POST", "/contacts/c1/notes"): {"note": {}},
        ("POST", "/contacts/c1/tags"): {},
    },
    "attio": {
        ("GET", "/v2/self"): {"workspace_name": "Acme"},
        ("POST", "/v2/objects/people/records/query"): {"data": []},
        ("POST", "/v2/objects/people/records"): {"data": {"id": {"record_id": "r1"}}},
        ("POST", "/v2/notes"): {"data": {}},
    },
    "salesforce": {
        ("GET", "/services/data/v60.0/search"): {"searchRecords": []},
        ("GET", "/services/data/v60.0/query"): {"records": []},
        ("POST", "/services/data/v60.0/sobjects/Lead"): {"id": "00Q1"},
        ("POST", "/services/data/v60.0/sobjects/Task"): {"id": "00T1"},
    },
    "zoho": {
        ("GET", "/crm/v6/Leads/search"): {},
        ("POST", "/crm/v6/Leads"): {"data": [{"details": {"id": "55"}}]},
        ("POST", "/crm/v6/Leads/55/Notes"): {"data": []},
    },
    "google_sheets": {
        ("POST", "values/'BlackSync calls'!A1:append"): {},
    },
    "slack": {("POST", ""): {}},
}


def mock(responses, calls):
    def handler(request: httpx.Request):
        path = request.url.path
        calls.append((request.method, path, request))
        best = None
        for (m, frag), body in responses.items():
            if m == request.method and (path.endswith(frag) or (frag and frag in httpx.URL(str(request.url)).path)
                                        or (frag in str(request.url))):
                if best is None or len(frag) > len(best[0]):
                    best = (frag, body)
        if best is None:
            return httpx.Response(404, json={"error": f"no mock for {request.method} {path}"})
        return httpx.Response(200, json=best[1])
    return handler


@pytest.fixture
def http_mock(monkeypatch):
    calls: list = []
    state = {"responses": {}}
    monkeypatch.setattr(BaseHttp, "client_factory",
                        staticmethod(lambda: httpx.AsyncClient(transport=httpx.MockTransport(
                            lambda r: mock(state["responses"], calls)(r)))))
    monkeypatch.setattr(settings, "secrets_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "nango_secret_key", "nango-test")
    return state, calls


CALL = CallInfo(call_id=str(uuid.uuid4()), outcome="meeting_booked", summary="Wants a demo Tuesday.", duration_seconds=95,
                phone="+14155550123", agent_name="Marissa", meeting_time="Tue 3 PM", url="https://app/calls/1",
                extracted={"timeline": "this month"})


@pytest.mark.parametrize("key", list(PROVIDERS))
def test_every_provider_creates_contact_and_logs_call(key, http_mock):
    state, calls = http_mock
    state["responses"] = RESPONSES[key]
    p = PROVIDERS[key]
    config = {"location_id": "loc1", "spreadsheet": "https://docs.google.com/spreadsheets/d/SHEET/edit"}
    if p.native:
        http = p.native_http("https://hooks.slack.com/services/x" if key == "slack" else "secret", config)
    else:
        config.update(nango_connection_id="conn1", nango_integration=key)
        http = p.http("", config)

    async def run():
        ref = await p.find_or_create(http, config, Contact("Jamie Rivera", "+14155550123", "jamie@x.com", "Globex"), create=True)
        assert ref
        await p.log_call(http, config, ref, CALL)

    asyncio.run(run())
    assert calls, "no requests made"
    if not p.native:
        assert calls[0][1].startswith("/proxy") and calls[0][2].headers["Connection-Id"] == "conn1"


def test_note_has_summary_outcome_and_link():
    text = CALL.note()
    assert "Meeting booked" in text and "Wants a demo" in text and "https://app/calls/1" in text and "1:35" in text


def test_connect_push_import_and_disconnect(client, http_mock):
    state, calls = http_mock
    state["responses"] = RESPONSES["followupboss"]
    r = client.post("/api/integrations/crm/followupboss/connect", json={"fields": {"api_key": "fka_secret"}})
    assert r.status_code == 200, r.text
    assert r.json()["account_label"] == "Acme · Jo · jo@acme.com" and "fka_secret" not in r.text
    assert "fka_secret" not in client.get("/api/integrations/crm").text

    # A finished call is logged in FUB and the contact remembers its FUB id.
    lead = client.post("/api/contacts", json={"name": "Jamie Rivera", "phone": "+14155550199"}).json()
    data = {"call_id": str(uuid.uuid4()), "outcome": "interested", "summary": "Interested.", "duration_seconds": 40,
            "to_phone": "+14155550199", "contact": {"id": lead["id"], "name": "Jamie Rivera", "phone": "+14155550199"}}
    org_id = client.get("/api/account").json().get("id") or client.get("/api/auth/me").json()["org"]["id"]
    asyncio.run(sync.push_call(uuid.UUID(org_id), data))
    posted = [json.loads(c[2].content) for c in calls if c[0] == "POST" and c[1] == "/v1/calls"]
    assert posted and posted[-1]["personId"] == 42 and posted[-1]["outcome"] == "Interested"
    acts = client.get("/api/integrations/crm/followupboss/activity").json()["items"]
    assert acts[0]["status"] == "ok" and "Logged" in acts[0]["message"]

    # Import: two people with phones, one already a contact → 1 new, 1 linked.
    state["responses"] = {**RESPONSES["followupboss"], ("GET", "/v1/people"): {"people": [
        {"id": 42, "name": "Jamie Rivera", "phones": [{"value": "(415) 555-0199"}], "created": NOW.isoformat()},
        {"id": 43, "name": "Pat Lee", "phones": [{"value": "+14155550177"}], "emails": [{"value": "pat@x.com"}]},
        {"id": 44, "name": "No Phone"}]}}
    res = client.post("/api/integrations/crm/followupboss/import").json()
    assert res == {"found": 2, "created": 1, "linked": 0}
    again = client.post("/api/integrations/crm/followupboss/import").json()
    assert again["created"] == 0

    assert client.delete("/api/integrations/crm/followupboss").status_code == 200
    assert client.get("/api/integrations/crm").json()["connections"] == []


def test_bad_key_is_not_saved(client, http_mock):
    state, _ = http_mock
    state["responses"] = {}  # every request 404s
    r = client.post("/api/integrations/crm/close/connect", json={"fields": {"api_key": "bad"}})
    assert r.status_code == 400 and "Couldn't connect to Close" in r.json()["detail"]
    assert all(c["provider"] != "close" for c in client.get("/api/integrations/crm").json()["connections"])


def test_speed_to_lead_calls_new_leads_in_hours(client, http_mock, monkeypatch):
    state, _ = http_mock
    state["responses"] = RESPONSES["close"]
    assert client.post("/api/integrations/crm/close/connect", json={"fields": {"api_key": "k"}}).status_code == 200
    agent_id = client.post("/api/agents/", json={"template": "blank"}).json()["id"]
    r = client.patch("/api/integrations/crm/close", json={"speed_to_lead_agent_id": agent_id})
    assert r.json()["settings"]["speed_to_lead_agent_id"] == agent_id

    later = (NOW + dt.timedelta(minutes=1)).isoformat()
    state["responses"] = {**RESPONSES["close"], ("GET", "/v1/lead/"): {"has_more": False, "data": [
        {"id": "lead_9", "display_name": "Newco", "date_created": later,
         "contacts": [{"name": "Sam New", "phones": [{"phone": "+14155550155"}]}]}]}}
    dialed = []

    async def fake_call(db, conn, agent, lead):
        dialed.append(lead.phone)
        return "call"

    monkeypatch.setattr(sync, "_call_lead", fake_call)
    monkeypatch.setattr(sync, "_in_hours", lambda org, now: True)
    asyncio.run(sync.poll_once())
    assert dialed == ["+14155550155"]
    asyncio.run(sync.poll_once())  # same lead again → not called twice
    assert dialed == ["+14155550155"]

    # Outside calling hours the lead waits, then is called when hours open.
    state["responses"][("GET", "/v1/lead/")]["data"][0].update(
        id="lead_10", date_created=(NOW + dt.timedelta(minutes=5)).isoformat(),
        contacts=[{"name": "Late Lead", "phones": [{"phone": "+14155550166"}]}])
    monkeypatch.setattr(sync, "_in_hours", lambda org, now: False)
    asyncio.run(sync.poll_once())
    assert dialed == ["+14155550155"]
    assert client.get("/api/integrations/crm").json()["connections"][0]["pending_calls"] == 1
    monkeypatch.setattr(sync, "_in_hours", lambda org, now: True)
    asyncio.run(sync.poll_once())
    assert dialed == ["+14155550155", "+14155550166"]
    client.delete("/api/integrations/crm/close")
