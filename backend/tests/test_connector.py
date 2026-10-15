"""The BlackSync connector for ChatGPT / Claude: OAuth sign-in, the MCP endpoint and its tools."""

import base64
import hashlib
import secrets
import uuid
from urllib.parse import parse_qs, urlparse

from tests.test_onboarding import _orphan_login

REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"
BASE = "https://blacksync.si"


def _pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _connect(user_client, anon, org_id=None, approve=True):
    """Run the whole flow the way ChatGPT does: register, authorize, approve, exchange the code."""
    reg = anon.post("/api/oauth/register", json={"client_name": "ChatGPT", "redirect_uris": [REDIRECT],
                                                  "token_endpoint_auth_method": "none"})
    assert reg.status_code == 201, reg.text
    client_id = reg.json()["client_id"]
    verifier, challenge = _pkce()
    r = anon.get("/api/oauth/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "state": "xyz",
        "code_challenge": challenge, "code_challenge_method": "S256", "scope": "blacksync",
        "resource": f"{BASE}/api/mcp"}, follow_redirects=False)
    assert r.status_code == 302, r.text
    loc = urlparse(r.headers["location"])
    assert loc.path == "/connect"
    req = parse_qs(loc.query)["req"][0]

    info = user_client.get("/api/oauth/request", params={"req": req}).json()
    assert info["client_name"] == "ChatGPT" and info["redirect_host"] == "chatgpt.com" and info["verified"]
    body = {"req": req, "approve": approve}
    if org_id or info["default_account"]:
        body["org_id"] = org_id or info["default_account"]
    redirect = user_client.post("/api/oauth/approve", json=body).json()["redirect"]
    q = parse_qs(urlparse(redirect).query)
    assert q["iss"] == [BASE] and q["state"] == ["xyz"]
    if not approve:
        assert q["error"] == ["access_denied"]
        return None
    tok = anon.post("/api/oauth/token", data={"grant_type": "authorization_code", "code": q["code"][0],
                                              "redirect_uri": REDIRECT, "client_id": client_id,
                                              "code_verifier": verifier, "resource": f"{BASE}/api/mcp"})
    assert tok.status_code == 200, tok.text
    return {**tok.json(), "client_id": client_id, "code": q["code"][0], "verifier": verifier}


def _rpc(c, token, method, params=None, id_=1):
    r = c.post("/api/mcp", json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}},
               headers={"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"})
    assert r.status_code == 200, r.text
    return r.json()


def _tool(c, token, name, args=None):
    out = _rpc(c, token, "tools/call", {"name": name, "arguments": args or {}})["result"]
    return out["structuredContent"], out.get("isError", False)


def test_discovery_documents(make_client):
    c = make_client()
    pr = c.get("/.well-known/oauth-protected-resource/api/mcp").json()
    assert pr["resource"] == f"{BASE}/api/mcp" and pr["authorization_servers"] == [BASE]
    md = c.get("/.well-known/oauth-authorization-server").json()
    assert md["issuer"] == BASE and "S256" in md["code_challenge_methods_supported"]
    assert md["registration_endpoint"].endswith("/api/oauth/register")
    assert md["client_id_metadata_document_supported"] and md["authorization_response_iss_parameter_supported"]


def test_mcp_requires_a_token(make_client):
    c = make_client()
    r = c.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r.status_code == 401
    assert 'resource_metadata="https://blacksync.si/.well-known/oauth-protected-resource/api/mcp"' in \
        r.headers["www-authenticate"]
    r = c.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
               headers={"Authorization": "Bearer bsa_nope"})
    assert r.status_code == 401 and 'error="invalid_token"' in r.headers["www-authenticate"]


