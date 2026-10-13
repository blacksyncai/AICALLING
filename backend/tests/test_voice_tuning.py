import asyncio

from app.agent.models import llm_endpoint
from app.agent.voice_tuning import apply_pronunciations, pronounce, voice_tuning


def test_defaults_match_standard_turn_taking():
    t = voice_tuning({})
    assert (t["min_delay"], t["max_delay"], t["min_duration"], t["min_words"], t["volume"]) == (0.35, 2.5, 0.5, 2, 1.0)
    fast = voice_tuning({"responsiveness": 1, "interruption": 1, "volume": 9})
    assert fast["min_delay"] < 0.35 and fast["min_words"] == 1 and fast["volume"] == 2.0


def test_pronunciations_whole_words_and_streaming():
    pairs = [("AI", "A.I."), ("BlackSync AI", "Black Sync A.I.")]
    assert apply_pronunciations("I said AI, not said", [("AI", "A.I.")]) == "I said A.I., not said"

    async def run():
        async def chunks():
            for c in ["Welcome to Black", "Sync ", "AI", " and its AI tools. Said."]:
                yield c
        return "".join([x async for x in pronounce(pairs[::-1])(chunks())])

    assert asyncio.run(run()) == "Welcome to Black Sync A.I. and its A.I. tools. Said."


def test_claude_models_use_anthropic_endpoint():
    key, url, temp = llm_endpoint("claude-haiku-5-5")
    assert "anthropic.com" in url and temp is False
    assert llm_endpoint("gpt-4.1-mini")[2] is True


def test_agent_saves_voice_tuning(client):
    a = client.post("/api/agents", json={"template": "blank"}).json()
    body = {"voice_tuning": {"volume": 1.2, "responsiveness": 0.9,
                             "pronunciations": [{"word": "BlackSync", "say": "Black Sync"}, {"word": "", "say": ""}]}}
    r = client.patch(f"/api/agents/{a['id']}", json=body)
    assert r.status_code == 200, r.text
    vt = r.json()["voice_tuning"]
    assert vt["volume"] == 1.2 and "interruption" not in vt and vt["pronunciations"] == [{"word": "BlackSync", "say": "Black Sync"}]


def test_blacksync_super_intelligence_models(monkeypatch):
    from app.agent import models
    from app.config import settings

    monkeypatch.setattr(settings, "cerebras_api_key", "csk-test")
    key, url, temp = models.llm_endpoint("gpt-oss-120b")
    assert key == "csk-test" and "cerebras" in url and temp is True
    names = {m["id"]: m["name"] for m in models.model_catalog()}
    assert names["gpt-oss-120b"].startswith("BlackSync Super Intelligence")
    monkeypatch.setattr(settings, "cerebras_api_key", "")
    assert "gpt-oss-120b" not in {m["id"] for m in models.model_catalog()}


def test_our_name_is_spoken_once_not_read_as_a_link():
    from app.agent.voice_tuning import BUILT_IN_PRONUNCIATIONS, apply_pronunciations

    say = lambda t: apply_pronunciations(t, BUILT_IN_PRONUNCIATIONS)  # noqa: E731
    assert say("I'm an AI assistant built with BlackSync AI (blacksync.ai).") == \
        "I'm an AI assistant built with BlackSync dot A I."
    assert say("Check out blacksync.ai today") == "Check out BlackSync dot A I today"


def test_guardrail_answer_is_short_and_spoken():
    from app.agent.runtime import guardrails

    g = guardrails({"business_name": "Compass"})
    assert "BlackSync dot A I" in g and "(blacksync" not in g and "spell that" in g
