"""Bandwidth as a second carrier: Bandwidth rings the contact, then hands the answered call to LiveKit."""

import uuid

import pytest

from app.config import settings
from app.services import bandwidth, outbound_call
from tests.test_phone_numbers import _FakeLK, _account, twilio  # noqa: F401  (fixture)

BW_NUMBER = "+13376040065"
BW_NUMBER_2 = "+13376040066"


@pytest.fixture
def bw(monkeypatch):
    for k, v in {"bandwidth_account_id": "9903791", "bandwidth_client_id": "CLI-test", "bandwidth_client_secret": "sec",
                 "bandwidth_application_id": "app-1", "bandwidth_sip_username": "bsuser",
                 "bandwidth_sip_password": "bspass", "livekit_sip_host": "proj.sip.livekit.cloud",
                 "app_url": "https://blacksync.test", "livekit_sip_outbound_trunk_id": "ST_test"}.items():
        monkeypatch.setattr(settings, k, v)
    placed, trunks = [], []

    async def fake_list():
        return [BW_NUMBER, BW_NUMBER_2]

    class _Resp:
        def __init__(self, status, body):
            self.status_code, self._body = status, body

        def json(self):
            return self._body

    async def fake_request(method, url, **kw):
        placed.append((method, url, kw.get("json")))
        return _Resp(201, {"callId": "c-bw-1"})

    async def fake_bridge(numbers):
        trunks.append(list(numbers))

    monkeypatch.setattr(bandwidth, "list_numbers", fake_list)
    monkeypatch.setattr(bandwidth, "_request", fake_request)
    monkeypatch.setattr(bandwidth, "ensure_bridge_trunk", fake_bridge)
    bandwidth._PENDING.clear()
    return placed, trunks


def test_bandwidth_number_calls_through_bandwidth_and_bridges(client, make_client, twilio, bw, monkeypatch):  # noqa: F811
    placed, trunks = bw
    org, owner = _account(client, make_client, "BW Co", credits=50)
    lk_log: list = []
    monkeypatch.setattr(outbound_call, "_lk", lambda: _FakeLK(lk_log))

    # The Bandwidth number shows up for admins and can be assigned like a Twilio one.
    owned = client.get("/api/admin/telephony").json()["owned"]
    assert any(o["number"] == BW_NUMBER and o["carrier"] == "bandwidth" for o in owned)
    r = client.post(f"/api/admin/orgs/{org['id']}/phone-numbers", json={"number": BW_NUMBER, "mode": "import"})
    assert r.status_code == 201, r.text
    assert trunks == [[BW_NUMBER]]

    agent = owner.post("/api/agents/", json={"template": "sales_sdr"}).json()
    r = owner.post(f"/api/agents/{agent['id']}/phone-call", json={"to_phone": "+14155550123"})
    assert r.status_code == 200, r.text
    call_id = r.json()["call_id"]
    # Bandwidth placed it — no LiveKit room or SIP dial from our side.
    assert not lk_log
    method, url, body = placed[-1]
    assert method == "POST" and url.endswith("/accounts/9903791/calls")
    assert body["from"] == BW_NUMBER and body["to"] == "+14155550123" and body["applicationId"] == "app-1"
    assert body["answerUrl"].startswith(f"https://blacksync.test/api/telephony/bandwidth/answer?c={call_id}&s=")

    # Callbacks need the signature.
    assert client.post(f"/api/telephony/bandwidth/answer?c={call_id}&s=bad").status_code == 403
    answer = body["answerUrl"].replace("https://blacksync.test", "")
    r = client.post(answer, json={"eventType": "answer"})
    assert r.status_code == 200 and "<Transfer>" in r.text
    assert f"sip:{BW_NUMBER}@proj.sip.livekit.cloud" in r.text and 'username="bsuser"' in r.text

    # LiveKit gets the hand-off: the worker is told it's this outbound call, not a new inbound one.
    r = client.post("/internal/inbound-call", json={"to": BW_NUMBER, "from_number": "+14155550123", "room": "call-xyz"})
    assert r.status_code == 200, r.text
    routed = r.json()
    assert routed["call_type"] == "outbound" and routed["call_log_id"] == call_id
    call = owner.get(f"/api/calls/{call_id}").json()
    assert call["status"] == "connected"

    # Once bridged, Bandwidth's hang-up is left to the agent's report.
    disconnect = body["disconnectUrl"].replace("https://blacksync.test", "")
    client.post(disconnect, json={"eventType": "disconnect", "cause": "hangup"})
    assert owner.get(f"/api/calls/{call_id}").json()["status"] == "connected"


def test_unanswered_bandwidth_call_is_no_answer(client, make_client, twilio, bw, monkeypatch):  # noqa: F811
    placed, _ = bw
    org, owner = _account(client, make_client, "BW Ring Co", credits=50)
    monkeypatch.setattr(outbound_call, "_lk", lambda: _FakeLK([]))
    assert client.post(f"/api/admin/orgs/{org['id']}/phone-numbers",
                       json={"number": BW_NUMBER_2, "mode": "import"}).status_code == 201
    agent = owner.post("/api/agents/", json={"template": "sales_sdr"}).json()
    call_id = owner.post(f"/api/agents/{agent['id']}/phone-call", json={"to_phone": "+14155550124"}).json()["call_id"]
    disconnect = placed[-1][2]["disconnectUrl"].replace("https://blacksync.test", "")
    client.post(disconnect, json={"eventType": "disconnect", "cause": "timeout"})
    call = owner.get(f"/api/calls/{call_id}").json()
    assert call["status"] == "no_answer" and call["outcome"] == "no_answer"
    # A stray hand-off for it later isn't treated as that call.
    r = client.post("/internal/inbound-call", json={"to": BW_NUMBER_2, "from_number": "+14155550124", "room": "call-late"})
    assert r.status_code == 404


def test_take_bridge_matches_caller():
    bandwidth._PENDING.clear()
    for cid, to in (("a", "+14155550001"), ("b", "+14155550002")):
        bandwidth._PENDING[cid] = {"number": BW_NUMBER, "to": to, "metadata": {"call_log_id": cid},
                                   "record_key": None, "expires": 9e12, "answered": True}
    assert bandwidth.take_bridge(BW_NUMBER, "+14155550002")["call_log_id"] == "b"
    assert bandwidth.take_bridge(BW_NUMBER, "4155550001")["call_log_id"] == "a"
    assert bandwidth.take_bridge(BW_NUMBER, "+14155550001") is None
    assert uuid  # keep import
