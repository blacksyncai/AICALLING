"""BlackSync Admin: the separate platform-admin MCP server at /api/admin-mcp."""

import uuid
from urllib.parse import parse_qs, urlparse

from tests.test_connector import BASE, REDIRECT, _connect, _pkce

ADMIN_RES = f"{BASE}/api/admin-mcp"
SCRIPT = ("You are Maya from Acme Roofing. Call homeowners who asked about a roof quote, confirm their address, "
          "ask about the roof's age and any leaks, and book a free inspection. Keep replies short and friendly. "
          "If they are busy, offer a callback time. Never pressure anyone.") * 2


def _request(anon, resource=ADMIN_RES):
    reg = anon.post("/api/oauth/register", json={"client_name": "Claude", "redirect_uris": [REDIRECT],
                                                  "token_endpoint_auth_method": "none"})
    client_id = reg.json()["client_id"]
    verifier, challenge = _pkce()
    r = anon.get("/api/oauth/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "state": "s",
        "code_challenge": challenge, "code_challenge_method": "S256", "scope": "blacksync", "resource": resource},
        follow_redirects=False)
    assert r.status_code == 302, r.text
    return client_id, verifier, parse_qs(urlparse(r.headers["location"]).query)["req"][0]


def _admin_connect(user_client, anon):
    client_id, verifier, req = _request(anon)
    info = user_client.get("/api/oauth/request", params={"req": req}).json()
    assert info["admin"] and info["accounts"] == []
    r = user_client.post("/api/oauth/approve", json={"req": req, "approve": True})
    assert r.status_code == 200, r.text
    code = parse_qs(urlparse(r.json()["redirect"]).query)["code"][0]
    tok = anon.post("/api/oauth/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
                                              "client_id": client_id, "code_verifier": verifier, "resource": ADMIN_RES})
    assert tok.status_code == 200, tok.text
    return tok.json()["access_token"]


def _rpc(c, token, method, params=None, path="/api/admin-mcp"):
    return c.post(path, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                  headers={"Authorization": f"Bearer {token}"})


def _tool(c, token, name, args=None):
    r = _rpc(c, token, "tools/call", {"name": name, "arguments": args or {}})
    assert r.status_code == 200, r.text
    out = r.json()["result"]
    return out["structuredContent"], out.get("isError", False)


def _customer(client, name):
    r = client.post("/api/admin/orgs", json={"name": name, "owner_email": f"{uuid.uuid4().hex[:8]}@acme.test"})
    assert r.status_code == 201, r.text
    body = r.json()
    return (body.get("org") or body)["id"]


def test_the_customer_connector_is_unchanged_and_tokens_dont_cross(client, make_client):
    anon = make_client()
    customer = _connect(client, anon)["access_token"]
    names = {t["name"] for t in _rpc(anon, customer, "tools/list", path="/api/mcp").json()["result"]["tools"]}
    assert not any(n.startswith("admin_") for n in names)
    assert _rpc(anon, customer, "tools/list").status_code == 401  # a customer token on the admin server

    admin = _admin_connect(client, make_client())
    assert _rpc(anon, admin, "tools/list", path="/api/mcp").status_code == 401  # an admin token on /api/mcp
    # Admin connections are not listed with the customer's connected assistants.
    listed = {c["id"] for c in client.get("/api/oauth/connections").json()["connections"]}
    assert all(c["id"] not in listed for c in client.get("/api/admin/ai-access").json()["connections"])

    pr = make_client().get("/.well-known/oauth-protected-resource/api/admin-mcp").json()
    assert pr["resource"] == ADMIN_RES and pr["resource_name"] == "BlackSync Admin"
    assert make_client().post("/api/admin-mcp", json={}).status_code == 401


def test_approval_needs_a_super_admin_with_the_portal_unlocked(client, make_client):
    locked = make_client()
    assert locked.post("/api/auth/login", json={"email": "admin@test.dev", "password": "admin-pass-123"}).status_code == 200
    _, _, req = _request(make_client())
    assert locked.get("/api/oauth/request", params={"req": req}).json()["admin_unlocked"] is False
    assert locked.post("/api/oauth/approve", json={"req": req, "approve": True}).status_code == 423
    assert locked.post("/api/oauth/approve", json={"req": req, "approve": True, "admin_password": "nope"}).status_code == 403
    ok = locked.post("/api/oauth/approve", json={"req": req, "approve": True, "admin_password": "portal-pass-456"})
    assert ok.status_code == 200 and "code=" in ok.json()["redirect"]


def test_admin_works_in_any_account_and_everything_is_logged(client, make_client):
    org = _customer(client, "Acme Roofing")
    anon = make_client()
    token = _admin_connect(client, anon)

    init = _rpc(anon, token, "initialize").json()["result"]
    assert init["serverInfo"]["title"] == "BlackSync Admin"
    tools = {t["name"]: t for t in _rpc(anon, token, "tools/list").json()["result"]["tools"]}
    assert {"admin_list_accounts", "admin_use_account", "admin_add_credits", "create_agent", "add_contacts"} <= set(tools)
    assert "account_id" in tools["create_agent"]["inputSchema"]["properties"]

    found, err = _tool(anon, token, "admin_list_accounts", {"query": "Acme Roofing"})
    assert not err and any(a["id"] == org for a in found["accounts"])
    out, err = _tool(anon, token, "list_agents")
    assert err and "Pick the customer account" in out["error"]

    used, err = _tool(anon, token, "admin_use_account", {"account_id": org})
    assert not err and used["account"]["name"] == "Acme Roofing"
    agent, err = _tool(anon, token, "create_agent", {"name": "Roof Quotes", "system_prompt": SCRIPT,
                                                     "first_message": "Hey, is this {{name}}?"})
    assert not err, agent
    assert agent["acting_account"]["id"] == org
    added, err = _tool(anon, token, "add_contacts", {"contacts": [{"name": "Pat", "phone": "+14155550111"}]})
    assert not err and added["added"] == 1
    detail = client.get(f"/api/admin/orgs/{org}").json()
    assert detail["agents"] >= 1 and detail["contacts"] == 1

    other = _customer(client, "Other Co")
    out, err = _tool(anon, token, "list_agents", {"account_id": other})
    assert not err and out["acting_account"]["name"] == "Other Co"

    preview, err = _tool(anon, token, "admin_add_credits", {"account_id": org, "amount": 50})
    assert not err and preview["needs_confirmation"]
    done, err = _tool(anon, token, "admin_add_credits", {"account_id": org, "amount": 50, "confirmed": True})
    assert not err and done["balance"] == preview["balance_after"]

    page = client.get("/api/admin/ai-access").json()
    assert page["server_url"] == ADMIN_RES
    assert any(c["account"] == "Acme Roofing" for c in page["connections"])
    logged = {a["tool"] for a in page["actions"]}
    assert {"create_agent", "add_contacts", "admin_use_account", "admin_add_credits"} <= logged
    assert next(a for a in page["actions"] if a["tool"] == "create_agent")["account"] == "Acme Roofing"

    conn = next(c["id"] for c in page["connections"] if c["account"] == "Acme Roofing")
    assert client.delete(f"/api/admin/ai-access/{conn}").status_code == 204
    assert _rpc(anon, token, "tools/list").status_code == 401