def test_connect_and_use_tools(client, make_client):
    anon = make_client()
    t = _connect(client, anon)
    token = t["access_token"]

    init = _rpc(anon, token, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                            "clientInfo": {"name": "chatgpt", "version": "1"}})["result"]
    assert init["protocolVersion"] == "2025-06-18" and init["capabilities"]["tools"]
    assert anon.post("/api/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                     headers={"Authorization": f"Bearer {token}"}).status_code == 202
    tools = {x["name"]: x for x in _rpc(anon, token, "tools/list")["result"]["tools"]}
    assert {"get_started", "build_agent", "call_with_agent", "list_calls", "search", "fetch"} <= set(tools)
    assert tools["call_with_agent"]["annotations"]["destructiveHint"] is True
    assert tools["list_calls"]["annotations"]["readOnlyHint"] is True
    assert tools["get_started"]["securitySchemes"][0]["type"] == "oauth2"

    start, err = _tool(anon, token, "get_started")
    assert not err and start["has_account"] and start["checklist"] and start["account"]["name"]

    agent = client.post("/api/agents/", json={"template": "sales_sdr"}).json()
    agents, _ = _tool(anon, token, "list_agents")
    assert any(a["id"] == agent["id"] for a in agents["agents"])
    got, _ = _tool(anon, token, "get_agent", {"agent_id": agent["id"]})
    assert got["system_prompt"] and got["url"].endswith(f"/agents/{agent['id']}")
    upd, err = _tool(anon, token, "update_agent", {"agent_id": agent["id"], "first_message": "Hi, it's Sam."})
    assert not err and upd["updated"] == ["first_message"]
    assert client.get(f"/api/agents/{agent['id']}").json()["first_message"] == "Hi, it's Sam."

    phone = f"+1415555{uuid.uuid4().int % 10000:04d}"
    added, _ = _tool(anon, token, "add_contacts", {"contacts": [{"name": "Jamie Rivera", "phone": phone}]})
    assert added["added"] == 1
    listed_contacts, _ = _tool(anon, token, "list_contacts", {"query": "Jamie Rivera"})
    assert listed_contacts["contacts"][0]["phone"] == phone
    found, _ = _tool(anon, token, "search", {"query": "Jamie Rivera"})
    hit = next(r for r in found["results"] if r["id"].startswith("contact:"))
    opened, err = _tool(anon, token, "fetch", {"id": hit["id"]})
    assert not err and phone in opened["text"]

    camp, err = _tool(anon, token, "create_campaign", {"name": "Spring outreach", "agent_id": agent["id"]})
    assert not err and camp["name"] == "Spring outreach"
    listed, _ = _tool(anon, token, "list_campaigns")
    assert any(x["id"] == camp["id"] for x in listed["campaigns"])

    kb, err = _tool(anon, token, "add_knowledge", {"section": "hours", "items": ["Open Mon–Fri 8am–6pm."]})
    assert not err and any("Mon–Fri" in i["text"] for s in kb["knowledge"] if s["key"] == "hours" for i in s["items"])

    calls, err = _tool(anon, token, "list_calls", {"limit": 5})
    assert not err and "calls" in calls
    _, err = _tool(anon, token, "get_analytics", {"days": 7})
    assert not err
    # Problems come back as tool errors the assistant can read, not protocol failures.
    bad, err = _tool(anon, token, "get_agent", {"agent_id": str(uuid.uuid4())})
    assert err and "not found" in bad["error"].lower()
    assert "error" in _rpc(anon, token, "tools/call", {"name": "nope"})


def test_build_agent_starts_generation(client, make_client, monkeypatch):
    from app.connector import tools

    started = []
    monkeypatch.setattr(tools, "_run_later", lambda coro: (started.append(1), coro.close()))
    anon = make_client()
    token = _connect(client, anon)["access_token"]
    out, err = _tool(anon, token, "build_agent", {
        "mission": "Call homeowners who asked about solar and book a free roof assessment.",
        "direction": "outbound", "agent_name": "Maya", "objections": "Too expensive"})
    assert not err, out
    assert out["status"] == "running" and started == [1]
    status, err = _tool(anon, token, "get_agent_build_status", {"build_id": out["build_id"]})
    assert not err and status["status"] == "running"
    draft = client.get(f"/api/agent-builder/drafts/{out['build_id']}").json()
    goal = draft["data"]["goal"]
    assert goal["mission"].startswith("Call homeowners") and goal["advanced"]["objections"] == "Too expensive"
    assert draft["data"]["behavior"]["agent_name"] == "Maya"


def test_onboarding_from_the_assistant(client, make_client):
    user = _orphan_login(client, make_client)
    anon = make_client()
    token = _connect(user, anon)["access_token"]
    start, _ = _tool(anon, token, "get_started")
    assert start["has_account"] is False and "create_account" in start["next_step"]
    out, err = _tool(anon, token, "list_agents")
    assert err and "create_account" in out["error"]
    inds, _ = _tool(anon, token, "list_industries", {"industry": "home_services"})
    assert inds["industries"][0]["specialties"]
    made, err = _tool(anon, token, "create_account", {"company": "Peak Roofing", "industry": "home_services"})
    assert not err and made["created"]
    start, _ = _tool(anon, token, "get_started")
    assert start["has_account"] and start["account"]["name"] == "Peak Roofing"
    _, err = _tool(anon, token, "create_account", {"company": "Again", "industry": "other"})
    assert err


def test_tokens_refresh_rotate_and_revoke(client, make_client):
    anon = make_client()
    t = _connect(client, anon)
    # A code works once; replaying it cuts off what it was exchanged for.
    again = anon.post("/api/oauth/token", data={"grant_type": "authorization_code", "code": t["code"],
                                                "redirect_uri": REDIRECT, "client_id": t["client_id"],
                                                "code_verifier": t["verifier"]})
    assert again.status_code == 400 and again.json()["error"] == "invalid_grant"
    assert anon.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                     headers={"Authorization": f"Bearer {t['access_token']}"}).status_code == 401

    t = _connect(client, anon)
    r = anon.post("/api/oauth/token", data={"grant_type": "refresh_token", "refresh_token": t["refresh_token"],
                                            "client_id": t["client_id"]})
    assert r.status_code == 200
    new = r.json()
    assert new["refresh_token"] != t["refresh_token"]
    # The old access token stops working once rotated; the new one works.
    assert anon.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                     headers={"Authorization": f"Bearer {t['access_token']}"}).status_code == 401
    assert _rpc(anon, new["access_token"], "ping")["result"] == {}
    # Wrong client can't use the refresh token.
    other = anon.post("/api/oauth/register", json={"redirect_uris": [REDIRECT]}).json()["client_id"]
    assert anon.post("/api/oauth/token", data={"grant_type": "refresh_token", "refresh_token": new["refresh_token"],
                                               "client_id": other}).status_code == 400

    conns = client.get("/api/oauth/connections").json()["connections"]
    assert conns and conns[0]["app"] == "ChatGPT"
    for cn in conns:
        assert client.delete(f"/api/oauth/connections/{cn['id']}").status_code == 204
    assert anon.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                     headers={"Authorization": f"Bearer {new['access_token']}"}).status_code == 401


