"""Native Salesforce OAuth: login URL, callback → saved connection, and token refresh on expiry."""

import asyncio
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet

from app.config import settings
from app.services.crm import salesforce_oauth as sf
from app.services.crm.http import BaseHttp, SalesforceHttp


@pytest.fixture
def sf_app(monkeypatch):
    monkeypatch.setattr(settings, "salesforce_client_id", "cid")
    monkeypatch.setattr(settings, "salesforce_client_secret", "csecret")
    monkeypatch.setattr(settings, "secrets_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "app_url", "https://blacksync.si")
    grants = []

    async def token(host, data):
        grants.append((host, data))
        if data["grant_type"] == "authorization_code":
            assert data["code_verifier"] and data["redirect_uri"] == "https://blacksync.si" + sf.CALLBACK_PATH
            return {"access_token": "at1", "refresh_token": "rt1", "instance_url": "https://acme.my.salesforce.com"}
        return {"access_token": "at2"}

    monkeypatch.setattr(sf, "_token", token)
    seen = []

    def handler(req):
        seen.append(req)
        if req.headers["authorization"] == "Bearer at1" and "fresh" in str(req.url):
            return httpx.Response(401, json=[{"message": "Session expired", "errorCode": "INVALID_SESSION_ID"}])
        return httpx.Response(200, json={"records": [{"Name": "Acme Realty"}]})

    monkeypatch.setattr(BaseHttp, "client_factory", staticmethod(
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5)))
    return grants, seen


def test_connect_with_salesforce_end_to_end(client, sf_app):
    grants, seen = sf_app
    providers = {p["key"]: p for p in client.get("/api/integrations/crm").json()["providers"]}
    assert providers["salesforce"]["oauth_native"] is True

    url = client.post("/api/integrations/crm/salesforce/oauth/start", json={"sandbox": False}).json()["url"]
    q = parse_qs(urlparse(url).query)
    assert url.startswith("https://login.salesforce.com/services/oauth2/authorize")
    assert q["client_id"] == ["cid"] and q["code_challenge_method"] == ["S256"] and "refresh_token" in q["scope"][0]

    r = client.get(sf.CALLBACK_PATH, params={"state": q["state"][0], "code": "abc"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/integrations/salesforce?connected=1"
    conn = next(c for c in client.get("/api/integrations/crm").json()["connections"] if c["provider"] == "salesforce")
    assert conn["account_label"] == "Acme Realty" and conn["status"] == "connected"
    assert "rt1" not in json.dumps(conn) and "at1" not in json.dumps(conn)
    assert seen[-1].url.host == "acme.my.salesforce.com"

    # The state is single-use: replaying the callback doesn't connect anything.
    again = client.get(sf.CALLBACK_PATH, params={"state": q["state"][0], "code": "abc"}, follow_redirects=False)
    assert again.headers["location"] == "/integrations/salesforce?error=failed"


def test_cancelled_sign_in_goes_back_with_a_message(client, sf_app):
    url = client.post("/api/integrations/crm/salesforce/oauth/start", json={"sandbox": True}).json()["url"]
    assert url.startswith("https://test.salesforce.com/")
    state = parse_qs(urlparse(url).query)["state"][0]
    r = client.get(sf.CALLBACK_PATH, params={"state": state, "error": "access_denied"}, follow_redirects=False)
    assert r.headers["location"] == "/integrations/salesforce?error=cancelled"


def test_expired_access_token_is_refreshed_once(sf_app):
    grants, seen = sf_app
    http = SalesforceHttp({"refresh_token": "rt-x", "access_token": "at1"}, {"instance_url": "https://acme.my.salesforce.com"})
    res = asyncio.run(http.request("GET", "/services/data/v60.0/query", params={"q": "fresh"}))
    assert res["records"] and grants[-1] == ("login.salesforce.com", {"grant_type": "refresh_token", "refresh_token": "rt-x"})
    assert seen[-1].headers["authorization"] == "Bearer at2"
