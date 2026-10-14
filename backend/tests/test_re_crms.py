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
