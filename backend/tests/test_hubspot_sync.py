"""HubSpot: Radar scan and lists, two-way sync (call outcomes, lead status, do-not-call), field mapping."""
import datetime as dt
import json

import httpx

from tests.test_re_crms import api, run  # noqa: F401  (fixture)
from app.services.crm.providers import PROVIDERS, CallInfo
from app.services.crm.radar import build_plays

NOW = dt.datetime.now(dt.timezone.utc)


def iso(days):
    return (NOW - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def contact(cid, **props):
    return {"id": str(cid), "properties": {"phone": f"+1415555{cid:04d}", "createdate": iso(30), **props}}


CONTACTS = [
    contact(1, firstname="Hot", recent_conversion_date=iso(1), recent_conversion_event_name="Home valuation",
            num_contacted_notes="0"),
    contact(2, firstname="Never", num_contacted_notes="0"),
    contact(3, firstname="Tried", num_contacted_notes="2", notes_last_contacted=iso(5), hs_lead_status="ATTEMPTED_TO_CONTACT"),
    contact(4, firstname="Cold", num_contacted_notes="4", notes_last_contacted=iso(45), hs_lead_status="CONNECTED",
            hs_last_sales_activity_timestamp=iso(45)),
    contact(5, firstname="Client", lifecyclestage="customer", hs_lifecyclestage_customer_date=iso(400),
            num_contacted_notes="9", notes_last_contacted=iso(300), hs_lead_status="CONNECTED"),
    contact(6, firstname="Dnc", blacksync_do_not_call="true", num_contacted_notes="0"),
    {"id": "7", "properties": {"firstname": "No phone", "createdate": iso(30)}},
]


def hubspot(state):
    def handler(req):
        path, body = req.url.path, json.loads(req.content) if req.content else {}
        state.setdefault("calls", []).append((req.method, path, body))
        if path == "/crm/v3/objects/contacts/search":
            rows = CONTACTS
            for f in (body.get("filterGroups") or [{}])[0].get("filters", []):
                if f["operator"] == "EQ":
                    rows = [r for r in rows if r["properties"].get(f["propertyName"]) == f["value"]]
                if f["propertyName"] == "recent_conversion_date":
                    rows = [r for r in rows if r["properties"].get("recent_conversion_date")]
            return httpx.Response(200, json={"results": rows})
        if path == "/crm/v3/lists/search":
            return httpx.Response(200, json={"lists": [{"listId": 42, "name": "Open house", "objectTypeId": "0-1",
                                                        "additionalProperties": {"hs_list_size": "2"}}]})
        if path == "/crm/v3/lists/42/memberships":
            return httpx.Response(200, json={"results": [{"recordId": "2"}, {"recordId": "3"}]})
        if path == "/crm/v3/objects/contacts/batch/read":
            want = {i["id"] for i in body["inputs"]}
            return httpx.Response(200, json={"results": [r for r in CONTACTS if r["id"] in want]})
        if path.startswith("/crm/v3/properties/contacts/"):
            prop = path.rsplit("/", 1)[1]
            if prop == "blacksync_do_not_call":
                return httpx.Response(404, json={"message": "not found"}) if not state.get("dnc_prop") else httpx.Response(200, json={})
            return httpx.Response(200, json={"options": [{"value": "lead", "label": "Lead"}, {"value": "customer", "label": "Customer"}]})
        if path == "/crm/v3/properties/contacts" and req.method == "POST":
            state["dnc_prop"] = True
            return httpx.Response(201, json={"name": "blacksync_do_not_call"})
        if path == "/crm/v3/properties/contacts":
            return httpx.Response(200, json={"results": [{"name": "property_address", "label": "Property address"},
                                                         {"name": "hs_secret", "label": "Internal"}]})
        if path == "/crm/v3/pipelines/deals":
            return httpx.Response(200, json={"results": [{"id": "p1", "label": "Sales", "stages": [
                {"id": "s1", "label": "New", "displayOrder": 0, "metadata": {"probability": "0.1"}}]}]})
        if path == "/crm/v3/objects/deals/search":
            return httpx.Response(200, json={"results": [{"id": "d1"}]})
        if path == "/crm/v4/associations/deals/contacts/batch/read":
            return httpx.Response(200, json={"results": [{"from": {"id": "d1"}, "to": [{"toObjectId": 4}]}]})
        if path.startswith("/crm/v3/objects/contacts/") and req.method == "GET":
            return httpx.Response(200, json={"id": "3", "properties": {"hs_lead_status": state.get("status", "NEW"),
                                                                       "property_address": "12 Oak St"}})
        if path.startswith("/crm/v3/objects/contacts/") and req.method == "PATCH":
            state["patched"] = body["properties"]
            return httpx.Response(200, json={"id": "3"})
        if path == "/crm/v3/objects/calls":
            return httpx.Response(201, json={"id": "c1"})
        return httpx.Response(404, json={"message": f"unexpected {path}"})
    return handler


def test_hubspot_radar_scan_fills_every_card(api):
    p = PROVIDERS["hubspot"]
    http = p.native_http("tok", {})
    api["handler"] = hubspot({})
    signals = run(p.scan_signals(http, {}, depth="recent"))
    plays = {pl["key"]: [i["name"] for i in pl["items"]] for pl in build_plays(signals, now=NOW)["plays"]}
    assert plays["hot"] == ["Hot"]
    assert plays["never_called"] == ["Never"]
    assert plays["unreached"] == ["Tried"]
    assert plays["went_cold"] == ["Cold"]
    assert plays["past_client"] == ["Client"]
    assert not any("Dnc" in names for names in plays.values())  # do-not-call is never in a play


def test_hubspot_lists_stages_and_deal_stages(api):
    p = PROVIDERS["hubspot"]
    http = p.native_http("tok", {})
    api["handler"] = hubspot({})
    opts = run(p.segment_options(http, {}))
    assert opts["list"] == [{"value": "42", "label": "Open house (2)"}]
    assert {"value": "lifecyclestage:customer", "label": "Lifecycle · Customer"} in opts["stage"]
    assert opts["deal"] == [{"value": "p1:s1", "label": "Sales · New"}]
    assert [s.name for s in run(p.segment_signals(http, {}, "list", "42"))] == ["Never", "Tried"]
    assert [s.name for s in run(p.segment_signals(http, {}, "stage", "lifecyclestage:customer"))] == ["Client"]
    assert [s.name for s in run(p.segment_signals(http, {}, "deal", "p1:s1"))] == ["Cold"]


def test_hubspot_two_way_call_outcome_lead_status_and_dnc(api):
    p = PROVIDERS["hubspot"]
    http = p.native_http("tok", {})
    state = {"status": "NEW"}
    api["handler"] = hubspot(state)
    call = CallInfo(call_id="x", outcome="voicemail", duration_seconds=20, phone="+14155550003", started_at=NOW)
    run(p.log_call(http, {}, "3", call))
    logged = next(b for m, path, b in state["calls"] if path == "/crm/v3/objects/calls")
    assert logged["properties"]["hs_call_disposition"] == p._DISPOSITION["voicemail"]
    assert state["patched"] == {"hs_lead_status": "ATTEMPTED_TO_CONTACT"}  # NEW → attempted
    state.pop("patched")
    state["status"] = "IN_PROGRESS"  # someone on the team is working them: never moved back
    run(p.log_call(http, {}, "3", CallInfo(call_id="y", outcome="interested", duration_seconds=90, phone="+1", started_at=NOW)))
    assert "patched" not in state
    run(p.mark_dnc(http, {}, "3"))
    assert state["patched"] == {"hs_lead_status": "UNQUALIFIED", "blacksync_do_not_call": "true"}  # property created on first use


def test_hubspot_field_mapping_and_speed_to_lead(api):
    p = PROVIDERS["hubspot"]
    http = p.native_http("tok", {})
    api["handler"] = hubspot({})
    keys = [f["key"] for f in run(p.field_catalog(http, {}))]
    assert "property_address" in keys and "hs_secret" not in keys and "firstname" in keys
    assert run(p.person_fields(http, {}, "3"))["property_address"] == "12 Oak St"
    hits = run(p.recent_activity(http, {}, NOW - dt.timedelta(days=3)))
    assert [(h["contact"].name, h["kind"]) for h in hits] == [("Hot", "Form: Home valuation")]
