"""The connector's Lead Finder, Radar, contact, campaign, meeting and CRM tools."""

import datetime as dt
import uuid

from tests.test_connector import _connect, _tool
from tests.test_crm import RESPONSES, http_mock  # noqa: F401  (fixture)
from tests.test_lead_finder import _addr, provider  # noqa: F401  (fixture)


def test_lead_finder_from_the_assistant(client, make_client, provider):  # noqa: F811
    anon = make_client()
    token = _connect(client, anon)["access_token"]
    org_id = client.get("/api/auth/me").json()["org"]["id"]
    client.patch(f"/api/admin/orgs/{org_id}", json={"lead_finder_enabled": True})
    client.post(f"/api/admin/orgs/{org_id}/lead-credits", json={"amount": 5})

    status, err = _tool(anon, token, "lead_finder_status")
    assert not err and status["enabled"]
    found, err = _tool(anon, token, "lookup_property", {"address": "1252 E 21st St, Erie, PA 16503"})
    assert not err and found["found"] and found["result"]["phones"], found
    again, _ = _tool(anon, token, "lookup_property", {**_addr(2)})
    assert again["cached"] is True and len(provider.calls) == 1
    listed, _ = _tool(anon, token, "list_property_lookups")
    assert any(i["id"] == found["id"] for i in listed["items"])

    agent = client.post("/api/agents/", json={"template": "blank"}).json()
    camp, _ = _tool(anon, token, "create_campaign", {"name": "Owners", "agent_id": agent["id"]})
    saved, err = _tool(anon, token, "save_lookup_to_contacts", {"lookup_id": found["id"], "campaign_id": camp["id"]})
    assert not err and saved["contact_id"], saved
    contact, _ = _tool(anon, token, "get_contact", {"contact_id": saved["contact_id"]})
    assert contact["campaign_id"] == camp["id"]
    in_camp, _ = _tool(anon, token, "list_campaign_contacts", {"campaign_id": camp["id"]})
    assert [c["id"] for c in in_camp["contacts"]] == [saved["contact_id"]]

    prep, err = _tool(anon, token, "bulk_lookup_prepare",
                      {"csv": "street,city,state,zip\n1300 Main St,Erie,PA,16503\n900 Oak St,Erie,PA,16503\n"})
    assert not err and prep["valid"] == 2 and prep["new_rows"] == 2, prep
    run, err = _tool(anon, token, "bulk_lookup_start", {"batch_id": prep["id"]})
    assert not err and run["status"] in ("running", "completed"), run
    got, err = _tool(anon, token, "get_bulk_lookup", {"batch_id": prep["id"]})
    assert not err and got["id"] == prep["id"]
    batches, _ = _tool(anon, token, "get_bulk_lookup")
    assert any(b["id"] == prep["id"] for b in batches["items"])

    bad, err = _tool(anon, token, "lookup_property", {})
    assert err and "address" in bad["error"]


def test_lookup_asks_before_charging(client, make_client, provider):  # noqa: F811
    anon = make_client()
    token = _connect(client, anon)["access_token"]
    org_id = client.get("/api/auth/me").json()["org"]["id"]
    client.patch(f"/api/admin/orgs/{org_id}", json={"lead_finder_enabled": True})
    client.patch("/api/admin/billing/settings", json={"lookup_free_daily": 0, "property_lookup_price_cents": 25})
    try:
        usage = client.get("/api/lead-finder/usage").json()
        if usage["credits"] or usage["unlimited"]:
            client.post(f"/api/admin/orgs/{org_id}/lead-credits", json={"amount": -usage["credits"]})
            client.patch(f"/api/admin/orgs/{org_id}", json={"lead_credits_unlimited": False})
        out, err = _tool(anon, token, "lookup_property", _addr(77))
        assert not err and out["needs_confirmation"] and out["price_cents"] == 25, out
        assert "expected_price_cents=25" in out["message"] and not provider.calls  # nothing looked up or charged
    finally:
        client.patch("/api/admin/billing/settings", json={"lookup_free_daily": 5, "clear_lookup_price": True})


