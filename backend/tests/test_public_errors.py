from app.services.public_errors import GENERIC, public_detail


def test_hides_env_names_and_vendors():
    assert public_detail("/api/calls/1", "Set LIVEKIT_SIP_OUTBOUND_TRUNK_ID first") == GENERIC
    assert public_detail("/api/campaigns/x/start", "Twilio error 21212") == GENERIC
    assert public_detail("/api/crm/fub", "Secret storage isn't configured on the server.") == GENERIC
    assert public_detail("/api/agents/", {"message": "needs OPENAI_API_KEY", "code": 3}) == {"message": GENERIC, "code": 3}


def test_keeps_plain_messages_and_admin_detail():
    assert public_detail("/api/agents/1", "Agent not found") == "Agent not found"
    assert public_detail("/api/admin/orgs", "Twilio error 21212") == "Twilio error 21212"
    assert public_detail("/api/settings/status", "LIVEKIT_URL missing") == "LIVEKIT_URL missing"


def test_internal_routes_need_the_worker_token_when_set(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "internal_token", "t0k")
    url = "/internal/agents/00000000-0000-0000-0000-000000000000/runtime"
    assert client.get(url).status_code == 403
    assert client.get(url, headers={"X-Internal-Token": "nope"}).status_code == 403
    assert client.get(url, headers={"X-Internal-Token": "t0k"}).status_code == 404  # past the check
