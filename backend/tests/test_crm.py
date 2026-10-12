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
