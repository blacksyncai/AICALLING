"""Outbound calls where the contact never said a live word are not conversations."""

from types import SimpleNamespace

from app.services.outbound_call import silent_pickup_outcome


def _call(outcome, transcript, call_type="outbound"):
    return SimpleNamespace(call_type=call_type, outcome=outcome, transcript=transcript)


TOOL = {"role": "tool", "tool": "end_call", "args": {"reason": "silence"}}


def test_agent_only_transcript_keeps_the_no_conversation_result():
    # Southpoint: opening, "Hello? Can you hear me okay?", hung up on silence; analysis said "insufficient".
    t = [{"role": "assistant", "text": "Hey, this is Zane. Do you have a quick second?"},
         {"role": "assistant", "text": "Hello? Can you hear me okay?"}, TOOL]
    assert silent_pickup_outcome(_call("insufficient_conversation", t), "no_answer") == "no_answer"
    assert silent_pickup_outcome(_call("insufficient_conversation", t), "voicemail") == "voicemail"
    # Repairing an old call (no earlier result to keep): nobody said anything at all.
    assert silent_pickup_outcome(_call("insufficient_conversation", t), "insufficient_conversation") == "no_answer"


def test_screener_that_never_put_anyone_through_is_screened():
    t = [{"role": "tool", "tool": "call_screener", "args": {"action": "answer"}},
         {"role": "assistant", "text": "Hey Scott, it's just..."}, TOOL]
    assert silent_pickup_outcome(_call("insufficient_conversation", t), "insufficient_conversation") == "screened"
    assert silent_pickup_outcome(_call("insufficient_conversation", t), "screened") == "screened"


def test_a_live_word_or_an_inbound_call_is_left_alone():
    t = [{"role": "assistant", "text": "Hey John, this is Zane."}, {"role": "user", "text": "Nothing. Cheese."}]
    assert silent_pickup_outcome(_call("insufficient_conversation", t), "no_answer") is None
    quiet = [{"role": "assistant", "text": "Thanks for calling, how can I help?"}]
    assert silent_pickup_outcome(_call("insufficient_conversation", quiet, call_type="inbound"), None) is None
    assert silent_pickup_outcome(_call("not_interested", quiet), None) is None
