"""Voice catalog (categories, metadata, preview cache) and the LLM model catalog."""

import pytest

from app.agent import models as model_mod
from app.agent.runtime import agent_to_runtime
from app.agent.voices import FEATURED_VOICES
from app.config import settings
from app.routers import settings as settings_router

LAUREN = "6c756032-11c3-4be8-a120-74f9673fb700"
PUBLIC = [
    {"id": LAUREN, "name": "Lauren (catalog)", "gender": "feminine", "language": "en",
     "description": "Warm American voice"},
    {"id": "pub-1", "name": "Brit", "gender": "masculine", "language": "en",
     "description": "A calm British narrator"},
    {"id": "pub-2", "name": "Sofia", "gender": "feminine", "language": "es", "description": "Friendly"},
    {"id": "pub-3", "name": "Kai", "gender": "gender_neutral", "language": "ja"},
    {"id": "own-1", "name": "Should be owned", "language": "en"},
]
OWNED = [{"id": "own-1", "name": "My Clone", "gender": "masculine", "language": "en", "description": ""}]


@pytest.fixture
def cartesia(monkeypatch):
    """Pretend a Cartesia key is set and return canned catalog payloads."""
    calls = {"voices": 0, "tts": 0}

    async def fake_fetch():
        calls["voices"] += 1
        return PUBLIC, OWNED

    async def fake_tts(payload):
        calls["tts"] += 1
        return b"RIFF-fake-wav-" + payload["voice"]["id"].encode()

    monkeypatch.setattr(settings, "cartesia_api_key", "test-cartesia")
    monkeypatch.setattr(settings_router, "_fetch_cartesia_voices", fake_fetch)
    monkeypatch.setattr(settings_router, "_synthesize", fake_tts)
    settings_router._voice_cache.update(at=0.0, public=None, owned=None)
    settings_router._preview_cache.clear()
    yield calls
    settings_router._voice_cache.update(at=0.0, public=None, owned=None)
    settings_router._preview_cache.clear()


def _by_id(body):
    return {v["id"]: v for v in body["voices"]}


HOUSE_CLONES = [f["id"] for f in FEATURED_VOICES if f.get("clone")]
HOUSE_STOCK = [f["id"] for f in FEATURED_VOICES if not f.get("clone")]


def test_categories_premium_is_clones_standard_is_curated(client, cartesia):
    body = client.get("/api/settings/voices").json()
    assert body["source"] == "cartesia"
    voices = _by_id(body)
    # Premium = cloned voices (house clones + the account's own clones).
    for vid in HOUSE_CLONES + ["own-1"]:
        assert voices[vid]["category"] == "premium"
    # Standard = the curated house voices only — not Cartesia's whole public library.
    for vid in HOUSE_STOCK:
        assert voices[vid]["category"] == "standard"
    for vid in ("pub-1", "pub-2", "pub-3"):
        assert vid not in voices
    cats = {c["key"]: c for c in body["categories"]}
    assert cats["premium"]["label"] == "Premium Human Voices"
    assert cats["standard"]["label"] == "Standard AI Voices"
    assert cats["premium"]["count"] == len(HOUSE_CLONES) + 1
    assert cats["standard"]["count"] == len(HOUSE_STOCK)
    ids = [v["id"] for v in body["voices"]]
    assert len(ids) == len(set(ids)) and ids[0] in HOUSE_CLONES
    assert [f["id"] for f in body["featured"]] == [f["id"] for f in FEATURED_VOICES]


def test_category_config_override(client, cartesia, monkeypatch):
    monkeypatch.setattr(settings, "voice_premium_label", "Signature")
    monkeypatch.setattr(settings, "voice_standard_label", "Library")
    monkeypatch.setattr(settings, "premium_voice_ids", " pub-2 , ")
    monkeypatch.setattr(settings, "standard_voice_ids", "pub-1")
    body = client.get("/api/settings/voices").json()
    cats = {c["key"]: c["label"] for c in body["categories"]}
    assert cats == {"premium": "Signature", "standard": "Library"}
    voices = _by_id(body)
    assert voices["pub-2"]["category"] == "premium" and voices["pub-2"]["is_clone"] is False
    assert voices["pub-1"]["category"] == "standard"
    assert "pub-3" not in voices


