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
    # Bulk: addresses starting with "1" match, others don't.
    p.bulk = lambda a: ({**FOUND, "charged": 0.07} if a["address"].startswith("1") else MISS)

    def handler(request: httpx.Request):
        p.calls.append({"url": str(request.url), "auth": request.headers.get("authorization"),
                        "body": json.loads(request.content)})
        if isinstance(p.reply, int):
            return httpx.Response(p.reply, json={"error": "nope"}, headers=p.headers)
        if isinstance(p.reply, Exception):
            raise p.reply
        if request.url.path.endswith("-bulk"):
            addrs = json.loads(request.content)["addresses"]
            res = [p.bulk(a) for a in addrs]
            return httpx.Response(200, json={"success": True, "total": len(res), "matched": sum(r["found"] for r in res),
                                             "results": res})
        return httpx.Response(200, json=p.reply)

    real = httpx.AsyncClient
    monkeypatch.setattr(lf.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(settings, "skiptrace_api_key", "dsk_test_secret_key")
    lf._hits.clear()
    return p


def _account(client, make_client, name="Finder Co", credits=10):
    org, email = _new_account(client, name=name)
    if credits:
        assert client.post(f"/api/admin/orgs/{org['id']}/lead-credits", json={"amount": credits}).status_code == 200
    return org, _login(make_client, email)


def _addr(n=1, **over):
    a = {"street": f"{1250 + n} E 21st St", "city": "Erie", "state": "PA", "zip": "16503"}
    a.update(over)
    return a


def _credits(c):
    return c.get("/api/lead-finder/usage").json()["credits"]


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
    assert res["phones"][0]["display"] == "(814) 555-0101"
    assert res["emails"] == ["dana.reyes@example.com"]
    assert body["usage"]["credits"] == 9  # one owner found = one credit

    # Reopening (or searching the same address again, written differently) is free.
    again = c.post("/api/lead-finder/lookups", json=_addr(2, street="1252 East 21st Street", zip="16503-1234"))
    assert again.json()["cached"] is True and len(provider.calls) == 1
    lid = body["lookup"]["id"]
    assert c.get(f"/api/lead-finder/lookups/{lid}").json()["result"]["contact"]["first_name"] == "Dana"
    assert len(provider.calls) == 1 and _credits(c) == 9


def test_dnc_is_only_what_dataskip_explicitly_says(client, make_client, provider):
    _, c = _account(client, make_client)
    provider.reply = {**FOUND, "phones": [
        {"number": "8145550111", "type": "mobile", "dnc": "false"},
        {"number": "8145550112", "type": "mobile"},                    # not reported
        {"number": "8145550113", "type": "landline", "dnc": "true"},
        {"number": "8145550114", "type": "landline", "dnc": False}]}
    phones = c.post("/api/lead-finder/lookups", json=_addr(3)).json()["lookup"]["result"]["phones"]
    assert [p["dnc"] for p in phones] == [False, None, True, False]


def test_credits_pay_for_matches_only_and_block_at_zero(client, make_client, provider):
    _, c = _account(client, make_client, credits=2)
    provider.reply = MISS  # no match costs nothing
    for n in range(3):
        assert c.post("/api/lead-finder/lookups", json=_addr(10 + n)).json()["lookup"]["found"] is False
    assert _credits(c) == 2
    provider.reply = FOUND
    assert c.post("/api/lead-finder/lookups", json=_addr(20)).status_code == 200
    assert c.post("/api/lead-finder/lookups", json=_addr(21)).status_code == 200
    assert _credits(c) == 0
    r = c.post("/api/lead-finder/lookups", json=_addr(22))
    assert r.status_code == 402 and r.json()["code"] == "no_credits"
    assert len(provider.calls) == 5  # the blocked one never reached DataSkip
    assert c.post("/api/lead-finder/lookups", json=_addr(20)).json()["cached"] is True  # saved results stay free


def test_no_credits_account_is_blocked(client, make_client, provider):
    _, c = _account(client, make_client, credits=0)
    r = c.post("/api/lead-finder/lookups", json=_addr(5))
    assert r.status_code == 402 and provider.calls == []


def test_provider_failures_cost_nothing(client, make_client, provider):
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
    assert _credits(c) == 10
    assert len(provider.calls) == 6  # no automatic retries


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
    assert provider.calls == [] and _credits(c) == 10


def test_concurrent_holds_cannot_overspend(client, make_client):
    import uuid as _uuid

    from app.database import AsyncSessionLocal
    from app.models.account import Organization

    org, _ = _account(client, make_client, name="Race Co", credits=2)

    async def go():
        async def one():
            async with AsyncSessionLocal() as db:
                o = await db.get(Organization, _uuid.UUID(org["id"]))
                try:
                    await lf.hold_credits(db, o, 1)
                    return True
                except lf.NotEnoughCredits:
                    return False

        return await asyncio.gather(*(one() for _ in range(8)))

    assert sum(asyncio.run(go())) == 2


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


def test_save_as_lead_dedupes_and_does_not_invent_dnc(client, make_client, provider):
    _, c = _account(client, make_client, name="Saver Co")
    lid = c.post("/api/lead-finder/lookups", json=_addr(60)).json()["lookup"]["id"]
    r = c.post(f"/api/lead-finder/lookups/{lid}/save")
    assert r.status_code == 200 and r.json()["created"] is True
    lead_id = r.json()["lead_id"]
    assert c.post(f"/api/lead-finder/lookups/{lid}/save").json() == {"lead_id": lead_id, "created": False}

    lead = next(x for x in c.get("/api/contacts").json()["items"] if x["id"] == lead_id)
    # Primary number: the first mobile DataSkip didn't flag. The contact isn't auto-marked do-not-call.
    assert lead["phone"] == "+18145550103" and lead["do_not_call"] is False and lead["source"] == "dataskip"
    assert lead["campaign_id"] is None and lead["email"] == "dana.reyes@example.com"

    from app.database import AsyncSessionLocal
    from app.models.lead import Lead

    async def fetch():
        async with AsyncSessionLocal() as db:
            return await db.get(Lead, __import__("uuid").UUID(lead_id))

    saved = asyncio.run(fetch())
    assert saved.enrichment["source"] == "dataskip" and saved.enrichment["phones"][0]["provider_dnc"] is True
    assert saved.custom_fields["property_address"] == "1252 E 21st St, Erie, PA 16503"

    provider.reply = MISS
    miss = c.post("/api/lead-finder/lookups", json=_addr(62)).json()["lookup"]["id"]
    assert c.post(f"/api/lead-finder/lookups/{miss}/save").status_code == 400


CSV = """Address,City,State,Zip,Owner notes
101 Oak Ave,Erie,PA,16503,x
202 Pine St,Erie,PA,16503,
103 Elm St,Erie,PA,,
,,,,
Main St,Erie,PA,16503,
101 Oak Avenue,Erie,PA,16503,dup
"""


def test_bulk_csv_preview_run_and_credits(client, make_client, provider):
    _, c = _account(client, make_client, name="Bulk Co", credits=5)
    r = c.post("/api/lead-finder/batches", json={"filename": "list.csv", "text": CSV})
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["status"] == "draft" and b["total_rows"] == 5 and b["valid"] == 3 and b["max_credits"] == 3
    reasons = {i["row"]: i["reason"] for i in b["invalid"]}
    assert "house number" in reasons[6] and "Duplicate" in reasons[7]
    assert provider.calls == [] and _credits(c) == 5  # preview is free

    s = c.post(f"/api/lead-finder/batches/{b['id']}/start")
    assert s.status_code == 202
    done = c.get(f"/api/lead-finder/batches/{b['id']}").json()
    assert done["status"] == "done" and done["matched"] == 2 and done["no_match"] == 1 and done["credits_used"] == 2
    assert [x["row"] for x in done["rows"]] == [2, 3, 4]
    assert _credits(c) == 3  # held 3, two owners found, one credit returned
    bulk = [x for x in provider.calls if x["url"].endswith("-bulk")]
    assert len(bulk) == 1 and bulk[0]["body"]["addresses"][2] == {"address": "103 Elm St", "city": "Erie", "state": "PA"}

    csv_out = c.get(f"/api/lead-finder/batches/{b['id']}/export")
    assert csv_out.status_code == 200 and "Dana Reyes" in csv_out.text and "no_match" in csv_out.text
    saved = c.post(f"/api/lead-finder/batches/{b['id']}/save-leads").json()
    assert saved["created"] + saved["updated"] == 2

    # Re-uploading the same addresses reuses saved results for free.
    b2 = c.post("/api/lead-finder/batches", json={"filename": "again.csv", "text": CSV}).json()
    assert b2["max_credits"] == 0 and b2["cached_rows"] == 3
    c.post(f"/api/lead-finder/batches/{b2['id']}/start")
    assert c.get(f"/api/lead-finder/batches/{b2['id']}").json()["cached"] == 3 and _credits(c) == 3

    _, other = _account(client, make_client, name="Peek Co")
    assert other.get(f"/api/lead-finder/batches/{b['id']}").status_code == 404
    assert other.get(f"/api/lead-finder/batches/{b['id']}/export").status_code == 404


def test_bulk_needs_enough_credits_and_refunds_failures(client, make_client, provider):
    _, c = _account(client, make_client, name="Short Co", credits=1)
    b = c.post("/api/lead-finder/batches", json={"text": CSV}).json()
    r = c.post(f"/api/lead-finder/batches/{b['id']}/start")
    assert r.status_code == 402 and "needs up to 3" in r.json()["detail"]
    client.post(f"/api/admin/orgs/{c.get('/api/auth/me').json()['org']['id']}/lead-credits", json={"amount": 9})
    provider.reply = 402  # provider out of balance mid-run
    c.post(f"/api/lead-finder/batches/{b['id']}/start")
    res = c.get(f"/api/lead-finder/batches/{b['id']}").json()
    assert res["status"] == "failed" and res["failed"] == 3 and _credits(c) == 10


def test_bulk_csv_full_address_column():
    valid, invalid, total = lf.parse_address_csv("Full Address\n\"1252 E 21st St, Erie, PA 16503\"\nnot an address\n")
    assert total == 2 and valid[0]["street"] == "1252 E 21st St" and valid[0]["state"] == "PA" and len(invalid) == 1
    with pytest.raises(ValueError):
        lf.parse_address_csv("Name,Phone\nA,1\n")


def test_admin_credits_controls_and_usage(client, make_client, provider):
    org, c = _account(client, make_client, name="Admin Watch Co", credits=0)
    assert client.post(f"/api/admin/orgs/{org['id']}/lead-credits", json={"amount": 25, "note": "Starter pack"}).json() == {"credits": 25}
    c.post("/api/lead-finder/lookups", json=_addr(70))
    provider.reply = 402
    c.post("/api/lead-finder/lookups", json=_addr(71))

    stats = client.get(f"/api/admin/orgs/{org['id']}/lead-finder").json()
    assert stats["credits"] == 24 and stats["unlimited"] is False
    assert stats["last_30_days"]["lookups"] == 1 and stats["last_30_days"]["matches"] == 1 and stats["last_30_days"]["cost"] == 0.07
    assert [t["kind"] for t in stats["ledger"]] == ["usage", "grant"] and stats["ledger"][1]["note"] == "Starter pack"
    assert stats["recent_errors"][0]["code"] == "balance"
    assert "Erie" not in json.dumps(stats) and "Dana" not in json.dumps(stats)  # no contact data for admins
    # Calling credits are untouched.
    assert client.get(f"/api/admin/orgs/{org['id']}").json()["credits_balance"] == 0

    assert client.post(f"/api/admin/orgs/{org['id']}/lead-credits", json={"amount": -100}).json() == {"credits": 0}
    client.patch(f"/api/admin/orgs/{org['id']}", json={"lead_credits_unlimited": True})
    provider.reply = FOUND
    assert c.post("/api/lead-finder/lookups", json=_addr(72)).status_code == 200
    assert client.patch(f"/api/admin/orgs/{org['id']}", json={"lead_finder_enabled": False}).status_code == 200
    assert c.post("/api/lead-finder/lookups", json=_addr(73)).status_code == 403

    # Regular users can't grant credits or see admin usage.
    assert c.post(f"/api/admin/orgs/{org['id']}/lead-credits", json={"amount": 999}).status_code in (401, 403)
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
    assert c.post("/api/lead-finder/batches", json={"text": CSV}).status_code == 401


def test_new_account_with_lookup_credits(client):
    r = client.post("/api/admin/orgs", json={"name": "Starter Co", "owner_email": "starter@acme.dev",
                                             "password": "owner-pass-123", "lead_credits": 50})
    assert r.status_code == 201, r.text
    org_id = r.json()["org"]["id"] if "org" in r.json() else r.json()["id"]
    assert client.get(f"/api/admin/orgs/{org_id}/lead-finder").json()["credits"] == 50
    listed = next(o for o in client.get("/api/admin/orgs").json()["orgs"] if o["id"] == org_id)
    assert listed["lead_credits"] == 50


def test_parse_without_commas_and_full_state_names():
    p = lf.parse_full_address("1252 E 21st St Erie PA 16503")
    assert (p["street"], p["city"], p["state"], p["zip"], p["confident"]) == ("1252 E 21st St", "Erie", "PA", "16503", True)
    p = lf.parse_full_address("77 Ocean Dr Apt 4 Miami Beach FL 33139")
    assert (p["street"], p["city"], p["state"]) == ("77 Ocean Dr Apt 4", "Miami Beach", "FL")
    p = lf.parse_full_address("45 W Lake Blvd Salt Lake City Utah 84101")
    assert (p["street"], p["city"], p["state"], p["zip"]) == ("45 W Lake Blvd", "Salt Lake City", "UT", "84101")
    p = lf.parse_full_address("12 Elm Way\nAustin TX 78701")
    assert (p["street"], p["city"], p["state"]) == ("12 Elm Way", "Austin", "TX")
    p = lf.parse_full_address("9 Oak Ave, Erie, PA")
    assert (p["street"], p["city"], p["state"], p["zip"], p["confident"]) == ("9 Oak Ave", "Erie", "PA", "", False)
