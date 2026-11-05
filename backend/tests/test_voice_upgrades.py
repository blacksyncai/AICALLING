"""Sonic 3.5 upgrades: tone presets, account-wide pronunciations, and accounts cloning their own voice."""

import asyncio
import uuid

import httpx
import pytest

from app.agent.voice_tuning import voice_tuning
from app.config import settings
from app.routers import settings as settings_router
from tests.test_accounts import _login, _new_account
from tests.test_voices_models import OWNED, cartesia  # noqa: F401


def test_tone_maps_to_cartesia_emotion():
    assert voice_tuning({"tone": "warm"})["emotion"] == "Content"
    assert voice_tuning({"tone": "calm"})["emotion"] == "Calm"
    assert voice_tuning({})["emotion"] is None


def test_account_pronunciations_apply_to_every_agent(client):
    from app.agent.runtime import runtime_for
    from app.database import AsyncSessionLocal
    from app.models.agent import Agent

    r = client.put("/api/settings/pronunciations", json={"pronunciations": [
        {"word": "eXp", "say": "E X P"}, {"word": "exp", "say": "dup"}, {"word": "", "say": "x"}]})
    assert r.status_code == 200 and r.json()["pronunciations"] == [{"word": "eXp", "say": "E X P"}]
    agent_id = client.post("/api/agents/", json={"template": "sales_sdr"}).json()["id"]
    client.patch(f"/api/agents/{agent_id}", json={"voice_tuning": {"tone": "upbeat",
                 "pronunciations": [{"word": "Nguyen", "say": "Win"}]}})

    async def cfg():
        async with AsyncSessionLocal() as db:
            return await runtime_for(db, await db.get(Agent, uuid.UUID(agent_id)))
    pron = asyncio.run(cfg())["voice_tuning"]["pronunciations"]
    assert [p["word"] for p in pron] == ["Nguyen", "eXp"]
    client.put("/api/settings/pronunciations", json={"pronunciations": []})


def test_clone_is_private_to_the_account(client, make_client, monkeypatch, cartesia):  # noqa: F811
    org, email = _new_account(client, name="Clone Realty")
    owner = _login(make_client, email)
    sent = {}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, **kw):
            sent["url"], sent["data"] = url, kw.get("data")
            return httpx.Response(200, json={"id": "clone-" + uuid.uuid4().hex[:8]}, request=httpx.Request("POST", url))
        async def delete(self, url, **kw):
            sent["deleted"] = url
            return httpx.Response(204, request=httpx.Request("DELETE", url))

    monkeypatch.setattr(settings_router.httpx, "AsyncClient", FakeClient)
    assert owner.post("/api/settings/voices/clone", files={"file": ("me.wav", b"x" * 100, "audio/wav")},
                      data={"name": "Maxwell"}).status_code == 400  # too short
    r = owner.post("/api/settings/voices/clone", files={"file": ("me.wav", b"x" * 50_000, "audio/wav")},
                   data={"name": "Maxwell"})
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    assert sent["url"].endswith("/voices/clone") and sent["data"]["mode"] == "similarity"
    assert [v["id"] for v in owner.get("/api/settings/voices/mine").json()["voices"]] == [vid]

    # Another account never sees it, even when Cartesia lists it among the platform's own voices.
    async def with_clone():
        return [], [*OWNED, {"id": vid, "name": "Maxwell (Clone Realty)", "language": "en"}]
    monkeypatch.setattr(settings_router, "_fetch_cartesia_voices", with_clone)
    settings_router._voice_cache.update(at=0.0, public=None, owned=None)
    listed = {v["id"] for v in client.get("/api/settings/voices").json()["voices"]}
    assert vid not in listed and "own-1" in listed
    assert vid not in {v["id"] for v in client.get("/api/settings/voices/mine").json()["voices"]}
    other_agent = client.post("/api/agents/", json={"template": "sales_sdr"}).json()["id"]
    assert client.patch(f"/api/agents/{other_agent}", json={"voice_id": vid}).status_code == 403
    mine = owner.post("/api/agents/", json={"template": "sales_sdr"}).json()["id"]
    assert owner.patch(f"/api/agents/{mine}", json={"voice_id": vid}).status_code == 200

    assert owner.delete(f"/api/settings/voices/mine/{vid}").status_code == 204
    assert sent["deleted"].endswith(vid)
    assert owner.get("/api/settings/voices/mine").json()["voices"] == []
