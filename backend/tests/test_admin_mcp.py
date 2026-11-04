"""Admin mode for the MCP connector: off by default, switched on per connection from the locked admin portal."""

import uuid

from tests.test_connector import _connect, _rpc, _tool

SCRIPT = ("You are Maya from Acme Roofing. Call homeowners who asked about a roof quote, confirm their address, "
          "ask about the roof's age and any leaks, and book a free inspection. Keep replies short and friendly. "
          "If they are busy, offer a callback time. Never pressure anyone.") * 2


def _customer(client, name="Acme Roofing"):
    r = client.post("/api/admin/orgs", json={"name": name, "owner_email": f"{uuid.uuid4().hex[:8]}@acme.test",
                                              "credits": 10})
    assert r.status_code == 201, r.text
    return r.json()["org"]["id"] if "org" in r.json() else r.json()["id"]


def _connection_id(client):
    rows = client.get("/api/admin/ai-access").json()["connections"]
    return rows[0]["id"]


def test_admin_mode_is_off_until_switched_on_in_the_portal(client, make_client):
    anon = make_client()
    token = _connect(client, anon)["access_token"]
    names = {t["name"] for t in _rpc(anon, token, "tools/list")["result"]["tools"]}
    assert "admin_list_accounts" not in names
    out, err = _tool(anon, token, "admin_list_accounts")
    assert err and "Admin mode is off" in out["error"]
    out, err = _tool(anon, token, "list_agents", {"account_id": str(uuid.uuid4())})
    assert err and "Admin mode is off" in out["error"]


def test_admin_works_inside_a_customer_account_and_everything_is_logged(client, make_client):
    org = _customer(client)
    anon = make_client()
    token = _connect(client, anon)["access_token"]
    conn = _connection_id(client)
    assert client.post(f"/api/admin/ai-access/{conn}", json={"hours": 2}).status_code == 200

    tools = {t["name"]: t for t in _rpc(anon, token, "tools/list")["result"]["tools"]}
    assert {"admin_list_accounts", "admin_use_account", "admin_add_credits"} <= set(tools)
    assert "account_id" in tools["create_agent"]["inputSchema"]["properties"]

    found, err = _tool(anon, token, "admin_list_accounts", {"query": "Acme Roofing"})
    assert not err and any(a["id"] == org for a in found["accounts"])

    out, err = _tool(anon, token, "list_agents")
    assert err and "pick the customer account" in out["error"]

    used, err = _tool(anon, token, "admin_use_account", {"account_id": org})
    assert not err and used["account"]["name"] == "Acme Roofing"

    agent, err = _tool(anon, token, "create_agent", {"name": "Roof Quotes", "system_prompt": SCRIPT,
                                                     "first_message": "Hey, is this {{name}}?"})
    assert not err, agent
    assert agent["acting_account"]["id"] == org
    added, err = _tool(anon, token, "add_contacts", {"contacts": [{"name": "Pat", "phone": "+14155550111"}]})
    assert not err and added["added"] == 1

    # The agent and contact landed in the customer's account, not the admin's own.
    detail = client.get(f"/api/admin/orgs/{org}").json()
    assert detail["agents"] >= 1 and detail["contacts"] == 1

    # account_id aims a single call at another account.
    other = _customer(client, "Other Co")
    out, err = _tool(anon, token, "list_agents", {"account_id": other})
    assert not err and out["acting_account"]["name"] == "Other Co"

    preview, err = _tool(anon, token, "admin_add_credits", {"account_id": org, "amount": 50})
    assert not err and preview["needs_confirmation"]
    done, err = _tool(anon, token, "admin_add_credits", {"account_id": org, "amount": 50, "confirmed": True})
    assert not err and done["balance"] == preview["balance_after"]

    log = client.get("/api/admin/ai-access").json()["actions"]
    tools_logged = [a["tool"] for a in log]
    assert {"create_agent", "add_contacts", "admin_use_account", "admin_add_credits"} <= set(tools_logged)
    assert next(a for a in log if a["tool"] == "create_agent")["account"] == "Acme Roofing"

    # Switching it off removes the access at once.
    assert client.delete(f"/api/admin/ai-access/{conn}").status_code == 204
    out, err = _tool(anon, token, "list_agents", {"account_id": org})
    assert err and "Admin mode is off" in out["error"]


def test_admin_mode_needs_a_super_admin_and_the_unlocked_portal(client, make_client):
    anon = make_client()
    _connect(client, anon)
    conn = _connection_id(client)
    locked = make_client()
    assert locked.post("/api/auth/login", json={"email": "admin@test.dev", "password": "admin-pass-123"}).status_code == 200
    assert locked.post(f"/api/admin/ai-access/{conn}", json={"hours": 1}).status_code == 423
    assert client.post(f"/api/admin/ai-access/{uuid.uuid4()}", json={"hours": 1}).status_code == 404
    assert client.post(f"/api/admin/ai-access/{conn}", json={"hours": 48}).status_code == 422
