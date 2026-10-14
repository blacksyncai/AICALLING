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
        ("POST", "/v1/people"): {"id": 42},
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
    "boldtrail": {
        ("GET", "/v2/public/contacts"): {"data": []},
        ("POST", "/v2/public/contact"): {"id": 77},
        ("PUT", "/v2/public/contact/77/action/call"): {},
    },
    "lofty": {
        ("GET", "/v1.0/leads"): {"leads": []},
        ("POST", "/v1.0/leads"): {"leadId": 901},
        ("POST", "/v1.0/logType"): {"code": 0},
    },
    "sierra": {
        ("GET", "/leads/find"): {"success": True, "data": {"leads": []}},
        ("POST", "/leads"): {"success": True, "data": {"leadId": 31}},
        ("POST", "/leads/31/note"): {"success": True, "data": {}},
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
def test_every_provider_creates_contact_and_logs_call(key, http_mock, monkeypatch):
    state, calls = http_mock
    state["responses"] = RESPONSES[key]
    p = PROVIDERS[key]
    config = {"location_id": "loc1", "spreadsheet": "https://docs.google.com/spreadsheets/d/SHEET/edit"}
    if key == "salesforce":  # the customer's own Connected App (client credentials)
        from app.services.crm import salesforce_oauth

        async def token(host, data):
            return {"access_token": "at"}

        monkeypatch.setattr(salesforce_oauth, "_token", token)
        config.update(domain="https://acme.lightning.force.com/lightning/page/home", client_id="cid")
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

    # By default a number that isn't in FUB is left alone (no surprise "new lead" in the CRM).
    assert client.get("/api/integrations/crm").json()["connections"][0]["settings"]["create_contacts"] is False
    client.patch("/api/integrations/crm/followupboss", json={"create_contacts": True})
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
    assert {k: res[k] for k in ("found", "created", "linked")} == {"found": 2, "created": 1, "linked": 0}
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


def test_filtered_import_reads_dnc_and_contacted(client, http_mock):
    state, calls = http_mock
    people = {"people": [
        {"id": 1, "name": "Hot Buyer", "stage": "Hot Prospect", "tags": ["Buyer"], "contacted": 0,
         "phones": [{"value": "+14155551001"}]},
        {"id": 2, "name": "Called Before", "stage": "Hot Prospect", "tags": ["Buyer"], "contacted": 1,
         "phones": [{"value": "+14155551002"}]},
        {"id": 3, "name": "Stop Calling", "stage": "Hot Prospect", "tags": ["Buyer", "Do Not Call"],
         "phones": [{"value": "+14155551003"}]},
        {"id": 4, "name": "Wrong Stage", "stage": "Closed", "tags": ["Buyer"], "phones": [{"value": "+14155551004"}]},
        {"id": 5, "name": "Wrong Tag", "stage": "Hot Prospect", "tags": ["Seller"], "phones": [{"value": "+14155551005"}]},
    ]}
    state["responses"] = {**RESPONSES["followupboss"], ("GET", "/v1/people"): people,
                          ("GET", "/v1/stages"): {"stages": [{"id": 1, "name": "Hot Prospect"}, {"id": 2, "name": "Closed"}]},
                          ("GET", "/v1/ponds"): {"ponds": [{"id": 9, "name": "Buyer pond"}]},
                          ("GET", "/v1/users"): {"users": [{"id": 3, "name": "Jo"}]}}
    assert client.post("/api/integrations/crm/followupboss/connect", json={"fields": {"api_key": "k"}}).status_code == 200
    opts = client.get("/api/integrations/crm/followupboss/import/options").json()["filters"]
    keys = {f["key"]: f for f in opts}
    assert {"stage", "tags", "pond", "agent"} <= set(keys) and keys["tags"]["options"]

    body = {"filters": {"stage": ["Hot Prospect"], "tags": ["buyer"]}, "skip_contacted": True, "list_tag": "Hot buyers"}
    prev = client.post("/api/integrations/crm/followupboss/import/preview", json=body).json()
    assert prev["found"] == 3 and prev["skipped_contacted"] == 1 and prev["do_not_call"] == 1
    res = client.post("/api/integrations/crm/followupboss/import", json=body).json()
    assert res["created"] == 2 and res["do_not_call"] == 1

    leads = client.get("/api/contacts?q=+1415555100").json()
    items = leads.get("items") or leads.get("contacts") or leads
    by_name = {l["name"]: l for l in items}
    assert "Called Before" not in by_name and "Wrong Stage" not in by_name
    assert by_name["Stop Calling"]["do_not_call"] is True and by_name["Hot Buyer"]["do_not_call"] in (False, None)
    assert "Hot buyers" in by_name["Hot Buyer"]["tags"]

    # A "do not call" result is written back to FUB as a tag.
    state["responses"][("GET", "/v1/people/1")] = {"id": 1, "tags": ["Buyer"]}
    state["responses"][("PUT", "/v1/people/1")] = {}
    org_id = client.get("/api/auth/me").json()["org"]["id"]
    data = {"call_id": str(uuid.uuid4()), "outcome": "do_not_call", "duration_seconds": 20, "to_phone": "+14155551001",
            "contact": {"id": by_name["Hot Buyer"]["id"], "name": "Hot Buyer", "phone": "+14155551001"}}
    asyncio.run(sync.push_call(uuid.UUID(org_id), data))
    put = [json.loads(c[2].content) for c in calls if c[0] == "PUT" and c[1] == "/v1/people/1"]
    assert put and "Do Not Call" in put[-1]["tags"]
    client.delete("/api/integrations/crm/followupboss")


def test_close_pipeline_stage_and_smart_view(http_mock):
    state, calls = http_mock
    lead = lambda i, status="Potential": {"id": f"lead_{i}", "display_name": f"Co {i}", "status_label": status,
                                          "contacts": [{"name": f"P {i}", "phones": [{"phone": f"+1415555200{i}"}]}]}
    state["responses"] = {
        ("GET", "/v1/status/lead/"): {"data": [{"label": "Potential"}, {"label": "Bad Fit"}]},
        ("GET", "/v1/pipeline/"): {"data": [{"id": "pipe_1", "name": "Sales", "statuses": [{"id": "stat_1", "label": "Demo booked"}]}]},
        ("GET", "/v1/saved_search/"): {"data": [{"id": "save_1", "name": "Hot", "s_query": {"type": "and"}}]},
        ("GET", "/v1/opportunity/"): {"data": [{"lead_id": "lead_1"}, {"lead_id": "lead_2"}], "has_more": False},
        ("GET", "/v1/lead/lead_1/"): lead(1),
        ("GET", "/v1/lead/lead_2/"): lead(2, "Bad Fit"),
        ("GET", "/v1/saved_search/save_1/"): {"id": "save_1", "s_query": {"type": "and"}},
        ("POST", "/v1/data/search/"): {"data": [lead(3), lead(4)], "cursor": None},
        ("GET", "/v1/lead/"): {"data": [lead(1), lead(5)], "has_more": False},
    }
    p = PROVIDERS["close"]
    http = p.native_http("k", {})

    async def run():
        opts = {o["key"]: o for o in await p.import_options(http, {})}
        by_stage = await p.list_contacts(http, {}, filters={"opp_status": ["stat_1"]})
        stage_and_status = await p.list_contacts(http, {}, filters={"opp_status": ["stat_1"], "status": ["Potential"]})
        view = await p.list_contacts(http, {}, filters={"view": ["save_1"]})
        whole_pipeline = await p.list_contacts(http, {}, filters={"pipeline": ["pipe_1"]})
        assert {c.external_id for c in whole_pipeline} == {"lead_1", "lead_2"}
        return opts, by_stage, stage_and_status, view

    opts, by_stage, both, view = asyncio.run(run())
    pipe = opts["pipeline"]["options"][0]
    assert pipe["label"] == "Sales" and pipe["stages"][0]["label"] == "Demo booked" and opts["view"]["options"][0]["value"] == "save_1"
    assert {c.external_id for c in by_stage} == {"lead_1", "lead_2"}
    assert [c.external_id for c in both] == ["lead_1"]  # in the stage AND the status
    assert [c.external_id for c in view] == ["lead_3", "lead_4"]


def test_close_pipeline_sync_moves_and_creates_opportunities(client, http_mock):
    state, calls = http_mock
    stages = [("st_new", "New Prospect", "active"), ("st_dial", "Dialing", "active"), ("st_vm", "Voicemail Left", "active"),
              ("st_booked", "Discovery Booked", "active"), ("st_won", "Won", "won")]
    state["responses"] = {
        **RESPONSES["close"],
        ("GET", "/v1/pipeline/"): {"data": [{"id": "pipe_smb", "name": "SMB Sales", "statuses": [
            {"id": i, "label": l, "type": t} for i, l, t in stages]}]},
        ("GET", "/v1/lead/"): {"data": [{"id": "lead_7"}]},
        ("GET", "/v1/opportunity/"): {"data": [{"id": "oppo_1", "status_id": "st_vm"}]},
        ("PUT", "/v1/opportunity/oppo_1/"): {},
        ("POST", "/v1/opportunity/"): {"id": "oppo_new"},
    }
    assert client.post("/api/integrations/crm/close/connect", json={"fields": {"api_key": "k"}}).status_code == 200
    info = client.get("/api/integrations/crm/close/pipelines").json()
    assert info["supported"] and info["noun"] == "opportunity"
    suggested = info["suggested"]["pipe_smb"]
    assert suggested["meeting_booked"] == "st_booked" and suggested["voicemail"] == "st_vm" and suggested["no_answer"] == "st_dial"
    r = client.put("/api/integrations/crm/close/pipelines", json={"pipeline_id": "pipe_smb", "map": suggested})
    assert r.status_code == 200 and r.json()["pipeline"]["name"] == "SMB Sales"

    org_id = client.get("/api/auth/me").json()["org"]["id"]

    def call(outcome):
        asyncio.run(sync.push_call(uuid.UUID(org_id), {"call_id": str(uuid.uuid4()), "outcome": outcome,
                    "duration_seconds": 30, "to_phone": "+14155553001", "contact": {"name": "Ann", "phone": "+14155553001"}}))

    call("meeting_booked")  # Voicemail Left → Discovery Booked (forward)
    moves = [json.loads(c[2].content) for c in calls if c[0] == "PUT" and c[1].endswith("/v1/opportunity/oppo_1/")]
    assert moves == [{"status_id": "st_booked"}]
    call("no_answer")       # Dialing is behind Voicemail Left → not moved back
    assert len([c for c in calls if c[0] == "PUT" and c[1].endswith("/oppo_1/")]) == 1

    state["responses"][("GET", "/v1/opportunity/")] = {"data": []}  # no opportunity yet → created in the mapped stage
    call("voicemail")
    created = [json.loads(c[2].content) for c in calls if c[0] == "POST" and c[1].endswith("/v1/opportunity/")]
    assert created and created[-1]["status_id"] == "st_vm" and created[-1]["lead_id"] == "lead_7"
    acts = client.get("/api/integrations/crm/close/activity").json()["items"]
    assert any("Opportunity created in Voicemail Left" in a["message"] for a in acts)
    client.delete("/api/integrations/crm/close")


def test_blacksync_pipeline_install_queue_and_card_moves(client, http_mock, monkeypatch):
    state, calls = http_mock
    created_status = iter(f"st_{i}" for i in range(20))

    def mk_status(req_body):
        return {"id": next(created_status)}

    state["responses"] = {
        **RESPONSES["close"],
        ("GET", "/v1/pipeline/"): {"data": []},
        ("POST", "/v1/pipeline/"): {"id": "pipe_bs", "name": "BlackSync AI · Ann"},
        ("POST", "/v1/status/opportunity/"): {"id": "st_x"},
    }
    assert client.post("/api/integrations/crm/close/connect", json={"fields": {"api_key": "k"}}).status_code == 200
    agent = client.post("/api/agents/", json={"template": "blank", "name": "Ann"}).json()

    # Each created stage gets its own id.
    orig = BaseHttp.client_factory

    def factory():
        def handler(request):
            if request.method == "POST" and request.url.path.endswith("/v1/status/opportunity/"):
                calls.append((request.method, request.url.path, request))
                return httpx.Response(200, json=mk_status(request))
            return mock(state["responses"], calls)(request)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(BaseHttp, "client_factory", staticmethod(factory))
    r = client.post("/api/integrations/crm/close/install", json={"agent_id": agent["id"]})
    assert r.status_code == 200, r.text
    inst = r.json()["installs"][0]
    assert inst["agent_name"] == "Ann" and inst["stages"][0] == "Queued for AI call" and len(inst["stages"]) == 8
    stage_posts = [json.loads(c[2].content) for c in calls if c[1].endswith("/v1/status/opportunity/")]
    assert stage_posts[0]["pipeline_id"] == "pipe_bs" and stage_posts[-1]["type"] == "lost"

    # A card dragged into "Queued for AI call" (st_0) is called and moved to "AI calling" (st_1).
    state["responses"].update({
        ("GET", "/v1/opportunity/"): {"data": [{"id": "oppo_q", "lead_id": "lead_q", "contact_id": "cont_q"}]},
        ("GET", "/v1/lead/lead_q/"): {"id": "lead_q", "display_name": "Davis Group", "status_label": "Potential",
                                      "description": "67 sales last year. Decision maker: Katie.",
                                      "contacts": [{"id": "cont_q", "name": "Katie Davis", "phones": [{"phone": "+14155554001"}]}]},
        ("GET", "/v1/activity/note/"): {"data": [{"note": "Wants database reactivation", "date_created": "2026-09-11"}]},
        ("GET", "/v1/activity/call/"): {"data": [{"disposition": "no-answer", "date_created": "2026-09-28"}]},
        ("PUT", "/v1/opportunity/oppo_q/"): {},
        ("GET", "/v1/opportunity/oppo_q/"): {"status_id": "st_1"},
    })
    dialed = []

    async def fake_call(db, conn, agent_, lead):
        dialed.append((agent_.name, lead.phone, (lead.custom_fields or {}).get("crm_context", "")))
        return "c"

    monkeypatch.setattr(sync, "_call_lead", fake_call)
    monkeypatch.setattr(sync, "_in_hours", lambda org, now: True)
    asyncio.run(sync.poll_once())
    assert dialed and dialed[0][0] == "Ann" and dialed[0][1] == "+14155554001"
    assert "67 sales" in dialed[0][2] and "no answer" in dialed[0][2]
    moves = [json.loads(c[2].content) for c in calls if c[0] == "PUT" and c[1].endswith("/oppo_q/")]
    assert moves[-1] == {"status_id": "st_1"}

    # The call result moves the card: meeting booked → "Meeting booked by AI" (st_5).
    lead = next(l for l in client.get("/api/contacts?q=4155554001").json().get("items", []))
    org_id = client.get("/api/auth/me").json()["org"]["id"]
    asyncio.run(sync.push_call(uuid.UUID(org_id), {"call_id": str(uuid.uuid4()), "outcome": "meeting_booked",
                "duration_seconds": 90, "to_phone": "+14155554001",
                "contact": {"id": lead["id"], "name": "Katie Davis", "phone": "+14155554001"}}))
    moves = [json.loads(c[2].content) for c in calls if c[0] == "PUT" and c[1].endswith("/oppo_q/")]
    assert moves[-1] == {"status_id": "st_5"}

    # The agent's prompt gets the CRM context (without the raw field names).
    from app.agent.runtime import build_instructions
    prompt = build_instructions({"system_prompt": "Hi"}, {"name": "Katie", "crm_context": "67 sales last year", "bs_deal": "x"})
    assert "WHAT THE CRM SAYS" in prompt and "67 sales" in prompt and "bs_deal" not in prompt
    client.delete("/api/integrations/crm/close")


def test_radar_plays_rules():
    from app.services.crm.radar import Signals, build_plays

    now = dt.datetime(2026, 10, 12, tzinfo=dt.timezone.utc)
    d = lambda days: now - dt.timedelta(days=days)
    sig = [
        Signals("1", "Hot", "+14155550001", created_at=d(40), last_inbound_at=d(1), inbound_kind="Viewed Property · 12 Oak St"),
        Signals("2", "Fresh", "+14155550002", created_at=d(3)),
        Signals("3", "Ghost", "+14155550003", created_at=d(20), calls=2, last_call_at=d(13), last_call_result="no answer"),
        Signals("4", "Cold", "+14155550004", created_at=d(90), calls=3, connected_calls=1, last_call_at=d(45), deal_open=True),
        Signals("5", "Stuck", "+14155550005", created_at=d(60), calls=1, connected_calls=1, last_call_at=d(10),
                deal_open=True, deal_stage="Proposal Sent", deal_updated_at=d(30)),
        Signals("6", "Client", "+14155550006", created_at=d(400), won_at=d(200)),
        Signals("7", "Old", "+14155550007", created_at=d(300), calls=0, last_activity_at=d(200)),
        Signals("8", "Lost", "+14155550008", created_at=d(30), status="Lost"),
        Signals("9", "DNC", "+14155550009", created_at=d(30), dnc=True),
        Signals("10", "Just called", "+14155550010", created_at=d(30), calls=1, last_call_at=d(1)),
    ]
    plays = {p["key"]: p for p in build_plays(sig, now)["plays"]}
    names = {k: [i["name"] for i in p["items"]] for k, p in plays.items()}
    assert names["hot"] == ["Hot"] and "Viewed Property" in plays["hot"]["items"][0]["reason"]
    # "Old" was never called, so it lands in never_called (the first matching play wins).
    assert set(names["never_called"]) == {"Fresh", "Old"}
    assert names["unreached"] == ["Ghost"] and names["went_cold"] == ["Cold"] and names["stuck"] == ["Stuck"]
    assert names["past_client"] == ["Client"]
    flat = sum(names.values(), [])
    assert not {"Lost", "DNC", "Just called"} & set(flat)


def test_radar_scan_and_launch_campaign(client, http_mock):
    state, _ = http_mock
    now = dt.datetime.now(dt.timezone.utc)
    iso = lambda days: (now - dt.timedelta(days=days)).isoformat()
    state["responses"] = {
        **RESPONSES["close"],
        ("GET", "/v1/lead/"): {"has_more": False, "data": [
            {"id": "lead_a", "display_name": "Alpha", "date_created": iso(10), "status_label": "Potential",
             "contacts": [{"name": "Al", "phones": [{"phone": "+14155556001"}]}], "opportunities": []},
            {"id": "lead_b", "display_name": "Beta", "date_created": iso(20), "status_label": "Potential",
             "contacts": [{"name": "Bo", "phones": [{"phone": "+14155556002"}]}], "opportunities": []}]},
        ("GET", "/v1/activity/call/"): {"has_more": False, "data": [
            {"lead_id": "lead_b", "date_created": iso(13), "disposition": "no-answer", "direction": "outbound"}]},
        ("GET", "/v1/activity/email/"): {"has_more": False, "data": []},
        ("GET", "/v1/activity/sms/"): {"has_more": False, "data": []},
        ("GET", "/v1/activity/form_submission/"): {"has_more": False, "data": []},
    }
    assert client.post("/api/integrations/crm/close/connect", json={"fields": {"api_key": "k"}}).status_code == 200
    scan = client.post("/api/radar/close/scan").json()
    plays = {p["key"]: p for p in scan["plays"]}
    assert plays["never_called"]["count"] == 1 and plays["unreached"]["count"] == 1
    assert "1 call, never reached" in plays["unreached"]["items"][0]["reason"]
    assert client.get("/api/radar").json()["crms"][0]["last_scan"]["id"] == scan["id"]

    agent = client.post("/api/agents/", json={"template": "blank"}).json()
    r = client.post(f"/api/radar/scans/{scan['id']}/launch", json={"play": "unreached", "agent_id": agent["id"], "mode": "campaign"})
    assert r.status_code == 200 and r.json()["contacts"] == 1
    camp = client.get(f"/api/campaigns/{r.json()['campaign_id']}").json()
    assert camp["status"] == "draft" and camp["agent_id"] == agent["id"]
    # Pipeline mode needs the BlackSync pipeline first.
    r = client.post(f"/api/radar/scans/{scan['id']}/launch", json={"play": "unreached", "agent_id": agent["id"], "mode": "pipeline"})
    assert r.status_code == 400 and "pipeline" in r.json()["detail"]
    client.delete("/api/integrations/crm/close")


def test_fub_follows_next_link_and_radar_scans(monkeypatch):
    seen = []

    def handler(request: httpx.Request):
        q = dict(request.url.params)
        seen.append((request.url.path, q))
        if "offset" in q and int(q["offset"]) >= 100:
            return httpx.Response(400, json={"errorMessage": "Deep pagination disabled, use 'nextLink' url"})
        path = request.url.path
        if path == "/v1/people":
            if q.get("next") == "p2":
                return httpx.Response(200, json={"people": [{"id": 200, "name": "Page Two", "phones": [{"value": "+14155557200"}],
                                                             "created": "2026-01-01T00:00:00Z", "stage": "Lead"}], "_metadata": {}})
            people = [{"id": i, "name": f"P{i}", "phones": [{"value": f"+1415555{7000 + i}"}], "stage": "Lead",
                       "created": "2026-09-01T00:00:00Z"} for i in range(100)]
            return httpx.Response(200, json={"people": people,
                                             "_metadata": {"nextLink": "https://api.followupboss.com/v1/people?next=p2&limit=100"}})
        if path == "/v1/events":
            return httpx.Response(200, json={"events": [{"personId": 5, "type": "Viewed Property",
                                                         "created": dt.datetime.now(dt.timezone.utc).isoformat(),
                                                         "property": {"street": "12 Oak St"}}], "_metadata": {}})
        if path == "/v1/calls":
            return httpx.Response(200, json={"calls": [], "_metadata": {}})
        return httpx.Response(404, json={})

    monkeypatch.setattr(BaseHttp, "client_factory",
                        staticmethod(lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    p = PROVIDERS["followupboss"]
    http = p.native_http("k", {})
    from app.services.crm.radar import build_plays

    signals = asyncio.run(p.scan_signals(http, {}))
    assert len(signals) == 101 and any(s.name == "Page Two" for s in signals)
    assert not any("offset" in q for _, q in seen)
    plays = {pl["key"]: pl for pl in build_plays(signals)["plays"]}
    assert plays["hot"]["count"] == 1 and "12 Oak St" in plays["hot"]["items"][0]["reason"]
    contacts = asyncio.run(p.list_contacts(http, {}, limit=500))
    assert len(contacts) == 101


def test_fub_tags_queue_activity_trigger_and_tasks(client, monkeypatch):
    monkeypatch.setattr(settings, "secrets_encryption_key", Fernet.generate_key().decode())
    now = dt.datetime.now(dt.timezone.utc)
    people = {
        "11": {"id": 11, "name": "Tagged Tina", "phones": [{"value": "+14155558011"}], "tags": ["Buyer"], "stage": "Lead",
               "assignedUserId": 7},
        "12": {"id": 12, "name": "Browsing Bob", "phones": [{"value": "+14155558012"}], "tags": [], "stage": "Lead"},
    }
    posts = []

    def handler(request: httpx.Request):
        path, q = request.url.path, dict(request.url.params)
        body = json.loads(request.content) if request.content else None
        if path == "/v1/me":
            return httpx.Response(200, json={"name": "Jo", "account": {"name": "Acme"}})
        if path == "/v1/people" and request.method == "GET":
            tag = q.get("tags")
            rows = [p for p in people.values() if not tag or tag in p["tags"]]
            return httpx.Response(200, json={"people": rows, "_metadata": {}})
        if path.startswith("/v1/people/"):
            pid = path.rsplit("/", 1)[1]
            if request.method == "PUT":
                people[pid]["tags"] = body["tags"]
            return httpx.Response(200, json=people[pid])
        if path == "/v1/events":
            if q.get("personId"):
                return httpx.Response(200, json={"events": []})
            return httpx.Response(200, json={"events": [{"personId": 12, "type": "Viewed Property", "property": {"street": "9 Elm St"},
                                                         "created": (now + dt.timedelta(seconds=5)).isoformat()}], "_metadata": {}})
        if path in ("/v1/notes", "/v1/calls") and request.method == "GET":
            return httpx.Response(200, json={path.rsplit("/", 1)[1]: []})
        posts.append((path, body))
        return httpx.Response(200, json={"id": 1})

    monkeypatch.setattr(BaseHttp, "client_factory",
                        staticmethod(lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    assert client.post("/api/integrations/crm/followupboss/connect", json={"fields": {"api_key": "k"}}).status_code == 200
    agent = client.post("/api/agents/", json={"template": "blank", "name": "Marissa"}).json()
    inst = client.post("/api/integrations/crm/followupboss/install", json={"agent_id": agent["id"]}).json()["installs"][0]
    assert inst["stages"][0] == "AI Call - Marissa"
    client.patch("/api/integrations/crm/followupboss", json={"activity_agent_id": agent["id"]})

    people["11"]["tags"].append("AI Call - Marissa")  # someone tags Tina in FUB
    dialed = []

    async def fake_call(db, conn, agent_, lead):
        dialed.append((lead.name, (lead.custom_fields or {}).get("crm_context", "")))
        return "c"

    monkeypatch.setattr(sync, "_call_lead", fake_call)
    monkeypatch.setattr(sync, "_in_hours", lambda org, now: True)
    asyncio.run(sync.poll_once())
    names = [d[0] for d in dialed]
    assert "Tagged Tina" in names and "Browsing Bob" in names
    assert "Viewed Property · 9 Elm St" in dict(dialed)["Browsing Bob"]
    assert people["11"]["tags"] == ["Buyer", "AI Calling"]

    lead = client.get("/api/contacts?q=4155558011").json()["items"][0]
    org_id = client.get("/api/auth/me").json()["org"]["id"]
    asyncio.run(sync.push_call(uuid.UUID(org_id), {"call_id": str(uuid.uuid4()), "outcome": "meeting_booked",
                "meeting_time": "Tue 3 PM", "duration_seconds": 80, "to_phone": "+14155558011",
                "contact": {"id": lead["id"], "name": "Tagged Tina", "phone": "+14155558011"}}))
    assert people["11"]["tags"] == ["Buyer", "AI Booked"]
    task = next(b for p, b in posts if p == "/v1/tasks")
    assert task["personId"] == 11 and task["assignedUserId"] == 7 and "Tue 3 PM" in task["name"]
    client.delete("/api/integrations/crm/followupboss")


def test_push_rules_note_options_and_auto_sync_into_campaign(client, http_mock, monkeypatch):
    state, calls = http_mock
    state["responses"] = dict(RESPONSES["followupboss"])
    assert client.post("/api/integrations/crm/followupboss/connect", json={"fields": {"api_key": "k"}}).status_code == 200
    org_id = uuid.UUID(client.get("/api/auth/me").json()["org"]["id"])
    lead = client.post("/api/contacts", json={"name": "Jamie", "phone": "+14155550311"}).json()

    def push(outcome, seconds):
        data = {"call_id": str(uuid.uuid4()), "outcome": outcome, "summary": "Secret summary.", "duration_seconds": seconds,
                "to_phone": "+14155550311", "contact": {"id": lead["id"], "name": "Jamie", "phone": "+14155550311"},
                "extracted_data": {"budget": "500k"}}
        before = len([c for c in calls if c[0] == "POST" and c[1] == "/v1/calls"])
        asyncio.run(sync.push_call(org_id, data))
        posted = [json.loads(c[2].content) for c in calls if c[0] == "POST" and c[1] == "/v1/calls"]
        return posted[-1] if len(posted) > before else None

    s = client.patch("/api/integrations/crm/followupboss", json={
        "create_contacts": True, "skip_outcomes": ["voicemail", "bogus"], "min_seconds": 20,
        "note_summary": False, "note_link": False}).json()["settings"]
    assert s["skip_outcomes"] == ["voicemail"] and s["min_seconds"] == 20
    assert push("voicemail", 40) is None          # skipped outcome
    assert push("interested", 8) is None          # too short
    body = push("interested", 45)
    assert body and "Secret summary" not in json.dumps(body) and "500k" in json.dumps(body)

    # Auto-sync: new people matching the rule land in the campaign; a finished campaign wakes up.
    agent_id = client.get("/api/agents/").json()[0]["id"]
    camp = client.post("/api/campaigns", json={"name": "FUB hot", "agent_id": agent_id}).json()
    state["responses"][("GET", "/v1/people")] = {"people": [
        {"id": 71, "name": "New Hot", "stage": "Hot", "phones": [{"value": "+14155550371"}]},
        {"id": 72, "name": "Dnc Hot", "stage": "Hot", "tags": ["Do Not Call"], "phones": [{"value": "+14155550372"}]}]}
    conn = client.post("/api/integrations/crm/followupboss/auto-imports", json={
        "name": "Hot → campaign", "filters": {"stage": ["Hot"]}, "campaign_id": camp["id"], "every_minutes": 15}).json()
    rule = conn["auto_imports"][0]
    assert rule["every_minutes"] == 15 and rule["campaign_id"] == camp["id"] and rule["runs"] == 0
    assert client.post("/api/integrations/crm/followupboss/auto-imports", json={"every_minutes": 7}).status_code == 400

    woke = []
    monkeypatch.setattr(sync, "wake_campaigns", lambda: woke.append(dict(sync._wake)) or sync._wake.clear())
    r = client.post(f"/api/integrations/crm/followupboss/auto-imports/{rule['id']}/run").json()
    assert r["result"]["created"] == 2 and r["result"]["added_to_campaign"] == 1  # the DNC one is saved, never queued
    assert r["connection"]["auto_imports"][0]["runs"] == 1 and r["connection"]["auto_imports"][0]["last_result"]["ok"]
    c = client.get(f"/api/campaigns/{camp['id']}").json()
    assert c["total_targets"] == 1

    # Due-ness: just ran → not due; an hour later (15-min rule) → due.
    from app.services.crm.sync import _due
    rr = r["connection"]["auto_imports"][0]
    assert not _due(rr, dt.datetime.fromisoformat(rr["last_run_at"]) + dt.timedelta(minutes=5))
    assert _due(rr, dt.datetime.fromisoformat(rr["last_run_at"]) + dt.timedelta(minutes=16))

    assert client.delete(f"/api/integrations/crm/followupboss/auto-imports/{rule['id']}").json()["auto_imports"] == []
    client.delete("/api/integrations/crm/followupboss")


def test_only_results_and_sentiment_rules(client, http_mock):
    state, calls = http_mock
    state["responses"] = dict(RESPONSES["followupboss"])
    assert client.post("/api/integrations/crm/followupboss/connect", json={"fields": {"api_key": "k"}}).status_code == 200
    org_id = uuid.UUID(client.get("/api/auth/me").json()["org"]["id"])
    lead = client.post("/api/contacts", json={"name": "Rae", "phone": "+14155550411"}).json()
    s = client.patch("/api/integrations/crm/followupboss", json={
        "create_contacts": True, "only_outcomes": ["meeting_booked", "interested", "nope"], "only_sentiments": ["positive", "meh"],
        "min_seconds": 45}).json()["settings"]
    assert s["only_outcomes"] == ["meeting_booked", "interested"] and s["only_sentiments"] == ["positive"]

    def sent(outcome, seconds, sentiment):
        before = len([c for c in calls if c[0] == "POST" and c[1] == "/v1/calls"])
        asyncio.run(sync.push_call(org_id, {"call_id": str(uuid.uuid4()), "outcome": outcome, "duration_seconds": seconds,
                                             "sentiment": sentiment, "to_phone": "+14155550411",
                                             "contact": {"id": lead["id"], "name": "Rae", "phone": "+14155550411"}}))
        return len([c for c in calls if c[0] == "POST" and c[1] == "/v1/calls"]) > before

    assert sent("interested", 60, "positive")
    assert not sent("interested", 30, "positive")      # under 45 s
    assert not sent("not_interested", 90, "positive")  # result not in the list
    assert not sent("interested", 90, "negative")      # wrong mood
    assert sent("do_not_call", 5, "negative")          # always synced
    client.delete("/api/integrations/crm/followupboss")


def test_hubspot_deal_stage_sync(http_mock):
    from app.services.crm.http import NativeHttp
    from app.services.crm.providers import HubSpot

    state, calls = http_mock
    state["responses"] = {
        ("GET", "/crm/v3/pipelines/deals"): {"results": [{"id": "default", "label": "Sales", "stages": [
            {"id": "appt", "label": "Appointment scheduled", "displayOrder": 0, "metadata": {"probability": "0.2"}},
            {"id": "qual", "label": "Qualified to buy", "displayOrder": 1, "metadata": {"probability": "0.4"}},
            {"id": "won", "label": "Closed won", "displayOrder": 2, "metadata": {"probability": "1.0", "isClosed": "true"}}]}]},
        ("GET", "/crm/v4/objects/contacts/901/associations/deals"): {"results": [{"toObjectId": 55}]},
        ("POST", "/crm/v3/objects/deals/batch/read"): {"results": [{"id": "55", "properties": {"pipeline": "default", "dealstage": "appt"}}]},
        ("PATCH", "/crm/v3/objects/deals/55"): {},
        ("POST", "/crm/v3/objects/deals"): {"id": "56"},
    }
    hs = HubSpot()
    http = NativeHttp("https://api.hubapi.com")
    pipes = asyncio.run(hs.pipelines(http, {}))
    assert [st["kind"] for st in pipes[0]["stages"]] == ["active", "active", "won"]
    msg = asyncio.run(hs.set_stage(http, {}, "901", pipes[0], "qual", create=True, forward_only=True, name="Rae"))
    assert msg == "Deal moved to Qualified to buy"
    patched = [json.loads(c[2].content) for c in calls if c[0] == "PATCH"]
    assert patched[-1] == {"properties": {"dealstage": "qual"}}
    # Forward-only: never move back down the board.
    assert asyncio.run(hs.set_stage(http, {}, "901", pipes[0], "appt", create=True, forward_only=True)) is None


def test_custom_ai_pipeline_on_pipedrive_with_retry_settings(client, http_mock, monkeypatch):
    state, calls = http_mock
    ids = iter(range(100, 200))

    def factory():
        def handler(request):
            if request.method == "POST" and request.url.path.endswith("/v1/stages"):
                calls.append((request.method, request.url.path, request))
                return httpx.Response(200, json={"data": {"id": next(ids)}})
            return mock(state["responses"], calls)(request)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    state["responses"] = {**RESPONSES["pipedrive"], ("GET", "/v1/pipelines"): {"data": []},
                          ("POST", "/v1/pipelines"): {"data": {"id": 9}}, ("GET", "/v1/stages"): {"data": []}}
    assert client.post("/api/integrations/crm/pipedrive/connect", json={"fields": {"api_key": "k"}}).status_code == 200
    monkeypatch.setattr(BaseHttp, "client_factory", staticmethod(factory))
    prev = client.get("/api/integrations/crm/pipedrive/install/preview").json()
    assert prev["supported"] and prev["stages"][0]["key"] == "queued" and prev["stages"][0]["what"]

    agent = client.post("/api/agents/", json={"template": "blank", "name": "Exp"}).json()
    r = client.post("/api/integrations/crm/pipedrive/install", json={
        "agent_id": agent["id"], "name": "BlackSync AI calling — Expired", "labels": {"queued": "New lead", "follow_up": "Contacted"},
        "max_tries": 5, "retry_hours": 2, "retry_voicemail": False})
    assert r.status_code == 200, r.text
    inst = r.json()["installs"][0]
    assert inst["pipeline_name"] == "BlackSync AI calling — Expired"
    assert inst["stages"][0] == "New lead" and "Contacted" in inst["stages"]
    assert inst["retry"] == {"max_tries": 5, "after_hours": 2.0, "voicemail": False}
    posted = [json.loads(c[2].content)["name"] for c in calls if c[0] == "POST" and c[1].endswith("/v1/stages")]
    assert posted[0] == "New lead" and len(posted) == 8
    client.delete("/api/integrations/crm/pipedrive")


def test_hubspot_creates_ai_pipeline(http_mock):
    from app.services.crm.http import NativeHttp
    from app.services.crm.providers import HubSpot
    from app.services.crm.sync import install_stages

    state, calls = http_mock
    state["responses"] = {
        ("GET", "/crm/v3/pipelines/deals"): {"results": []},
        ("POST", "/crm/v3/pipelines/deals"): {"id": "777", "label": "BlackSync AI", "stages": [
            {"id": f"s{i}", "label": st["label"]} for i, st in enumerate(install_stages())]},
    }
    pipe = asyncio.run(HubSpot().install_pipeline(NativeHttp("https://api.hubapi.com"), {}, "BlackSync AI", install_stages()))
    assert pipe["id"] == "777" and [s["key"] for s in pipe["stages"]][:2] == ["queued", "calling"]
    body = [json.loads(c[2].content) for c in calls if c[0] == "POST"][0]
    probs = {st["label"]: st["metadata"]["probability"] for st in body["stages"]}
    assert probs["Not interested"] == "0.0" and probs["Queued for AI call"] == "0.5"


def test_radar_digs_old_leads_in_batches_and_waits_out_rate_limits(client, monkeypatch):
    """FUB: dig oldest-first, continue to the next batch, merge without repeats, and retry a 429."""
    from app.services.crm import http as crm_http

    monkeypatch.setattr(settings, "secrets_encryption_key", Fernet.generate_key().decode())

    async def no_sleep(_s):
        return None

    monkeypatch.setattr(crm_http.asyncio, "sleep", no_sleep)
    fub = PROVIDERS["followupboss"]
    monkeypatch.setattr(type(fub), "_DEPTHS", {**type(fub)._DEPTHS, "old": ("created", 100, False, 0)})  # 1 page a batch
    hits = {"429": 0}
    old = "2024-01-15T00:00:00Z"

    def handler(request: httpx.Request):
        path, q = request.url.path, dict(request.url.params)
        if path == "/v1/me":
            return httpx.Response(200, json={"name": "Jo"})
        if path == "/v1/people":
            if q.get("next") == "b2":
                rows = [{"id": 500 + i, "name": f"Old B{i}", "phones": [{"value": f"+1415556{6000 + i}"}], "stage": "Lead",
                         "created": old, "contacted": False} for i in range(3)]
                return httpx.Response(200, json={"people": rows, "_metadata": {}})
            assert q.get("sort") == "created"  # oldest first
            if hits["429"] == 0:
                hits["429"] += 1
                return httpx.Response(429, headers={"Retry-After": "1"}, json={"errorMessage": "Too many requests"})
            rows = [{"id": i, "name": f"Old A{i}", "phones": [{"value": f"+1415555{6000 + i}"}], "stage": "Lead",
                     "created": old, "contacted": i % 2 == 0} for i in range(100)]
            return httpx.Response(200, json={"people": rows,
                                             "_metadata": {"nextLink": "https://api.followupboss.com/v1/people?next=b2&limit=100"}})
        return httpx.Response(200, json={"events": [], "calls": [], "_metadata": {}})

    monkeypatch.setattr(BaseHttp, "client_factory",
                        staticmethod(lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    assert client.post("/api/integrations/crm/followupboss/connect", json={"fields": {"api_key": "k"}}).status_code == 200
    r = client.post("/api/radar/followupboss/scan", params={"depth": "old"})
    assert r.status_code == 200, r.text
    first = r.json()
    assert hits["429"] == 1 and first["depth"] == "old" and first["next"] and first["scanned"] == 100
    plays = {pl["key"]: pl for pl in first["plays"]}
    # Calls weren't read on an old-lead batch: only people FUB marks as not contacted count as never contacted.
    assert plays["never_called"]["count"] == 50 and plays["never_called"]["title"] == "Haven't been contacted"
    item = plays["never_called"]["items"][0]
    assert item["created"].startswith("2024-01-15") and item["contacted"] is False

    r = client.post("/api/radar/followupboss/scan", params={"continue_from": first["id"]})
    second = r.json()
    assert second["scanned"] == 103 and second["batches"] == 2 and not second["next"]
    never = {pl["key"]: pl for pl in second["plays"]}["never_called"]
    assert never["count"] == 53 and len({i["external_id"] for i in never["items"]}) == 53
    # The end of the CRM: nothing more to scan.
    assert client.post("/api/radar/followupboss/scan", params={"continue_from": second["id"]}).status_code == 400
    client.delete("/api/integrations/crm/followupboss")


def test_script_variables_filled_from_follow_up_boss(client, monkeypatch):
    """The agent's {{variables}} map to FUB fields (auto by name, or chosen) and fill in before the call."""
    import asyncio as aio

    from app.database import AsyncSessionLocal
    from app.models.agent import Agent
    from app.models.crm import CrmConnection
    from app.models.lead import Lead
    from app.services.crm import sync as crm_sync, variables as crm_vars
    from sqlalchemy import select as sa_select

    monkeypatch.setattr(settings, "secrets_encryption_key", Fernet.generate_key().decode())
    type(PROVIDERS["followupboss"])._cf_cache.clear()
    person = {"id": 77, "firstName": "Tony", "lastName": "Fuentes", "name": "Tony Fuentes", "stage": "Lead",
              "phones": [{"value": "+14155559077"}], "emails": [{"value": "tony@fuentesteam.com"}],
              "addresses": [{"street": "12 Oak St", "city": "Orlando", "state": "FL", "code": "32801"}],
              "price": 450000, "source": "Zillow", "assignedTo": "Gabriel Ruiz", "customPropertyType": "Condo"}

    def handler(request: httpx.Request):
        path = request.url.path
        if path == "/v1/me":
            return httpx.Response(200, json={"name": "Jo"})
        if path == "/v1/customFields":
            return httpx.Response(200, json={"customfields": [{"name": "customPropertyType", "label": "Property Type"}]})
        if path == "/v1/people/77":
            return httpx.Response(200, json=person)
        return httpx.Response(200, json={"notes": [], "calls": [], "events": [], "textMessages": [], "emails": []})

    monkeypatch.setattr(BaseHttp, "client_factory",
                        staticmethod(lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    assert client.post("/api/integrations/crm/followupboss/connect", json={"fields": {"api_key": "k"}}).status_code == 200
    agent = client.post("/api/agents/", json={"template": "blank", "name": "Olivia"}).json()
    client.patch(f"/api/agents/{agent['id']}", json={
        "first_message": "Hi {{first_name}}, it's Olivia with {{realtor}}'s team.",
        "system_prompt": "Ask about {{address}} in {{city}} (a {{property_type}}, around {{price}}). Mention {{home_type}}."})

    # Pull the contact's fields before a call (what dispatch does), then fill the agent's variables.
    async def go():
        async with AsyncSessionLocal() as db:
            lead = Lead(org_id=uuid.UUID(client.get("/api/auth/me").json()["org"]["id"]), name="Tony Fuentes",
                        phone="+14155559077", crm_refs={"followupboss": "77"})
            db.add(lead)
            await db.flush()
            await crm_sync.ensure_context(db, lead)
            await db.commit()
            conns = (await db.execute(sa_select(CrmConnection).where(CrmConnection.org_id == lead.org_id))).scalars().all()
            a = await db.get(Agent, uuid.UUID(agent["id"]))
            return crm_vars.apply({"name": "Tony"}, lead, a, list(conns))

    v = aio.run(go())
    assert v["first_name"] == "Tony" and v["address"] == "12 Oak St" and v["city"] == "Orlando"
    assert v["price"] == "$450,000" and v["property_type"] == "Condo"  # custom field, matched by its label
    assert "realtor" in v and v["realtor"] == "Gabriel Ruiz"  # synonym → assigned agent
    assert "home_type" not in v  # no automatic match yet

    # The mapping screen lists the script's variables with sample values; pick a field for {{home_type}}.
    data = client.get("/api/integrations/crm/followupboss/variables", params={"agent_id": agent["id"]}).json()
    rows = {r["name"]: r for r in data["variables"]}
    assert set(rows) >= {"first_name", "realtor", "address", "city", "property_type", "price", "home_type"}
    assert rows["address"]["auto"] == "address" and rows["address"]["sample"] == "12 Oak St"
    assert rows["home_type"]["auto"] is None and any(f["key"] == "property_type" for f in data["fields"])
    assert client.put("/api/integrations/crm/followupboss/variables",
                      json={"agent_id": agent["id"], "map": {"home_type": "property_type", "city": "-"}}).status_code == 200
    v = aio.run(go())
    assert v["home_type"] == "Condo" and "city" not in v
    client.delete("/api/integrations/crm/followupboss")
