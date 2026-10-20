from app.services.public_errors import GENERIC, public_detail


def test_hides_env_names_and_vendors():
    assert public_detail("/api/calls/1", "Set LIVEKIT_SIP_OUTBOUND_TRUNK_ID first") == GENERIC
    assert public_detail("/api/campaigns/x/start", "Twilio error 21212") == GENERIC
    assert public_detail("/api/crm/fub", "Secret storage isn't configured on the server.") == GENERIC
    assert public_detail("/api/agents/", {"message": "needs OPENAI_API_KEY", "code": 3}) == {"message": GENERIC, "code": 3}


def test_keeps_plain_messages_and_admin_detail():
    assert public_detail("/api/agents/1", "Agent not found") == "Agent not found"
    assert public_detail("/api/admin/orgs", "Twilio error 21212") == "Twilio error 21212"
    assert public_detail("/api/settings/status", "LIVEKIT_URL missing") == GENERIC


def test_internal_routes_need_the_worker_token_when_set(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "internal_token", "t0k")
    url = "/internal/agents/00000000-0000-0000-0000-000000000000/runtime"
    assert client.get(url).status_code == 403
    assert client.get(url, headers={"X-Internal-Token": "nope"}).status_code == 403
    assert client.get(url, headers={"X-Internal-Token": "t0k"}).status_code == 404  # past the check


def test_a_failed_label_on_a_real_conversation_is_not_redialable():
    from app.agent.runtime import reconcile_outcome

    talk = [{"role": "assistant", "text": "Hey, is this Sam?"}, {"role": "user", "text": "Yeah, who's this?"},
            {"role": "user", "text": "Sure, tell me more about the property."}]
    assert reconcile_outcome("failed", talk) == "completed"
    assert reconcile_outcome("failed", []) == "failed"


def test_customer_voice_settings_hide_provider_errors():
    for brand in ("ElevenLabs", "Eleven Labs", "eleven-labs", "Cartesia", "Deepgram", "SignalWire", "Bandwidth"):
        assert public_detail("/api/settings/voices/preview", f"Check {brand} access to this voice") == GENERIC