def test_is_clone_only_for_real_clones(client, cartesia):
    voices = _by_id(client.get("/api/settings/voices").json())
    assert voices["own-1"]["is_clone"] is True
    assert voices["own-1"]["name"] == "My Clone"  # owned metadata wins
    for vid in HOUSE_CLONES:
        assert voices[vid]["is_clone"] is True
    for vid in HOUSE_STOCK:
        assert voices[vid]["is_clone"] is False


def test_voice_metadata_fields(client, cartesia, monkeypatch):
    monkeypatch.setattr(settings, "standard_voice_ids", "pub-1,pub-2,pub-3")
    voices = _by_id(client.get("/api/settings/voices").json())
    for v in voices.values():
        assert {"id", "name", "provider", "category", "language", "accent", "gender", "description",
                "is_clone", "preview", "models", "status"} <= v.keys()
        assert v["provider"] == ("mistral" if v["id"].startswith("mistral:") else "cartesia")
        assert v["models"] == (["voxtral-mini-tts-latest"] if v["provider"] == "mistral" else ["sonic-3"])
        assert v["status"] == "available"
        assert v["preview"] is True
    assert voices["pub-1"]["accent"] == "British"
    assert voices["pub-1"]["gender"] == "male"
    assert voices["pub-2"]["accent"] is None  # nothing in the metadata → no guess
    assert voices["pub-3"]["gender"] == "neutral"
    lauren = voices[LAUREN]
    assert lauren["name"] == "Lauren"  # house name kept
    assert lauren["language"] == "en"
    assert lauren["accent"] == "American"  # from the Cartesia description, not the house one
    assert lauren["description"] == next(f for f in FEATURED_VOICES if f["id"] == LAUREN)["description"]
    assert lauren["gender"] == "female"


def test_catalog_is_cached(client, cartesia):
    client.get("/api/settings/voices")
    client.get("/api/settings/voices")
    assert cartesia["voices"] == 1


def test_fallback_without_key(client, monkeypatch):
    monkeypatch.setattr(settings, "cartesia_api_key", "")
    body = client.get("/api/settings/voices").json()
    assert body["source"] == "fallback"
    assert body["message"]
    assert body["voices"]
    assert all(v["preview"] is False for v in body["voices"])
    cats = {c["key"]: c["count"] for c in body["categories"]}
    assert cats["premium"] == len(HOUSE_CLONES)
    assert cats["standard"] == len(HOUSE_STOCK)


def test_fallback_when_cartesia_errors(client, monkeypatch):
    async def boom():
        raise RuntimeError("down")

    monkeypatch.setattr(settings, "cartesia_api_key", "k")
    monkeypatch.setattr(settings_router, "_fetch_cartesia_voices", boom)
    settings_router._voice_cache.update(at=0.0, public=None, owned=None)
    body = client.get("/api/settings/voices").json()
    assert body["source"] == "fallback"
    assert "short list" in body["message"]


def test_preview_requires_key(client, monkeypatch):
    monkeypatch.setattr(settings, "cartesia_api_key", "")
    assert client.post("/api/settings/voices/preview", json={"voice_id": "x"}).status_code == 400


def test_preview_cache_hit(client, cartesia):
    req = {"voice_id": "pub-1", "text": "Hello", "speed": 1.0, "language": "en"}
    r1 = client.post("/api/settings/voices/preview", json=req)
    r2 = client.post("/api/settings/voices/preview", json=req)
    assert r1.status_code == r2.status_code == 200
    assert r1.headers["content-type"] == "audio/wav"
    assert r1.content == r2.content
    assert cartesia["tts"] == 1
    # A different speed is a different clip.
    client.post("/api/settings/voices/preview", json={**req, "speed": 1.2})
    assert cartesia["tts"] == 2