def test_bad_requests_are_refused(client, make_client):
    anon = make_client()
    assert anon.post("/api/oauth/register", json={"redirect_uris": ["http://evil.example/cb"]}).status_code == 400
    cid = anon.post("/api/oauth/register", json={"redirect_uris": [REDIRECT]}).json()["client_id"]
    _, challenge = _pkce()
    base = {"response_type": "code", "client_id": cid, "code_challenge": challenge, "code_challenge_method": "S256"}
    # Unregistered redirect: never redirected anywhere.
    assert anon.get("/api/oauth/authorize", params={**base, "redirect_uri": "https://evil.example/cb"},
                    follow_redirects=False).status_code == 400
    # No PKCE: error goes back to the app, with iss.
    r = anon.get("/api/oauth/authorize", params={**base, "redirect_uri": REDIRECT, "code_challenge_method": "plain"},
                 follow_redirects=False)
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["error"] == ["invalid_request"] and q["iss"] == [BASE]
    # A tampered approval request is rejected.
    assert client.post("/api/oauth/approve", json={"req": "abc.def"}).status_code == 400
    # Declining sends access_denied back.
    _connect(client, anon, approve=False)
    # Wrong PKCE verifier.
    t_reg = anon.post("/api/oauth/register", json={"redirect_uris": [REDIRECT]}).json()["client_id"]
    verifier, challenge = _pkce()
    loc = anon.get("/api/oauth/authorize", params={**base, "client_id": t_reg, "code_challenge": challenge,
                                                   "redirect_uri": REDIRECT}, follow_redirects=False).headers["location"]
    req = parse_qs(urlparse(loc).query)["req"][0]
    code = parse_qs(urlparse(client.post("/api/oauth/approve", json={"req": req}).json()["redirect"]).query)["code"][0]
    r = anon.post("/api/oauth/token", data={"grant_type": "authorization_code", "code": code, "client_id": t_reg,
                                            "redirect_uri": REDIRECT, "code_verifier": secrets.token_urlsafe(48)})
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


