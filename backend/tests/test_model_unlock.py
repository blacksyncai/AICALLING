def test_flash_models_need_an_unlock(client):
    org = client.get("/api/auth/me").json()["org"]
    client.patch(f"/api/admin/orgs/{org['id']}", json={"models_unlocked": False})
    agent = client.post("/api/agents/", json={"template": "blank"}).json()
    try:
        catalog = {m["id"]: m for m in client.get("/api/settings/models").json()["models"]}
        if "mistral-medium-latest" in catalog:
            assert catalog["mistral-medium-latest"]["locked"] is True
        assert not catalog.get("gpt-4.1-mini", {}).get("locked")
        # Locked: switching to a Flash model is refused; open models still work.
        r = client.patch(f"/api/agents/{agent['id']}", json={"llm_model": "mistral-medium-latest"})
        assert r.status_code == 403 and "Contact support" in r.json()["detail"]
        assert client.patch(f"/api/agents/{agent['id']}", json={"llm_model": "gpt-4.1-mini"}).status_code == 200
        # The team unlocks it for the account.
        assert client.patch(f"/api/admin/orgs/{org['id']}", json={"models_unlocked": True}).json()["models_unlocked"] is True
        assert client.patch(f"/api/agents/{agent['id']}", json={"llm_model": "mistral-medium-latest"}).status_code == 200
        # Locking again never breaks an agent already on it: saving other changes still works.
        client.patch(f"/api/admin/orgs/{org['id']}", json={"models_unlocked": False})
        r = client.patch(f"/api/agents/{agent['id']}", json={"name": "Still on Flash", "llm_model": "mistral-medium-latest"})
        assert r.status_code == 200 and r.json()["llm_model"] == "mistral-medium-latest"
    finally:
        client.patch(f"/api/admin/orgs/{org['id']}", json={"models_unlocked": False})