def test_preview_cache_is_bounded(client, cartesia):
    for i in range(settings_router._PREVIEW_CACHE_MAX + 5):
        client.post("/api/settings/voices/preview", json={"voice_id": f"v{i}", "text": "Hi"})
    assert len(settings_router._preview_cache) == settings_router._PREVIEW_CACHE_MAX


def test_models_endpoint(client):
    body = client.get("/api/settings/models").json()
    ids = [m["id"] for m in body["models"]]
    assert body["default"] in ids
    assert "gpt-4.1-mini" in ids and "gpt-4.1" in ids
    group_keys = [g["key"] for g in body["groups"]]
    assert group_keys == [k for k, _ in model_mod.GROUPS if k in group_keys]
    for g in body["groups"]:
        assert g["models"], g  # only non-empty groups
        assert all(i in ids for i in g["models"])
    assert "other" not in group_keys  # default server model is already curated
    for m in body["models"]:
        assert m["provider"] == "OpenAI"
        assert m["status"] == "available"
        assert m["speed"] in ("fast", "standard", None)
        assert set(m["tags"]) <= {"recommended", "fast", "advanced"}
        assert not m["id"].startswith(("o1", "o3", "o4"))  # no reasoning models
    assert {lang["code"] for lang in body["languages"]} >= {"en", "multi", "es"}


def test_models_other_group_for_custom_default(client, monkeypatch):
    monkeypatch.setattr(settings, "llm_model", "my-proxy-model")
    body = client.get("/api/settings/models").json()
    assert body["groups"][-1] == {"key": "other", "label": "Other", "models": ["my-proxy-model"]}


def test_every_model_is_accepted_by_runtime(client, agent_id):
    for m in client.get("/api/settings/models").json()["models"]:
        r = client.patch(f"/api/agents/{agent_id}", json={"llm_model": m["id"]})
        assert r.status_code == 200, r.text
        assert r.json()["llm_model"] == m["id"]

        class Row:  # what the worker receives
            id, name, system_prompt, first_message, knowledge_base = agent_id, "x", "", "", ""
            language, temperature, voice_id, voice_speed = "en", 0.5, "", 1.0
            background_audio = enable_booking = False
            calcom_event_type_id = transfer_number = ""
            max_duration_seconds = 600
            llm_model = m["id"]

        assert agent_to_runtime(Row())["llm_model"] == m["id"]
        assert model_mod.is_runnable_model(m["id"])


def test_language_mismatch_rules():
    assert model_mod.language_mismatch("en", "es") is True
    assert model_mod.language_mismatch("en", "en") is False
    assert model_mod.language_mismatch("en_US", "en") is False
    assert model_mod.language_mismatch("en", "multi") is False
    assert model_mod.language_mismatch(None, "es") is False
    assert model_mod.language_mismatch("", "es") is False


def test_mistral_voice_listed_as_premium_and_audio_converts(client, cartesia):
    from app.agent.mistral_tts import f32le_to_s16le, wav_header
    import struct

    voices = _by_id(client.get("/api/settings/voices").json())
    h = voices["mistral:01a133e4-93c6-7540-98b5-a917a4da562e"]
    assert h["name"] == "Hamza 2.0" and h["category"] == "premium" and h["provider"] == "mistral"
    m = voices["mistral:01a1340c-90cb-7714-8ee0-02732154b0dd"]
    assert m["name"] == "Marissa M 2.0" and m["category"] == "premium" and m["provider"] == "mistral"
    assert f32le_to_s16le(struct.pack("<3f", 0.0, 1.0, -2.0)) == struct.pack("<3h", 0, 32767, -32767)
    assert wav_header(10)[:4] == b"RIFF" and len(wav_header(10)) == 44
