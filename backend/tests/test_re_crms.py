"""BoldTrail/kvCORE, Lofty and Sierra Interactive connectors send what each API documents."""

import asyncio
import datetime as dt
import json

import httpx
import pytest

from app.services.crm.http import BaseHttp, CrmError
from app.services.crm.providers import PROVIDERS, CallInfo, Contact


@pytest.fixture
def api(monkeypatch):
    """Route requests to a handler per test; record them."""
    state = {"handler": None, "seen": []}

    def transport(req):
        state["seen"].append(req)
        return state["handler"](req)

    monkeypatch.setattr(BaseHttp, "client_factory", staticmethod(
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(transport), timeout=5)))
    return state


def run(coro):
    return asyncio.run(coro)


CALL = CallInfo(call_id="c1", outcome="interested", summary="Wants a tour Saturday.", duration_seconds=95,
                phone="+14155550123", started_at=dt.datetime(2026, 10, 14, 15, 0, tzinfo=dt.timezone.utc))


def test_boldtrail(api):
    p = PROVIDERS["boldtrail"]
    http = p.native_http("tok", {})

    def handler(req):
        if req.method == "GET" and req.url.path == "/v2/public/contacts":
            if "filter[email]" in req.url.params:
                return httpx.Response(200, json={"data": [{"id": 77}], "total": 1})
            if req.url.params.get("limit") == "1":
                return httpx.Response(200, json={"data": [], "total": 1234})
            page = int(req.url.params["page"])
            rows = [{"id": 1, "name": "Ann Lee", "cell_phone_1": "4155550101", "status": 4},
                    {"id": 2, "name": "No Phone"}] if page == 1 else [{"id": 3, "name": "Bo Diaz", "home_phone": "4155550102"}]
            return httpx.Response(200, json={"data": rows, "current_page": page, "last_page": 2})
        if req.method == "PUT" and req.url.path == "/v2/public/contact/77/action/call":
            return httpx.Response(200, json={"success": True})
        return httpx.Response(404, json={})

    api["handler"] = handler
    assert run(p.verify(http, {})) == "1,234 contacts"
    assert api["seen"][-1].headers["authorization"] == "Bearer tok"
    assert run(p.find_or_create(http, {}, Contact("Ann Lee", "+14155550101", "ann@x.com"), create=False)) == "77"
    run(p.log_call(http, {}, "77", CALL))
    body = json.loads(api["seen"][-1].content)
    assert body["result"] == 3 and body["direction"] == "outbound" and "Wants a tour" in body["notes"]
    got = run(p.list_contacts(http, {}, limit=10))
    assert [(c.external_id, c.phone, c.stage) for c in got] == [("1", "4155550101", "Active"), ("3", "4155550102", "")]


