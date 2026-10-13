"""Inbound campaigns: an account's own number answered by its agent."""

from app.services import inbound
from tests.test_phone_numbers import _account, _num, twilio  # noqa: F401  (fixture)


def test_inbound_campaign_needs_a_number_and_routes_calls(client, make_client, twilio, monkeypatch):  # noqa: F811
    routed_numbers: list[str] = []

    async def fake_routing(number):
        routed_numbers.append(number)

    monkeypatch.setattr(inbound, "ensure_routing", fake_routing)
    org, owner = _account(client, make_client, "Inbound Co", credits=50)
    agent_id = owner.get("/api/agents/").json()[0]["id"]

    # No number → can't make an inbound campaign.
    r = owner.post("/api/campaigns/", json={"name": "Front desk", "direction": "inbound", "agent_id": agent_id})
    assert r.status_code == 400 and "own phone number" in r.json()["detail"]

    n = _num()
    client.post(f"/api/admin/orgs/{org['id']}/phone-numbers", json={"number": n, "mode": "purchase"})
    number_id = owner.get("/api/phone-numbers").json()["numbers"][0]["id"]

    # Someone else's number isn't allowed.
    _, other = _account(client, make_client, "Other Inbound Co")
    assert other.post("/api/campaigns/", json={"name": "x", "direction": "inbound", "phone_number_id": number_id}).status_code == 404

    camp = owner.post("/api/campaigns/", json={"name": "Front desk", "direction": "inbound", "agent_id": agent_id,
                                               "phone_number_id": number_id}).json()
    # Inbound campaigns go live as soon as they're created.
    assert camp["direction"] == "inbound" and camp["phone_number_id"] == number_id and camp["status"] == "running"
    assert routed_numbers[-1] == n

    r = client.post("/internal/inbound-call", json={"to": n, "from_number": "+14155550999", "room": "call-in-1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["call_type"] == "inbound" and body["agent_id"] == agent_id and body["variables"]["phone"] == "+14155550999"
    calls = owner.get("/api/calls").json()
    items = calls.get("calls") or calls.get("items") or calls
    mine = [c for c in items if c["id"] == body["call_log_id"]]
    assert mine and mine[0]["call_type"] == "inbound" and mine[0]["to_phone"] == "+14155550999"

    # Pausing stops answering; Go live turns it back on.
    owner.post(f"/api/campaigns/{camp['id']}/pause")
    assert client.post("/internal/inbound-call", json={"to": n, "from_number": "+14155550999", "room": "call-x2"}).status_code == 404
    assert owner.post(f"/api/campaigns/{camp['id']}/start").json()["campaign"]["status"] == "running"
    assert client.post("/internal/inbound-call", json={"to": n, "from_number": "+14155550999", "room": "call-x3"}).status_code == 200
