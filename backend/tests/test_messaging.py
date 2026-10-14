"""Texting through the account's own Twilio / Telnyx credentials."""

import pytest

from app.services import sms

SID = "AC" + "a" * 32


@pytest.fixture
def provider(monkeypatch):
    from cryptography.fernet import Fernet

    from app.config import settings

    monkeypatch.setattr(settings, "secrets_encryption_key", Fernet.generate_key().decode())
    calls = {"verify": [], "send": []}

    async def verify(provider, account_sid, secret, from_number):
        calls["verify"].append((provider, account_sid, secret, from_number))
        if secret == "bad":
            raise sms.SmsError("Those credentials didn't work — check the Account SID and Auth Token.")
        if from_number.endswith("9999"):
            raise sms.SmsError(f"{from_number} isn't a number in that account.")
        return "Acme Realty"

    async def send(provider, account_sid, secret, from_number, to, body, messaging_profile_id=""):
        calls["send"].append((provider, secret, from_number, to, body))
        return "SM1"

    monkeypatch.setattr(sms, "verify", verify)
    monkeypatch.setattr(sms, "send", send)
    return calls


def test_connect_twilio_test_text_and_never_return_the_secret(client, provider):
    assert client.get("/api/phone-numbers/messaging").json() == {"connected": False}
    r = client.put("/api/phone-numbers/messaging", json={"provider": "twilio", "account_sid": SID,
                                                         "secret": "tok-123", "from_number": "(415) 555-0100"})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["connected"] and got["from_number"] == "+14155550100" and got["account_label"] == "Acme Realty"
    assert "tok-123" not in r.text and SID not in r.text  # SID shown masked, token never

    # Updating the number keeps the saved token.
    r = client.put("/api/phone-numbers/messaging", json={"provider": "twilio", "from_number": "+14155550101"})
    assert r.status_code == 200 and provider["verify"][-1] == ("twilio", SID, "tok-123", "+14155550101")

    r = client.post("/api/phone-numbers/messaging/test", json={"to": "415-555-0199"})
    assert r.status_code == 200 and provider["send"][-1][:4] == ("twilio", "tok-123", "+14155550101", "+14155550199")

    assert client.delete("/api/phone-numbers/messaging").json() == {"connected": False}


def test_wrong_credentials_and_foreign_numbers_are_explained(client, provider):
    r = client.put("/api/phone-numbers/messaging", json={"provider": "telnyx", "secret": "bad", "from_number": "+14155550100"})
    assert r.status_code == 400 and "credentials didn't work" in r.json()["detail"]
    r = client.put("/api/phone-numbers/messaging", json={"provider": "telnyx", "secret": "key", "from_number": "+14155559999"})
    assert r.status_code == 400 and r.json()["detail"] == "+14155559999 isn't a number in that account."
    r = client.put("/api/phone-numbers/messaging", json={"provider": "telnyx", "from_number": "+14155550100"})
    assert r.status_code == 400 and r.json()["detail"] == "Enter the API key."
    assert client.post("/api/phone-numbers/messaging/test", json={"to": "+14155550199"}).status_code == 400


def test_twilio_sid_format_is_checked_before_calling_out():
    import asyncio

    with pytest.raises(sms.SmsError, match="starts with AC"):
        asyncio.run(sms.verify("twilio", "nope", "tok", "+14155550100"))


def test_requests_sent_to_each_provider(monkeypatch):
    import asyncio
    import base64
    import json

    import httpx

    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.host == "api.twilio.com":
            if req.url.path.endswith("/Messages.json"):
                return httpx.Response(201, json={"sid": "SM9"})
            return httpx.Response(400, json={"message": "The 'To' number is not valid. See https://www.twilio.com/docs/errors/21211"})
        if "Bearer bad" == req.headers["authorization"]:
            return httpx.Response(401, json={"errors": [{"detail": "Authentication failed"}]})
        return httpx.Response(200, json={"data": {"id": "tx-1"}})

    real = httpx.AsyncClient
    monkeypatch.setattr(sms.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))

    assert asyncio.run(sms.send("twilio", SID, "tok", "+14155550100", "+14155550199", "Hi")) == "SM9"
    tw = seen[-1]
    assert tw.url.path == f"/2010-04-01/Accounts/{SID}/Messages.json"
    assert tw.headers["authorization"] == "Basic " + base64.b64encode(f"{SID}:tok".encode()).decode()
    assert b"To=%2B14155550199" in tw.content and b"Body=Hi" in tw.content

    assert asyncio.run(sms.send("telnyx", "", "key", "+14155550100", "+14155550199", "Hi", "prof-1")) == "tx-1"
    tx = seen[-1]
    assert tx.url.path == "/v2/messages" and json.loads(tx.content) == {
        "from": "+14155550100", "to": "+14155550199", "text": "Hi", "messaging_profile_id": "prof-1"}

    with pytest.raises(sms.SmsError) as e:
        asyncio.run(sms.send("telnyx", "", "bad", "+1", "+1", "x"))
    assert "API key didn't work" in str(e.value)
    with pytest.raises(sms.SmsError) as e:
        asyncio.run(sms._twilio("GET", "/x.json", SID, "tok"))
    assert str(e.value) == "The 'To' number is not valid. See"  # the provider's link is dropped