def test_lofty(api):
    p = PROVIDERS["lofty"]
    http = p.native_http("key1", {})

    def handler(req):
        path = req.url.path
        if path == "/v1.0/me":
            return httpx.Response(200, json={"firstName": "Gabe", "lastName": "Ruiz"})
        if req.method == "GET" and path == "/v1.0/leads":
            if req.url.params.get("phone") == "4155550101":
                return httpx.Response(200, json={"leads": [{"leadId": 900}]})
            if "email" in req.url.params or "phone" in req.url.params:
                return httpx.Response(200, json={"leads": []})
            return httpx.Response(200, json={"leads": [
                {"leadId": 5, "firstName": "New", "phones": ["4155550105"], "createTime": "2026-10-14T12:00:00Z",
                 "stage": "New Lead", "tags": [{"tagName": "Buyer"}], "cannotCall": False},
                {"leadId": 4, "firstName": "Old", "phones": ["4155550104"], "createTime": "2026-10-01T12:00:00Z"}]})
        if req.method == "POST" and path == "/v1.0/leads":
            return httpx.Response(200, json={"leadId": 901})
        if path == "/v1.0/logType":
            return httpx.Response(200, json={"code": 0})
        if path == "/v1.0/leads/5":
            return httpx.Response(200, json={"lead": {"firstName": "New", "phones": ["4155550105"],
                                                      "leadPropertyList": [{"streetAddress": "12 Oak St", "city": "Austin", "state": "TX", "zipCode": "78701"}],
                                                      "leadInquiry": {"priceMin": 400000, "priceMax": 550000},
                                                      "customAttributes": [{"attributeName": "Timeframe", "value": "3 months"}]}})
        return httpx.Response(404, json={})

    api["handler"] = handler
    assert run(p.verify(http, {})) == "Gabe Ruiz"
    assert api["seen"][-1].headers["authorization"] == "token key1"
    assert run(p.find_or_create(http, {}, Contact("X", "+14155550101", "x@y.com"), create=False)) == "900"
    assert run(p.find_or_create(http, {}, Contact("Jo Park", "+14155550199", ""), create=True)) == "901"
    run(p.log_call(http, {}, "900", CALL))
    body = json.loads(api["seen"][-1].content)
    assert body == {"leadId": 900, "logType": "logCall", "content": body["content"], "leadPhoneNumber": "4155550123",
                    "callingOutcome": "Talked", "outboundOrInbound": "outbound", "isPin": False}
    since = dt.datetime(2026, 10, 10, tzinfo=dt.timezone.utc)
    new = run(p.list_contacts(http, {}, limit=50, since=since))
    assert [(c.external_id, c.stage, c.tags) for c in new] == [("5", "New Lead", ["Buyer"])]
    f = run(p.person_fields(http, {}, "5"))
    assert f["full_address"] == "12 Oak St, Austin, TX 78701" and f["price"] == "$400,000–$550,000" and f["timeframe"] == "3 months"


def test_lofty_pipelines_and_stage(api):
    p = PROVIDERS["lofty"]
    http = p.native_http("key1", {})

    def handler(req):
        path = req.url.path
        if path == "/v1.0/teamFeatures/lead-pipelines":
            return httpx.Response(200, json={"pipelines": [{"id": 1, "name": "Main",
                "stages": [{"id": 10, "name": "New Lead"}, {"id": 11, "name": "Contacted"}]}]})
        if req.method == "PUT" and path == "/v1.0/leads/5":
            return httpx.Response(200, json={"leadId": 5})
        if req.method == "GET" and path == "/v1.0/leads":
            return httpx.Response(200, json={"leads": [
                {"leadId": 1, "stage": "Active", "phones": ["4155550101"]},
                {"leadId": 2, "stage": "New Lead", "phones": ["4155550102"]}]})
        return httpx.Response(404, json={})

    api["handler"] = handler
    pipes = run(p.pipelines(http, {}))
    assert pipes[0]["stages"][1]["label"] == "Contacted"
    assert run(p.set_stage(http, {}, "5", pipes[0], "11", create=False, forward_only=True)) == "Moved to Contacted"
    body = json.loads(api["seen"][-1].content)
    assert body == {"stage": "Contacted"}
    run(p.mark_dnc(http, {}, "5"))
    assert json.loads(api["seen"][-1].content) == {"cannotCall": True}


def test_lofty_pipelines_fallback_from_leads(api):
    from app.services.crm.http import CrmError
    p = PROVIDERS["lofty"]
    http = p.native_http("key1", {})

    def handler(req):
        if req.url.path == "/v1.0/teamFeatures/lead-pipelines":
            return httpx.Response(403, json={"code": 200127, "message": "key scope"})
        if req.url.path == "/v1.0/leads":
            return httpx.Response(200, json={"leads": [
                {"leadId": 1, "stage": "Active", "phones": ["4155550101"]},
                {"leadId": 2, "stage": "New Lead", "phones": ["4155550102"]}]})
        return httpx.Response(404, json={})

    api["handler"] = handler
    pipes = run(p.pipelines(http, {}))
    assert pipes[0]["id"] == "lofty-stages"
    assert [s["label"] for s in pipes[0]["stages"]] == ["Active", "New Lead"]


