"""Per-account phone numbers (Twilio), caller ID on outbound calls, and call recordings."""

import time
import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.config import settings
from app.services import outbound_call, recordings, telephony
from tests.test_accounts import _login, _new_account

TRUNK = "TK_test_trunk"


@pytest.fixture
def twilio(monkeypatch):
    """Fake Twilio at the HTTP layer; `.calls` records (method, path, form)."""
    state = SimpleNamespace(calls=[], owned=[{"sid": "PN_house", "phone_number": "+16282879442",
                                              "friendly_name": "House", "trunk_sid": TRUNK}], lk=[])

    def handler(request: httpx.Request):
        path = request.url.path
        form = dict(httpx.QueryParams(request.content.decode())) if request.content else {}
        state.calls.append((request.method, path, form))
        if path.endswith("/AvailablePhoneNumbers/US/Local.json"):
            return httpx.Response(200, json={"available_phone_numbers": [
                {"phone_number": "+14155550111", "friendly_name": "(415) 555-0111", "locality": "SF", "region": "CA"}]})
        if path.endswith("/IncomingPhoneNumbers.json") and request.method == "GET":
            return httpx.Response(200, json={"incoming_phone_numbers": state.owned})
        if path.endswith("/IncomingPhoneNumbers.json") and request.method == "POST":
            sid = f"PN_{uuid.uuid4().hex[:8]}"
            state.owned.append({"sid": sid, "phone_number": form["PhoneNumber"], "trunk_sid": form.get("TrunkSid")})
            return httpx.Response(201, json={"sid": sid, "phone_number": form["PhoneNumber"]})
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404, json={"message": "unknown"})

    real = httpx.AsyncClient
    monkeypatch.setattr(telephony.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(settings, "twilio_account_sid", "AC_test")
    monkeypatch.setattr(settings, "twilio_auth_token", "secret")
    monkeypatch.setattr(settings, "twilio_trunk_sid", TRUNK)

    async def fake_lk_numbers(add=None, remove=None):
        state.lk.append((add or [], remove or []))

    monkeypatch.setattr(telephony, "_livekit_numbers", fake_lk_numbers)
    return state


def _num() -> str:
    return f"+1415{uuid.uuid4().int % 10_000_000:07d}"


def _account(client, make_client, name, credits=0):
    org, email = _new_account(client, name=name, credits=credits)
    return org, _login(make_client, email)


def test_admin_buys_number_for_account_and_it_is_isolated(client, make_client, twilio):
    org, owner = _account(client, make_client, "Numbers Co")
    _, other = _account(client, make_client, "Other Co")

    found = client.get("/api/admin/phone-numbers/available", params={"area_code": "415"}).json()["numbers"]
    assert found[0]["number"] == "+14155550111"

    r = client.post(f"/api/admin/orgs/{org['id']}/phone-numbers",
                    json={"number": "(415) 555-0111", "mode": "purchase", "label": "Main"})
    assert r.status_code == 201, r.text
    num = r.json()
    assert num["number"] == "+14155550111" and num["source"] == "purchased" and num["is_default"]
    buy = [c for c in twilio.calls if c[0] == "POST"][0]
    assert buy[2]["TrunkSid"] == TRUNK and buy[2]["PhoneNumber"] == "+14155550111"
    assert (["+14155550111"], []) in twilio.lk

    assert [n["number"] for n in owner.get("/api/phone-numbers").json()["numbers"]] == ["+14155550111"]
    assert other.get("/api/phone-numbers").json()["numbers"] == []
    # The same number can't go to a second account.
    assert client.post(f"/api/admin/orgs/{org['id']}/phone-numbers",
                       json={"number": "+14155550111", "mode": "purchase"}).status_code == 502


def test_self_serve_off_means_request_then_admin_fulfills(client, make_client, twilio):
    n, n2 = _num(), _num()
    org, owner = _account(client, make_client, "Request Co")
    assert owner.get("/api/phone-numbers").json()["self_serve"] is False
    assert owner.post("/api/phone-numbers/purchase", json={"number": n}).status_code == 403
    assert not [c for c in twilio.calls if c[0] == "POST"]

    req = owner.post("/api/phone-numbers/requests", json={"area_code": "415"}).json()
    assert any(r["id"] == req["id"] for r in client.get("/api/admin/telephony").json()["open_requests"])
    client.post(f"/api/admin/orgs/{org['id']}/phone-numbers",
                json={"number": n, "mode": "purchase", "request_id": req["id"]})
    mine = owner.get("/api/phone-numbers").json()
    assert mine["requests"][0]["status"] == "fulfilled" and len(mine["numbers"]) == 1


def test_self_serve_purchase_respects_limit(client, make_client, twilio, monkeypatch):
    from app.services.billing import subscriptions

    n, n2 = _num(), _num()
    client.patch("/api/admin/telephony/settings", json={"self_serve_numbers": True, "max_numbers_per_org": 1})
    try:
        _, owner = _account(client, make_client, "Self Serve Co")
        assert owner.get("/api/phone-numbers/available", params={"area_code": "415"}).status_code == 200
        # No plan → the number is sold on its own through Checkout (bought once paid).
        from app.services.billing import purchases

        async def fake_checkout(db, org, user_id, number):
            return f"https://checkout.test/{number}"

        monkeypatch.setattr(purchases, "checkout_phone_number", fake_checkout)
        r = owner.post("/api/phone-numbers/purchase", json={"number": n})
        assert r.status_code == 200 and r.json()["checkout_url"].startswith("https://checkout.test/")
        assert owner.get("/api/phone-numbers").json()["numbers"] == []  # nothing bought before payment
        real = subscriptions.phone_summary

        async def on_plan(db, org_id):
            return {**await real(db, org_id), "subscribed": True, "included": 1}

        monkeypatch.setattr(subscriptions, "phone_summary", on_plan)
        assert owner.post("/api/phone-numbers/purchase", json={"number": n}).status_code == 201
        assert owner.post("/api/phone-numbers/purchase", json={"number": n2}).status_code == 400
    finally:
        client.patch("/api/admin/telephony/settings", json={"self_serve_numbers": False, "max_numbers_per_org": 5})


def test_import_and_release_rules(client, make_client, twilio):
    n, n2 = _num(), _num()
    org, owner = _account(client, make_client, "Import Co")
    imp = client.post(f"/api/admin/orgs/{org['id']}/phone-numbers",
                      json={"number": "+16282879442", "mode": "import"}).json()
    assert imp["source"] == "imported"
    # Not in the Twilio account → refused.
    assert client.post(f"/api/admin/orgs/{org['id']}/phone-numbers",
                       json={"number": "+19998887777", "mode": "import"}).status_code == 502

    # Imported numbers are only unassigned — never deleted from Twilio, even if asked.
    assert client.delete(f"/api/admin/phone-numbers/{imp['id']}", params={"return_to_twilio": True}).status_code == 200
    assert not [c for c in twilio.calls if c[0] == "DELETE"]
    assert owner.get("/api/phone-numbers").json()["numbers"] == []

    bought = client.post(f"/api/admin/orgs/{org['id']}/phone-numbers",
                         json={"number": n, "mode": "purchase"}).json()
    client.delete(f"/api/admin/phone-numbers/{bought['id']}", params={"return_to_twilio": True})
    assert [c for c in twilio.calls if c[0] == "DELETE"]
    # A released number can be assigned again later.
    assert client.post(f"/api/admin/orgs/{org['id']}/phone-numbers",
                       json={"number": "+16282879442", "mode": "import"}).status_code == 201


def test_agent_caller_number_must_belong_to_account(client, make_client, twilio):
    n, n2 = _num(), _num()
    org, owner = _account(client, make_client, "Caller Co")
    other_org, _ = _account(client, make_client, "Caller Other")
    client.post(f"/api/admin/orgs/{other_org['id']}/phone-numbers", json={"number": n, "mode": "purchase"})
    agent = owner.post("/api/agents/", json={"template": "sales_sdr"}).json()
    assert owner.patch(f"/api/agents/{agent['id']}", json={"caller_number": n}).status_code == 400
    client.post(f"/api/admin/orgs/{org['id']}/phone-numbers", json={"number": n2, "mode": "purchase"})
    r = owner.patch(f"/api/agents/{agent['id']}", json={"caller_number": n2})
    assert r.status_code == 200 and r.json()["caller_number"] == n2


class _FakeLK:
    def __init__(self, log):
        async def create_room(req):
            log.append(("room", req))

        async def create_dispatch(req):
            log.append(("dispatch", req))
            return SimpleNamespace(id="AD_1")

        async def create_sip_participant(req, timeout=None):
            log.append(("sip", req))
            return SimpleNamespace(sip_call_id="SCL_1")

        async def aclose():
            pass

        self.room = SimpleNamespace(create_room=create_room)
        self.agent_dispatch = SimpleNamespace(create_dispatch=create_dispatch)
        self.sip = SimpleNamespace(create_sip_participant=create_sip_participant)
        self.aclose = aclose


def test_call_uses_account_number_and_records(client, make_client, twilio, monkeypatch):
    n, n2 = _num(), _num()
    org, owner = _account(client, make_client, "Dial Co", credits=50)
    client.post(f"/api/admin/orgs/{org['id']}/phone-numbers", json={"number": n, "mode": "purchase"})
    log: list = []
    monkeypatch.setattr(outbound_call, "_lk", lambda: _FakeLK(log))
    monkeypatch.setattr(settings, "livekit_sip_outbound_trunk_id", "ST_test")
    for k, v in {"recordings_s3_bucket": "b", "recordings_s3_access_key": "k", "recordings_s3_secret_key": "s"}.items():
        monkeypatch.setattr(settings, k, v)
    started = []

    async def fake_start(room, key):
        started.append((room, key))
        return "EG_1"

    monkeypatch.setattr(recordings, "start", fake_start)

    agent = owner.post("/api/agents/", json={"template": "sales_sdr"}).json()
    r = owner.post(f"/api/agents/{agent['id']}/phone-call", json={"to_phone": "(555) 123-4567"})
    assert r.status_code == 200, r.text
    call_id = r.json()["call_id"]
    for _ in range(50):
        if started:
            break
        time.sleep(0.05)
    sip = next(req for kind, req in log if kind == "sip")
    assert sip.sip_number == n and sip.sip_call_to == "+15551234567"
    room = next(req for kind, req in log if kind == "room").name
    assert room.startswith("call-") and len(room) == len("call-") + 36
    assert started and started[0][1] == f"recordings/{org['id']}/{call_id}.ogg"

    for _ in range(50):
        call = owner.get(f"/api/calls/{call_id}").json()
        if call["has_recording"]:
            break
        time.sleep(0.05)
    assert call["from_phone"] == n and call["has_recording"]

    async def fake_url(key):
        return "https://bucket.example/rec.ogg?sig=1"

    monkeypatch.setattr(recordings, "playback_url", fake_url)
    rec = owner.get(f"/api/calls/{call_id}/recording").json()
    assert rec["status"] == "ready" and rec["url"].startswith("https://")
    # Another account can't reach it.
    _, stranger = _account(client, make_client, "Stranger Co")
    assert stranger.get(f"/api/calls/{call_id}/recording").status_code == 404


def test_recording_off_for_agent_skips_egress(client, make_client, twilio, monkeypatch):
    org, owner = _account(client, make_client, "Quiet Co", credits=50)
    log: list = []
    monkeypatch.setattr(outbound_call, "_lk", lambda: _FakeLK(log))
    monkeypatch.setattr(settings, "livekit_sip_outbound_trunk_id", "ST_test")
    for k, v in {"recordings_s3_bucket": "b", "recordings_s3_access_key": "k", "recordings_s3_secret_key": "s"}.items():
        monkeypatch.setattr(settings, k, v)
    started = []

    async def fake_start(room, key):
        started.append(key)
        return "EG_1"

    monkeypatch.setattr(recordings, "start", fake_start)
    agent = owner.post("/api/agents/", json={"template": "sales_sdr"}).json()
    owner.patch(f"/api/agents/{agent['id']}", json={"record_calls": False})
    call_id = owner.post(f"/api/agents/{agent['id']}/phone-call", json={"to_phone": "+15551234567"}).json()["call_id"]
    for _ in range(20):
        if any(k == "sip" for k, _ in log):
            break
        time.sleep(0.05)
    sip = next(req for kind, req in log if kind == "sip")
    assert sip.sip_number == ""  # no numbers on the account → trunk default
    assert not started
    assert owner.get(f"/api/calls/{call_id}/recording").json()["status"] == "none"


def test_test_call_can_pick_which_number_it_calls_from(client, make_client, twilio, monkeypatch):
    n1, n2 = _num(), _num()
    org, owner = _account(client, make_client, "Pick Co", credits=50)
    for n in (n1, n2):
        client.post(f"/api/admin/orgs/{org['id']}/phone-numbers", json={"number": n, "mode": "purchase"})
    log: list = []
    monkeypatch.setattr(outbound_call, "_lk", lambda: _FakeLK(log))
    monkeypatch.setattr(settings, "livekit_sip_outbound_trunk_id", "ST_test")
    agent = owner.post("/api/agents/", json={"template": "sales_sdr"}).json()

    r = owner.post(f"/api/agents/{agent['id']}/phone-call", json={"to_phone": "+15551234567", "from_number": n2})
    assert r.status_code == 200, r.text
    assert owner.get(f"/api/calls/{r.json()['call_id']}").json()["from_phone"] == n2

    # Only the account's own numbers can be used.
    r = owner.post(f"/api/agents/{agent['id']}/phone-call", json={"to_phone": "+15551234567", "from_number": "+19998887777"})
    assert r.status_code == 400 and "number" in r.json()["detail"]
