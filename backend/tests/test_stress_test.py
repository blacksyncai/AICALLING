import asyncio

from app.services import stress_test


def test_stress_run_plays_scenarios_and_grades(monkeypatch):
    calls = {"agent": 0}

    async def fake_reply(cfg, variables, history, state, channel="chat"):
        assert channel == "phone"
        calls["agent"] += 1
        if not history:
            return {"reply": "", "opening": "Hey, is this Jordan?", "tool_events": [], "ended": False,
                    "outcome": None, "state": state}
        return {"reply": "Got it, have a good one.", "tool_events": [], "ended": True, "outcome": "completed",
                "state": state}

    async def fake_chat(payload, timeout=45.0):
        if payload.get("response_format"):
            content = '{"checks": [{"check": "x", "result": "fail", "evidence": "y"}], "problems": ["p"]}'
        else:
            content = "Yeah, who's this?"
        return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr(stress_test, "playground_reply", fake_reply)
    monkeypatch.setattr(stress_test, "_chat", fake_chat)
    out = asyncio.run(stress_test.run({"enable_booking": False}, {}, ["busy", "dnc"]))
    assert out["total"] == 2 and out["passed"] == 0
    r = out["results"][0]
    assert [t["role"] for t in r["transcript"]] == ["assistant", "user", "assistant"]
    assert r["problems"] == ["p"] and r["outcome"] == "completed"


def test_booking_scenario_only_when_booking_is_on():
    assert "booking" not in {s["id"] for s in stress_test.scenarios_for({})}
    assert "booking" in {s["id"] for s in stress_test.scenarios_for({"enable_booking": True})}
