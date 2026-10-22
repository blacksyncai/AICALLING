from types import SimpleNamespace

from app.agent import handoff
from app.agent.runtime import _tools_block


def test_default_handoff_names_the_caller_and_agent():
    cfg = {"persona_name": "Sofia", "business_name": "Summit Realty"}
    line = handoff.handoff_line(cfg, {"full_name": "Mark Ellis", "first_name": "Mark"})
    assert line.startswith("Hey, it's Sofia from Summit Realty. I've got Mark Ellis on the line.")
    assert "[One sentence" in line and line.endswith("Want me to put them through?")


def test_custom_handoff_fills_variables_and_handles_unknown_callers():
    cfg = {"transfer_handoff": "Hey team, {{full_name}} is on the line about {{property_street}}.",
           "business_name": "Summit Realty"}
    assert handoff.handoff_line(cfg, {"full_name": "Mark Ellis", "property_street": "214 Asheville St"}) == \
        "Hey team, Mark Ellis is on the line about 214 Asheville St."
    assert handoff.handoff_line({"business_name": "X"}, {}).startswith(
        "Hey, it's the assistant from X. I've got a caller on the line.")


def test_briefing_includes_handoff_tools_and_history():
    text = handoff.briefing_instructions({"business_name": "Summit Realty", "persona_name": "Sofia"},
                                         {"full_name": "Mark Ellis"}, "Caller: I want to sell\nYou: Got it")
    for want in ("can't hear you", "connect_to_caller", "decline_transfer", "voicemail_detected",
                 "Caller: I want to sell", "I've got Mark Ellis on the line"):
        assert want in text


def test_history_text_keeps_only_spoken_turns():
    msgs = [SimpleNamespace(role="system", text_content="rules"), SimpleNamespace(role="user", text_content="hi"),
            SimpleNamespace(role="assistant", text_content="hey there"), SimpleNamespace(role="user", text_content="")]
    assert handoff.history_text(SimpleNamespace(messages=lambda: msgs)) == "Caller: hi\nYou: hey there"


def test_not_connected_keeps_the_caller_and_offers_next_step():
    booked = handoff.not_connected("no_answer", booking=True)
    assert "Nobody picked up" in booked and "check_availability" in booked and "Don't end the call" in booked
    vm = handoff.not_connected("voicemail", booking=False)
    assert "callback" in vm and "don't mention voicemail" in vm


def test_rules_describe_warm_vs_cold_transfer():
    base = {"transfer_number": "+14155550123", "business_name": "Summit Realty"}
    warm = _tools_block({**base, "transfer_mode": "warm"}, "phone")
    cold = _tools_block({**base, "transfer_mode": "cold"}, "phone")
    assert "short hold" in warm and "Never end the call because a transfer didn't connect" in warm
    assert "connecting you now" in cold and "short hold" not in cold
