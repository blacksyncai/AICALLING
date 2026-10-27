"""Stress-test runs are saved (reopen after closing the tab), with model usage visible to staff only."""

import asyncio

from tests.test_accounts import _login, _new_account


def test_usage_meter_adds_up_and_prices_models():
    from app.services import llm, stress_test

    meter: dict = {}
    token = llm.usage_meter.set(meter)
    try:
        llm._meter("gpt-4.1-mini", {"usage": {"prompt_tokens": 1_000_000, "completion_tokens": 0}})
        llm._meter("gpt-4.1-mini", {"usage": {"prompt_tokens": 0, "completion_tokens": 500_000}})
        llm._meter("some-new-model", {"usage": {"input_tokens": 100_000, "output_tokens": 0}})
    finally:
        llm.usage_meter.reset(token)
    llm._meter("gpt-4.1-mini", {"usage": {"prompt_tokens": 5}})  # no meter set: ignored
    out = stress_test.cost_of(meter)
    assert meter["gpt-4.1-mini"] == {"input": 1_000_000, "output": 500_000, "calls": 2, "cost_usd": 1.2}
    assert out["cost_usd"] == 1.3 and out["input_tokens"] == 1_100_000  # 0.4 + 0.8 + fallback 0.1


def test_runs_are_saved_and_cost_is_staff_only(client, make_client, monkeypatch):
    from app.services import stress_test

    async def fake_run(cfg, variables, only=None):
        return {"results": [{"id": "booking", "title": "Books a meeting", "passed": True, "transcript": [], "checks": []}],
                "passed": 1, "total": 1, "usage": {"cost_usd": 0.42, "input_tokens": 9, "output_tokens": 3, "by_model": {}}}

    monkeypatch.setattr(stress_test, "run", fake_run)
    agent = client.post("/api/agents/", json={"template": "sales_sdr"}).json()
    ran = client.post(f"/api/agents/{agent['id']}/stress-test", json={}).json()
    assert ran["passed"] == 1 and ran["id"] and ran["cost_usd"] == 0.42  # the default test user is staff
    runs = client.get(f"/api/agents/{agent['id']}/stress-tests").json()["runs"]
    assert runs[0]["id"] == ran["id"] and runs[0]["cost_usd"] == 0.42
    full = client.get(f"/api/agents/{agent['id']}/stress-tests/{ran['id']}").json()
    assert full["results"][0]["title"] == "Books a meeting" and full["usage"]["cost_usd"] == 0.42

    # A customer sees their runs, not what they cost us; other accounts can't open them.
    org, email = _new_account(client, name="Stress Co")
    owner = _login(make_client, email)
    mine = owner.post("/api/agents/", json={"template": "sales_sdr"}).json()
    theirs = owner.post(f"/api/agents/{mine['id']}/stress-test", json={}).json()
    assert "cost_usd" not in theirs and "usage" not in theirs
    assert "cost_usd" not in owner.get(f"/api/agents/{mine['id']}/stress-tests").json()["runs"][0]
    assert owner.get(f"/api/agents/{agent['id']}/stress-tests/{ran['id']}").status_code == 404