def test_contacts_campaigns_and_meetings(client, make_client):
    anon = make_client()
    token = _connect(client, anon)["access_token"]
    agent = client.post("/api/agents/", json={"template": "blank"}).json()
    camp, _ = _tool(anon, token, "create_campaign", {"name": "Tools", "agent_id": agent["id"]})
    phone = f"+1415556{uuid.uuid4().int % 10000:04d}"
    _tool(anon, token, "add_contacts", {"contacts": [{"name": "Pat Doe", "phone": phone}]})
    cid = _tool(anon, token, "list_contacts", {"query": "Pat Doe"})[0]["contacts"][0]["id"]

    upd, err = _tool(anon, token, "update_contact", {"contact_id": cid, "status": "interested", "tags": ["vip"]})
    assert not err and upd["status"] == "interested" and upd["tags"] == ["vip"]
    out, err = _tool(anon, token, "bulk_update_contacts", {"contact_ids": [cid], "action": "add_to_campaign",
                                                           "campaign_id": camp["id"]})
    assert not err and out["updated"] == 1
    _, err = _tool(anon, token, "bulk_update_contacts", {"contact_ids": [cid], "action": "delete"})
    assert err  # deleting isn't offered to assistants

    edited, err = _tool(anon, token, "update_campaign", {"campaign_id": camp["id"], "call_window_start": "10:00",
                                                         "max_concurrent_calls": 3})
    assert not err and edited["call_window_start"] == "10:00" and edited["max_concurrent_calls"] == 3, edited

    meetings, err = _tool(anon, token, "list_meetings", {"upcoming_only": True})
    assert not err and "stats" in meetings
    bad, err = _tool(anon, token, "update_meeting", {"call_id": str(uuid.uuid4()), "status": "completed"})
    assert err and "not found" in bad["error"].lower()


def test_radar_from_the_assistant(client, make_client, http_mock):  # noqa: F811
    state, _ = http_mock
    now = dt.datetime.now(dt.timezone.utc)
    iso = lambda days: (now - dt.timedelta(days=days)).isoformat()
    state["responses"] = {
        **RESPONSES["close"],
        ("GET", "/v1/lead/"): {"has_more": False, "data": [
            {"id": "lead_a", "display_name": "Alpha", "date_created": iso(10), "status_label": "Potential",
             "contacts": [{"name": "Al", "phones": [{"phone": "+14155557001"}]}], "opportunities": []},
            {"id": "lead_b", "display_name": "Beta", "date_created": iso(20), "status_label": "Potential",
             "contacts": [{"name": "Bo", "phones": [{"phone": "+14155557002"}]}], "opportunities": []}]},
        ("GET", "/v1/activity/call/"): {"has_more": False, "data": [
            {"lead_id": "lead_b", "date_created": iso(13), "disposition": "no-answer", "direction": "outbound"}]},
        ("GET", "/v1/activity/email/"): {"has_more": False, "data": []},
        ("GET", "/v1/activity/sms/"): {"has_more": False, "data": []},
        ("GET", "/v1/activity/form_submission/"): {"has_more": False, "data": []},
    }
    assert client.post("/api/integrations/crm/close/connect", json={"fields": {"api_key": "k"}}).status_code == 200
    anon = make_client()
    token = _connect(client, anon)["access_token"]
    try:
        crms, err = _tool(anon, token, "list_crm_integrations")
        assert not err and any(c["crm"] == "close" for c in crms["connected"])
        scan, err = _tool(anon, token, "radar_scan", {"crm": "close"})
        assert not err, scan
        plays = {p["play"]: p for p in scan["plays"]}
        assert plays["unreached"]["count"] == 1 and plays["unreached"]["top"][0]["phone"]
        people, err = _tool(anon, token, "radar_play", {"scan_id": scan["scan_id"], "play": "never_called"})
        assert not err and people["count"] == 1 and len(people["people"]) == 1
        over, _ = _tool(anon, token, "radar_overview")
        assert next(c for c in over["crms"] if c["crm"] == "close")["last_scan"]["scan_id"] == scan["scan_id"]

        agent = client.post("/api/agents/", json={"template": "blank"}).json()
        out, err = _tool(anon, token, "radar_launch", {"scan_id": scan["scan_id"], "play": "unreached",
                                                       "agent_id": agent["id"], "mode": "campaign"})
        assert not err and out["contacts"] == 1 and out["url"].endswith(out["campaign_id"]), out
        bad, err = _tool(anon, token, "radar_launch", {"scan_id": scan["scan_id"], "play": "unreached",
                                                       "agent_id": agent["id"], "mode": "pipeline"})
        assert err and "pipeline" in bad["error"]
        log, err = _tool(anon, token, "crm_activity", {"crm": "close"})
        assert not err and any("Radar" in i["message"] for i in log["items"])
        _, err = _tool(anon, token, "radar_scan", {"crm": "hubspot"})
        assert err
    finally:
        client.delete("/api/integrations/crm/close")