def test_lofty_radar_scan(api):
    from app.services.crm.radar import build_plays

    p = PROVIDERS["lofty"]
    assert p.can_scan
    http = p.native_http("key1", {})
    now = dt.datetime.now(dt.timezone.utc)
    leads = [
        {"leadId": 5, "firstName": "Hot", "lastName": "Inbound", "phones": ["4155550105"], "emails": ["hot@x.com"],
         "createTime": (now - dt.timedelta(days=2)).isoformat(), "updateTime": (now - dt.timedelta(days=2)).isoformat(),
         "stage": "New Lead", "source": "Zillow", "tags": [{"tagName": "Buyer"}], "cannotCall": False},
        {"leadId": 4, "firstName": "Never", "lastName": "Called", "phones": ["4155550104"],
         "createTime": (now - dt.timedelta(days=10)).isoformat(), "stage": "Active", "source": "Website",
         "tags": [], "cannotCall": False},
        {"leadId": 7, "firstName": "Old", "lastName": "Lead", "phones": ["4155550107"],
         "createTime": (now - dt.timedelta(days=400)).isoformat(), "updateTime": (now - dt.timedelta(days=395)).isoformat(), "stage": "Active", "tags": [], "cannotCall": False},
        {"leadId": 8, "firstName": "Fresh", "lastName": "Signup", "phones": ["4155550108"],
         "createTime": (now - dt.timedelta(days=3)).isoformat(), "updateTime": (now - dt.timedelta(days=3)).isoformat(),
         "stage": "New Lead", "source": "Website", "tags": [], "cannotCall": False},
        {"leadId": 6, "firstName": "Dnc", "lastName": "Dude", "phones": ["4155550106"],
         "createTime": (now - dt.timedelta(days=1)).isoformat(), "stage": "New Lead", "cannotCall": True},
    ]
    def handler(req):
        path = req.url.path
        if req.method == "GET" and path == "/v1.0/leads":
            assert req.url.params["sort"] in ("CreateTime", "LastActivity"), req.url.params
            return httpx.Response(200, json={"leads": leads})
        if req.method == "GET" and path == "/v1.0/communication/call":
            lid = req.url.params["leadId"]
            calls = {"5": [{"leadId": 5, "direction": "Inbound", "status": "Completed", "duration": 200,
                            "startTime": (now - dt.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")}],
                     "4": [{"leadId": 4, "direction": "Outbound", "status": "NoAnswer", "duration": 0,
                            "startTime": (now - dt.timedelta(days=4)).strftime("%Y-%m-%d %H:%M:%S")},
                           {"leadId": 4, "direction": "Outbound", "status": "NoAnswer", "duration": 0,
                            "startTime": (now - dt.timedelta(days=6)).strftime("%Y-%m-%d %H:%M:%S")}]}.get(lid, [])
            return httpx.Response(200, json={"calls": calls})
        if req.method == "GET" and path.endswith("/activities"):
            return httpx.Response(200, json={"activities": []})
        return httpx.Response(404, json={})

    api["handler"] = handler
    signals = run(p.scan_signals(http, {}, limit=100, depth="recent"))
    by_id = {s.external_id: s for s in signals}
    assert set(by_id) == {"4", "5", "6", "7", "8"}
    assert by_id["5"].last_inbound_at and by_id["5"].inbound_kind == "Called you"
    assert by_id["4"].calls == 2 and by_id["4"].connected_calls == 0
    assert by_id["4"].last_call_result == "NoAnswer" and by_id["4"].calls_known
    assert by_id["6"].dnc is True
    plays = {pl["key"]: pl for pl in build_plays(signals, now=now)["plays"]}
    assert [i["external_id"] for i in plays["hot"]["items"]] == ["5"]
    assert [i["external_id"] for i in plays["unreached"]["items"]] == ["4"]
    assert [i["external_id"] for i in plays["never_called"]["items"]] == ["7", "8"]
    assert not any(i["external_id"] == "6" for pl in plays.values() for i in pl["items"])

    n_seen = len(api["seen"])
    quick = run(p.scan_signals(http, {}, limit=100, depth="quick"))
    assert all(s.calls_known for s in quick)  # quick reads call counts for its (small) batch
    assert any(r.url.path == "/v1.0/communication/call" for r in api["seen"][n_seen:])
    assert not any(r.url.path.endswith("/activities") for r in api["seen"][n_seen:])  # but never activities
    quick_plays = {pl["key"]: pl for pl in build_plays(quick, now=now)["plays"]}
    assert [i["external_id"] for i in quick_plays["never_called"]["items"]] == ["8"]
    assert [i["external_id"] for i in quick_plays["revive"]["items"]] == ["7"]


def test_lofty_radar_segments(api):
    p = PROVIDERS["lofty"]
    assert p.can_segment
    http = p.native_http("key1", {})

    def handler(req):
        path, q = req.url.path, dict(req.url.params)
        if path == "/v1.0/team-features/lead-ponds":
            return httpx.Response(200, json=[{"id": 7, "pondName": "Buyers"}, {"id": 9, "pondName": "Sellers"}])
        if path == "/v1.0/teamFeatures/lead-pipelines":
            return httpx.Response(200, json={"pipelines": [{"id": 1, "name": "Main",
                "stages": [{"name": "New Lead"}, {"name": "Active"}]}], "get_metadata": {"total": 1}})
        if path == "/v1.0/leads":
            rows = [{"leadId": 5, "firstName": "Jane", "phones": ["4155550105"], "stage": "New Lead",
                     "source": "Zillow", "pondId": 7, "createTime": "2026-10-30T12:00:00Z"},
                    {"leadId": 4, "firstName": "Bob", "phones": ["4155550104"], "stage": "Active",
                     "source": "Website", "pondId": 9, "createTime": "2026-10-01T12:00:00Z"}]
            if q.get("pondId"):
                rows = [r for r in rows if str(r.get("pondId")) == q["pondId"]]
            if q.get("stage"):
                rows = [r for r in rows if r.get("stage") == q["stage"]]
            return httpx.Response(200, json={"leads": rows})
        return httpx.Response(404, json={})

    api["handler"] = handler
    opts = run(p.segment_options(http, {}))
    assert {"value": "7", "label": "Buyers"} in opts["pond"]
    assert {"value": "New Lead", "label": "New Lead"} in opts["stage"]
    assert {"value": "Zillow", "label": "Zillow"} in opts["source"]
    assert opts["deal"] == []
    pond = run(p.segment_signals(http, {}, "pond", "7"))
    assert [s.external_id for s in pond] == ["5"]
    stage = run(p.segment_signals(http, {}, "stage", "Active"))
    assert [s.external_id for s in stage] == ["4"]


def test_sierra(api):
    p = PROVIDERS["sierra"]
    http = p.native_http("sk", {})

    def handler(req):
        path = req.url.path
        if path == "/users":
            return httpx.Response(200, json={"success": True, "data": {"records": [{"siteName": "Ruiz Team"}]}})
        if path == "/leads/find":
            if req.url.params.get("email") == "a@b.com":
                return httpx.Response(200, json={"success": True, "data": {"leads": [{"id": 31}]}})
            if "email" in req.url.params or "phone" in req.url.params:
                return httpx.Response(200, json={"success": True, "data": {"leads": []}})
            return httpx.Response(200, json={"success": True, "data": {"totalPages": 1, "leads": [
                {"id": 40, "firstName": "Lia", "phone": "(415) 555-0140", "creationDate": "2026-10-14T10:00:00Z", "leadStatus": "New"}]}})
        if path == "/leads/31/note":
            return httpx.Response(200, json={"success": True, "data": {}})
        if path == "/leads" and req.method == "POST":
            return httpx.Response(200, json={"success": False, "errorMessage": "Email already exists"})
        return httpx.Response(404, json={})

    api["handler"] = handler
    assert run(p.verify(http, {})) == "Ruiz Team"
    seen = api["seen"][-1]
    assert seen.headers["sierra-apikey"] == "sk" and seen.headers["sierra-originatingsystemname"] == "BlackSync AI"
    assert run(p.find_or_create(http, {}, Contact("A", "+14155550101", "a@b.com"), create=False)) == "31"
    # No email → Sierra can't create a lead; nothing is sent.
    assert run(p.find_or_create(http, {}, Contact("B", "+14155550102", ""), create=True)) is None
    with pytest.raises(CrmError, match="already exists"):
        run(p.find_or_create(http, {}, Contact("C", "+14155550103", "c@d.com"), create=True))
    run(p.log_call(http, {}, "31", CALL))
    body = json.loads(api["seen"][-1].content)
    assert body["shouldNotify"] is False and body["message"].startswith("AI call:")
    leads = run(p.list_contacts(http, {}, limit=10, since=dt.datetime(2026, 10, 13, tzinfo=dt.timezone.utc)))
    assert [(c.external_id, c.stage) for c in leads] == [("40", "New")]
    assert api["seen"][-1].url.params["leadCreationDateFrom"] == "10/13/2026"


def test_totalexpert(api):
    from app.services.crm.http import TotalExpertHttp

    TotalExpertHttp._tokens.clear()
    p = PROVIDERS["totalexpert"]
    cfg = {"client_id": "cid", "owner": "jane.lo"}
    http = p.native_http("sec", cfg)
    tokens = iter(["t1", "t2"])
    state = {"expired": False}

    def handler(req):
        path = req.url.path
        if path == "/v1/token":
            assert req.headers["authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": next(tokens), "expires_in": 3600})
        if state["expired"] and req.headers["authorization"] == "Bearer t1":
            return httpx.Response(401, json={"error": "expired"})
        if req.method == "GET" and path == "/v1/contacts":
            flt = req.url.params.get("filter", "")
            if flt == "email=ann@x.com":
                return httpx.Response(200, json={"items": [], "links": {"next": None}})
            if flt == "phone_cell=(415)555-0101":
                return httpx.Response(200, json={"items": [{"id": 77}], "links": {"next": None}})
            if flt.startswith("phone_"):
                return httpx.Response(200, json={"items": [], "links": {"next": None}})
            page = int(req.url.params.get("page[number]", 1))
            rows = [{"id": 1, "first_name": "Ann", "last_name": "Lee", "phone_cell": "(415)555-0101", "ok_to_call": 1},
                    {"id": 2, "first_name": "No", "last_name": "Phone"}] if page == 1 else \
                [{"id": 3, "first_name": "Bo", "last_name": "Diaz", "phone_home": "(415)555-0102", "ok_to_call": 0}]
            return httpx.Response(200, json={"items": rows, "links": {"next": 2 if page == 1 else None}})
        if req.method == "POST" and path == "/v1/contacts":
            return httpx.Response(201, json={"id": 88})
        if req.method == "POST" and path == "/v1/contact-notes":
            return httpx.Response(201, json={"id": 5})
        if req.method == "PATCH" and path == "/v1/contacts/77":
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={})

    api["handler"] = handler
    assert run(p.verify(http, cfg)) == "Total Expert (jane.lo)"
    assert run(p.find_or_create(http, cfg, Contact("Ann Lee", "+14155550101", "ann@x.com"), create=False)) == "77"
    assert run(p.find_or_create(http, cfg, Contact("Cy", "+14155550199"), create=True)) == "88"
    body = json.loads(api["seen"][-1].content)
    assert body == {"source": "BlackSync AI", "first_name": "Cy", "last_name": "Lead", "phone_cell": "(415)555-0199",
                    "owner": {"username": "jane.lo"}}

    state["expired"] = True  # token expires: fetch a new one and retry
    run(p.log_call(http, cfg, "77", CALL))
    note = json.loads(api["seen"][-1].content)
    assert api["seen"][-1].headers["authorization"] == "Bearer t2"
    assert note["contact"] == {"id": 77} and note["type_id"] == 7 and "Wants a tour" in note["note"]
    assert note["owner"] == {"username": "jane.lo"}

    contacts = run(p.list_contacts(http, cfg))
    assert [(c.external_id, c.dnc) for c in contacts] == [("1", False), ("3", True)]
    run(p.mark_dnc(http, cfg, "77"))
    assert json.loads(api["seen"][-1].content) == {"ok_to_call": 0}


def test_totalexpert_bad_credentials(api):
    from app.services.crm.http import TotalExpertHttp

    TotalExpertHttp._tokens.clear()
    api["handler"] = lambda req: httpx.Response(401, json={"error": "invalid_client"})
    p = PROVIDERS["totalexpert"]
    with pytest.raises(CrmError, match="client ID and secret"):
        run(p.verify(p.native_http("bad", {"client_id": "x"}), {}))
