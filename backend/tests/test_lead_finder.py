"""Lead Finder: DataSkip lookups, daily allowance, caching, errors, isolation, saving leads, admin controls."""

import asyncio
import json

import httpx
import pytest

from app.config import settings
from app.services import lead_finder as lf
from tests.test_accounts import _login, _new_account

FOUND = {
    "success": True, "found": True, "charged": 0.07,
    "contact": {"firstName": "Dana", "lastName": "Reyes", "fullName": "Dana Reyes",
                "propertyAddress": "1252 E 21st St", "propertyCity": "Erie", "propertyState": "PA", "propertyZip": "16503",
                "mailingAddress": "PO Box 12", "mailingCity": "Erie", "mailingState": "PA", "mailingZip": "16512"},
    "phones": [{"number": "8145550101", "type": "mobile", "dnc": True},
               {"number": "(814) 555-0102", "type": "landline", "dnc": False},
               {"number": "814-555-0103", "type": "mobile", "dnc": False}],
    "emails": ["Dana.Reyes@example.com"],
}
MISS = {"success": True, "found": False, "charged": 0, "contact": None, "phones": [], "emails": []}


@pytest.fixture
def provider(monkeypatch):
    """Fake DataSkip at the HTTP layer. Set `.reply` to a dict or an int status; `.calls` records requests."""
    class P:
        reply = FOUND
        headers = {}
        calls: list = []

    p = P()
    p.calls = []

    def handler(request: httpx.Request):
        p.calls.append({"url": str(request.url), "auth": request.headers.get("authorization"),
                        "body": json.loads(request.content)})
        if isinstance(p.reply, int):
            return httpx.Response(p.reply, json={"error": "nope"}, headers=p.headers)
        if isinstance(p.reply, Exception):
            raise p.reply
        return httpx.Response(200, json=p.reply)

    real = httpx.AsyncClient
    monkeypatch.setattr(lf.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(settings, "skiptrace_api_key", "dsk_test_secret_key")
    lf._hits.clear()
    return p


def _account(client, make_client, name="Finder Co"):
    org, email = _new_account(client, name=name)
    return org, _login(make_client, email)


def _addr(n=1, **over):
    a = {"street": f"{1250 + n} E 21st St", "city": "Erie", "state": "PA", "zip": "16503"}
    a.update(over)
    return a


def test_lookup_calls_dataskip_securely_and_normalizes(client, make_client, provider):
    _, c = _account(client, make_client)
    r = c.post("/api/lead-finder/lookups", json=_addr(2))
    assert r.status_code == 200, r.text
    body = r.json()
    call = provider.calls[0]
    assert call["url"] == "https://app.dataskip.io/api/v1/skip-trace"
    assert call["auth"] == "Bearer dsk_test_secret_key"
    assert call["body"] == {"address": "1252 E 21st St", "city": "Erie", "state": "PA", "zip": "16503"}
    assert "dsk_test_secret_key" not in r.text  # the key never reaches the browser

    res = body["lookup"]["result"]
    assert body["cached"] is False and body["lookup"]["found"] is True
    assert res["contact"]["full_name"] == "Dana Reyes" and res["contact"]["mailing"]["address"] == "PO Box 12"
    assert [p["number"] for p in res["phones"]] == ["+18145550101", "+18145550102", "+18145550103"]
    assert res["phones"][0]["dnc"] is True and res["phones"][0]["display"] == "(814) 555-0101"
    assert res["emails"] == ["dana.reyes@example.com"]
    assert body["usage"]["used"] == 1 and body["usage"]["remaining"] == 4

    # Reopening (or searching the same address again, written differently) is free.
    again = c.post("/api/lead-finder/lookups", json=_addr(2, street="1252 East 21st Street", zip="16503-1234"))
    assert again.json()["cached"] is True and len(provider.calls) == 1
    lid = body["lookup"]["id"]
    assert c.get(f"/api/lead-finder/lookups/{lid}").json()["result"]["contact"]["first_name"] == "Dana"
    assert len(provider.calls) == 1 and c.get("/api/lead-finder/usage").json()["used"] == 1


def test_five_per_day_then_blocked(client, make_client, provider, monkeypatch):
    _, c = _account(client, make_client)
    provider.reply = MISS  # no-match still counts against our allowance
    for n in range(5):
        r = c.post("/api/lead-finder/lookups", json=_addr(10 + n))
        assert r.status_code == 200 and r.json()["lookup"]["found"] is False
    r = c.post("/api/lead-finder/lookups", json=_addr(20))
    assert r.status_code == 429 and r.json()["code"] == "quota"
    assert r.json()["usage"]["remaining"] == 0 and r.json()["usage"]["resets_at"].endswith("+00:00")
    assert len(provider.calls) == 5  # the sixth never reached DataSkip
    # A cached address is still viewable at the limit.
    assert c.post("/api/lead-finder/lookups", json=_addr(10)).status_code == 200


def test_provider_failures_do_not_use_allowance(client, make_client, provider):
    _, c = _account(client, make_client)
    cases = [(400, 400, "invalid_request"), (401, 503, "auth"), (402, 503, "balance"), (500, 502, "provider_error")]
    for upstream, ours, code in cases:
        provider.reply = upstream
        r = c.post("/api/lead-finder/lookups", json=_addr(30 + upstream))
        assert r.status_code == ours and r.json()["code"] == code, r.text
        assert "dataskip" not in r.json()["detail"].lower() and "dsk_" not in r.text
    provider.reply, provider.headers = 429, {"Retry-After": "42"}
    r = c.post("/api/lead-finder/lookups", json=_addr(31))
    assert r.status_code == 503 and r.headers["Retry-After"] == "42" and "42 seconds" in r.json()["detail"]
    provider.reply = httpx.ConnectError("down")
    assert c.post("/api/lead-finder/lookups", json=_addr(32)).json()["code"] == "network"
    assert c.get("/api/lead-finder/usage").json()["used"] == 0
    # Each failure was one request — no automatic retries.
    assert len(provider.calls) == 6


def test_rejected_requests_never_reach_provider(client, make_client, provider, monkeypatch):
    _, c = _account(client, make_client)
    for bad, word in [({"street": "Main St", "city": "Erie", "state": "PA"}, "house number"),
                      ({"street": "12 Main St, Erie PA", "city": "Erie", "state": "PA"}, "only the street"),
                      ({"street": "12 Main St", "city": "", "state": "PA"}, "city"),
                      ({"street": "12 Main St", "city": "Erie", "state": "ZZ"}, "state"),
                      ({"street": "12 Main St", "city": "Erie", "state": "PA", "zip": "123"}, "ZIP")]:
        r = c.post("/api/lead-finder/lookups", json=bad)
        assert r.status_code == 400 and word in r.json()["detail"], r.text
    monkeypatch.setattr(settings, "skiptrace_api_key", "")
    r = c.post("/api/lead-finder/lookups", json=_addr(40))
    assert r.status_code == 503 and c.get("/api/lead-finder/usage").json()["configured"] is False
    assert provider.calls == [] and c.get("/api/lead-finder/usage").json()["used"] == 0


def test_concurrent_reservations_cannot_exceed_allowance(client, make_client):
    from app.database import AsyncSessionLocal
    from app.models.account import Organization

    org, _ = _account(client, make_client, name="Race Co")

    async def go():
        async with AsyncSessionLocal() as db:
            o = await db.get(Organization, __import__("uuid").UUID(org["id"]))
            o.lead_finder_daily_limit = 2
            await db.commit()

        async def one(i):
            async with AsyncSessionLocal() as db:
                o = await db.get(Organization, __import__("uuid").UUID(org["id"]))
                a = lf.validate_address(f"{100 + i} Oak Ave", "Erie", "PA", "16503")
                try:
                    await lf.reserve(db, o, None, a, lf.address_key(a["street"], a["city"], a["state"], a["zip"]))
                    return True
                except lf.LookupError_:
                    return False

        return await asyncio.gather(*(one(i) for i in range(8)))

    results = asyncio.run(go())
    assert sum(results) == 2


def test_history_is_org_scoped_and_deletable(client, make_client, provider):
    _, c = _account(client, make_client, name="Owner Co")
    lid = c.post("/api/lead-finder/lookups", json=_addr(50)).json()["lookup"]["id"]
    items = c.get("/api/lead-finder/lookups").json()["items"]
    assert items[0]["id"] == lid and items[0]["owner_name"] == "Dana Reyes" and "result" not in items[0]

    _, other = _account(client, make_client, name="Other Co")
    assert other.get(f"/api/lead-finder/lookups/{lid}").status_code == 404
    assert other.post(f"/api/lead-finder/lookups/{lid}/save").status_code == 404
    assert other.delete(f"/api/lead-finder/lookups/{lid}").status_code == 404
    assert other.get("/api/lead-finder/lookups").json()["items"] == []
    # The same address searched by another org is a new lookup for them, not a shared cache.
    assert other.post("/api/lead-finder/lookups", json=_addr(50)).json()["cached"] is False

    assert c.delete(f"/api/lead-finder/lookups/{lid}").status_code == 204
    gone = c.get(f"/api/lead-finder/lookups/{lid}").json()
    assert gone["deleted"] is True and gone["result"] is None and gone["owner_name"] is None
    assert c.get("/api/lead-finder/usage").json()["used"] == 1  # deleting doesn't give allowance back


def test_save_as_lead_dedupes_and_keeps_dnc(client, make_client, provider):
    _, c = _account(client, make_client, name="Saver Co")
    lid = c.post("/api/lead-finder/lookups", json=_addr(60)).json()["lookup"]["id"]
    r = c.post(f"/api/lead-finder/lookups/{lid}/save")
    assert r.status_code == 200 and r.json()["created"] is True
    lead_id = r.json()["lead_id"]
    again = c.post(f"/api/lead-finder/lookups/{lid}/save").json()
    assert again == {"lead_id": lead_id, "created": False}

    contacts = c.get("/api/contacts").json()["items"]
    mine = [x for x in contacts if x["id"] == lead_id]
    assert len(mine) == 1
    lead = mine[0]
    # Primary number skips the DNC-listed mobile; campaigns aren't touched.
    assert lead["phone"] == "+18145550103" and lead["do_not_call"] is False and lead["source"] == "dataskip"
    assert lead["campaign_id"] is None and lead["email"] == "dana.reyes@example.com"

    from app.database import AsyncSessionLocal
    from app.models.lead import Lead

    async def fetch():
        async with AsyncSessionLocal() as db:
            return await db.get(Lead, __import__("uuid").UUID(lead_id))

    saved = asyncio.run(fetch())
    assert saved.enrichment["source"] == "dataskip" and saved.enrichment["phones"][0]["dnc"] is True
    assert saved.custom_fields["property_address"] == "1252 E 21st St, Erie, PA 16503"
    assert saved.custom_fields["mailing_address"].startswith("PO Box 12")

    # Every number DNC-listed → the lead is never dialed.
    provider.reply = {**FOUND, "phones": [{"number": "8145550199", "type": "mobile", "dnc": True}]}
    lid2 = c.post("/api/lead-finder/lookups", json=_addr(61)).json()["lookup"]["id"]
    lead2 = c.post(f"/api/lead-finder/lookups/{lid2}/save").json()
    assert lead2["created"] is True
    row = next(x for x in c.get("/api/contacts").json()["items"] if x["id"] == lead2["lead_id"])
    assert row["do_not_call"] is True and row["phone"] == ""

    provider.reply = MISS
    miss = c.post("/api/lead-finder/lookups", json=_addr(62)).json()["lookup"]["id"]
    assert c.post(f"/api/lead-finder/lookups/{miss}/save").status_code == 400


def test_admin_controls_and_usage(client, make_client, provider):
    org, c = _account(client, make_client, name="Admin Watch Co")
    c.post("/api/lead-finder/lookups", json=_addr(70))
    provider.reply = 402
    c.post("/api/lead-finder/lookups", json=_addr(71))

    stats = client.get(f"/api/admin/orgs/{org['id']}/lead-finder").json()
    assert stats["used_today"] == 1 and stats["daily_limit"] == 5 and stats["limit_is_default"] is True
    assert stats["last_30_days"] == {"lookups": 1, "matches": 1, "cost": 0.07, "failed": 1}
    assert stats["recent_errors"][0]["code"] == "balance"
    assert "Erie" not in json.dumps(stats) and "Dana" not in json.dumps(stats)  # no contact data for admins

    assert client.patch(f"/api/admin/orgs/{org['id']}", json={"lead_finder_daily_limit": 1}).status_code == 200
    assert c.get("/api/lead-finder/usage").json()["remaining"] == 0
    assert client.patch(f"/api/admin/orgs/{org['id']}", json={"lead_finder_enabled": False}).status_code == 200
    provider.reply = FOUND
    assert c.post("/api/lead-finder/lookups", json=_addr(72)).status_code == 403
    assert c.get("/api/lead-finder/usage").json()["enabled"] is False
    client.patch(f"/api/admin/orgs/{org['id']}", json={"lead_finder_enabled": True, "lead_finder_daily_limit": -1})
    assert c.get("/api/lead-finder/usage").json()["limit"] == 5

    # Regular users can't change limits or see admin usage.
    assert c.patch(f"/api/admin/orgs/{org['id']}", json={"lead_finder_daily_limit": 999}).status_code in (401, 403)
    assert c.get(f"/api/admin/orgs/{org['id']}/lead-finder").status_code in (401, 403)


def test_parse_full_address():
    p = lf.parse_full_address("1252 E 21st St, Erie, PA 16503")
    assert p == {"street": "1252 E 21st St", "city": "Erie", "state": "PA", "zip": "16503", "confident": True}
    p = lf.parse_full_address("77 Ocean Dr, Miami Beach, Florida 33139-1234, USA")
    assert p["state"] == "FL" and p["zip"] == "33139-1234" and p["city"] == "Miami Beach" and p["confident"]
    p = lf.parse_full_address("12 Main Street Springfield")
    assert p["confident"] is False
    assert lf.address_key("12 Main Street", "Erie", "PA", "16503") == lf.address_key("12 main st.", "ERIE", "pa", "16503-0001")


def test_lead_finder_requires_login(make_client):
    c = make_client()
    assert c.get("/api/lead-finder/usage").status_code == 401
    assert c.post("/api/lead-finder/lookups", json=_addr(1)).status_code == 401