def test_only_known_hosts_are_metadata_clients():
    from app.routers.oauth import is_metadata_client_id

    assert is_metadata_client_id("https://chatgpt.com/oauth/client.json")
    assert is_metadata_client_id("https://claude.ai/oauth/mcp-oauth-client-metadata")
    assert not is_metadata_client_id("https://evil.example/client.json")
    assert not is_metadata_client_id("http://chatgpt.com/oauth/client.json")
    assert not is_metadata_client_id("https://chatgpt.com.evil.example/client.json")


def test_every_read_tool_answers(client, make_client):
    from app.connector.tools import TOOLS

    anon = make_client()
    token = _connect(client, anon)["access_token"]
    agent = client.post("/api/agents/", json={"template": "sales_sdr"}).json()
    camp, _ = _tool(anon, token, "create_campaign", {"name": "Smoke", "agent_id": agent["id"]})
    args = {"get_agent": {"agent_id": agent["id"]}, "get_campaign": {"campaign_id": camp["id"]},
            "search": {"query": "Smoke"}, "fetch": {"id": f"campaign:{camp['id']}"},
            "get_call": {"call_id": str(uuid.uuid4())}, "get_agent_build_status": {"build_id": str(uuid.uuid4())}}
    for name, t in TOOLS.items():
        if not t.read_only:
            continue
        out, err = _tool(anon, token, name, args.get(name, {}))
        assert "Something went wrong" not in str(out), (name, out)
    out, err = _tool(anon, token, "pause_campaign", {"campaign_id": camp["id"]})
    assert "Something went wrong" not in str(out), out
    out, err = _tool(anon, token, "launch_agent", {"agent_id": agent["id"]})
    assert "Something went wrong" not in str(out), out


def test_chatgpt_client_metadata_document(client, make_client, monkeypatch):
    """ChatGPT identifies itself with https://chatgpt.com/oauth/client.json (its real document, below)."""
    from app.routers import oauth

    cid = "https://chatgpt.com/oauth/client.json"
    doc = {"client_id": cid, "client_uri": "https://chatgpt.com/", "redirect_uris": [REDIRECT],
           "token_endpoint_auth_method": "private_key_jwt", "token_endpoint_auth_methods_supported": ["none", "private_key_jwt"],
           "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"], "client_name": "ChatGPT",
           "token_endpoint_auth_signing_alg": "RS256", "jwks_uri": "https://chatgpt.com/oauth/jwks.json"}

    async def fake_fetch(client_id):
        return doc if client_id == cid else None

    monkeypatch.setattr(oauth, "_fetch_metadata_document", fake_fetch)
    anon = make_client()
    verifier, challenge = _pkce()
    r = anon.get("/api/oauth/authorize", params={
        "response_type": "code", "client_id": cid, "redirect_uri": REDIRECT, "state": "s", "scope": "blacksync",
        "code_challenge": challenge, "code_challenge_method": "S256", "resource": f"{BASE}/api/mcp"},
        follow_redirects=False)
    assert r.status_code == 302 and urlparse(r.headers["location"]).path == "/connect", r.text
    req = parse_qs(urlparse(r.headers["location"]).query)["req"][0]
    assert client.get("/api/oauth/request", params={"req": req}).json()["client_name"] == "ChatGPT"
    code = parse_qs(urlparse(client.post("/api/oauth/approve", json={"req": req}).json()["redirect"]).query)["code"][0]
    tok = anon.post("/api/oauth/token", data={"grant_type": "authorization_code", "code": code, "client_id": cid,
                                              "redirect_uri": REDIRECT, "code_verifier": verifier})
    assert tok.status_code == 200, tok.text
    assert _rpc(anon, tok.json()["access_token"], "ping")["result"] == {}
