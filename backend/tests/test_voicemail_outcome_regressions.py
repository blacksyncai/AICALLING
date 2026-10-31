"""Outcome evidence must agree before a greeting can reach follow-up consumers."""

import asyncio
import uuid

import pytest

from app.agent.runtime import (
    callback_requested, person_answered, reconcile_outcome, screener_match,
)


def contact(text, **extra):
    return {"role": "user", "text": text, **extra}


GREETINGS = (
    "Leave your name and reason for calling, and I'll return your call.",
    "Please leave a message and I'll call you back.",
    "Hi, you've reached Sam. Please leave your name and I'll return your call.",
    "Hey, it's Hamza, I can't talk right now, I'll call you back or just text me",
)


@pytest.mark.parametrize("greeting", GREETINGS)
@pytest.mark.parametrize("proposed", ["callback", "qualified", "interested", "completed", "voicemail"])
def test_recorded_promises_never_become_follow_up(greeting, proposed):
    transcript = [contact(greeting)]
    assert not person_answered(transcript)
    assert not callback_requested(transcript)
    assert reconcile_outcome(proposed, transcript) == "voicemail"


def test_name_and_reason_greeting_is_not_a_screener():
    assert not screener_match(GREETINGS[0])
    assert screener_match("Record your name and reason for calling and I'll see if they're available.")


@pytest.mark.parametrize("utterance", [
    "I'm busy—call me tomorrow afternoon.",
    "Can you catch me another time?",
    "Can you call me back later?",
    "I can't talk right now, can you just text me instead?",
    "I want to think about it and check with my partner.",
])
def test_live_callback_requests_survive(utterance):
    transcript = [contact(utterance)]
    assert person_answered(transcript)
    assert reconcile_outcome("callback", transcript) == "callback"
    assert reconcile_outcome("voicemail", transcript) == "completed"


def test_human_after_screening_can_defer_without_a_hello():
    transcript = [
        contact("Record your name and reason for calling and I'll see if they're available."),
        {"role": "tool", "tool": "call_screener", "args": {"action": "answer"}},
        contact("Please stay on the line."),
        contact("I'm busy—call me tomorrow afternoon."),
    ]
    assert person_answered(transcript)
    assert reconcile_outcome("callback", transcript) == "callback"


@pytest.mark.parametrize("transcript", [
    [], [contact("Hello?")],
    [{"role": "assistant", "text": "I'll call you back tomorrow."}],
    [contact("Please stay on the line.")],
])
def test_ambiguous_calls_do_not_invent_callback_or_voicemail(transcript):
    assert reconcile_outcome("callback", transcript) == "completed"


def test_greeting_split_across_final_transcriptions():
    transcript = [contact("Hi."), contact("Please leave your name and reason for calling."),
                  contact("And I'll return your call.")]
    assert reconcile_outcome("callback", transcript) == "voicemail"


def test_conflicting_detection_signals_use_live_context():
    machine = {"role": "tool", "tool": "answer_detection",
               "args": {"result": "opaque-provider-value", "is_machine": True, "reason": "recording"}}
    assert reconcile_outcome("callback", [machine]) == "voicemail"
    assert reconcile_outcome("callback", [machine, contact("Call me tomorrow afternoon.")]) == "callback"
    assert reconcile_outcome("callback", [contact("Call me tomorrow afternoon."), machine]) == "callback"
    human = {"role": "tool", "tool": "answer_detection", "args": {"is_machine": False}}
    assert reconcile_outcome("callback", [human, contact(GREETINGS[1])]) == "voicemail"


def test_worker_voicemail_marker_and_later_pickup():
    marker = {"role": "tool", "tool": "voicemail", "args": {"action": "hung_up"}}
    greeting = contact(GREETINGS[1], voicemail_greeting=True)
    assert reconcile_outcome("callback", [marker, greeting]) == "voicemail"
    assert reconcile_outcome("callback", [marker, greeting, contact("Can you catch me another time?")]) == "callback"


@pytest.mark.parametrize("stored,analyzed,transcript,expected", [
    ("callback", "callback", [contact(GREETINGS[0])], "voicemail"),
    ("qualified", "qualified", [contact(GREETINGS[1])], "voicemail"),
    ("completed", "callback", [contact(GREETINGS[1])], "voicemail"),
    ("callback", "voicemail", [contact("I'm busy, call me tomorrow afternoon.")], "callback"),
    ("completed", "callback", [contact("Hello?")], "completed"),
])
def test_analysis_conflicts_are_resolved_before_radar(client, monkeypatch, stored, analyzed, transcript, expected):
    from app.database import AsyncSessionLocal
    from app.models.call_log import CallLog
    from app.services import llm, outbound_call
    from app.services.crm import automations

    routed = []

    async def fake_analyze(*args):
        return {"summary": "Test analysis", "outcome": analyzed, "extracted": {}}

    async def capture_radar(db, call):
        routed.append(call.outcome)

    monkeypatch.setattr(llm, "analyze_call", fake_analyze)
    monkeypatch.setattr(automations, "on_analyzed_call", capture_radar)
    cid = uuid.uuid4()

    async def run():
        async with AsyncSessionLocal() as db:
            db.add(CallLog(id=cid, call_type="outbound", status="completed", outcome=stored,
                           transcript=transcript, duration_seconds=35, livekit_room_name=f"regression-{cid}"))
            await db.commit()
        await outbound_call._analyze(str(cid))
        async with AsyncSessionLocal() as db:
            call = await db.get(CallLog, cid)
            return call.outcome, call.status

    outcome, status = asyncio.run(run())
    assert outcome == expected
    assert routed == [expected]
    assert status == ("no_answer" if expected == "voicemail" else "completed")


def test_live_agreement_to_an_agent_callback_offer():
    transcript = [contact("Hello?"), {"role": "assistant", "text": "Would you like me to call you tomorrow?"},
                  contact("Yes, that works.")]
    assert reconcile_outcome("callback", transcript) == "callback"


def test_live_request_without_question_punctuation():
    transcript = [contact("You've reached me at a bad time please call me tomorrow")]
    assert reconcile_outcome("callback", transcript) == "callback"


def test_outcome_report_corrects_contact_before_consumers(client, monkeypatch):
    from types import SimpleNamespace
    from app.database import AsyncSessionLocal
    from app.models.call_log import CallLog
    from app.models.lead import Lead
    from app.routers.campaigns import RETRY_STATUSES
    from app.services import call_alerts, outbound_call
    from app.services.crm.automations import condition_matches
    from app.services.crm.sync import OUTCOME_TO_KEY

    async def no_charge(*args):
        pass

    monkeypatch.setattr(outbound_call, "charge_call", no_charge)

    async def run():
        async with AsyncSessionLocal() as db:
            lead = Lead(name="Voicemail Regression", phone="+14155550199", status="calling")
            db.add(lead)
            await db.flush()
            call = CallLog(lead_id=lead.id, livekit_room_name=f"report-{uuid.uuid4()}", call_type="outbound")
            db.add(call)
            await db.commit()
            result = await outbound_call.outbound_call_service.update_call_outcome(
                call_log_id=str(call.id), outcome="callback", transcript=[contact(GREETINGS[0])],
                meeting_link=None, qualification_score=None, db=db)
            await db.refresh(lead)
            return result, lead.status

    call, status = asyncio.run(run())
    assert call.outcome == "voicemail" and call.status == "no_answer"
    assert status == "voicemail" and status in RETRY_STATUSES
    assert OUTCOME_TO_KEY[call.outcome] == "voicemail"
    assert call.outcome not in call_alerts.DEFAULT_OUTCOMES
    assert not condition_matches(SimpleNamespace(kind="outcome", value="callback"), call, {})
    assert condition_matches(SimpleNamespace(kind="outcome", value="voicemail"), call, {})


@pytest.mark.parametrize("utterance", [
    "I'm tied up this afternoon; could we chat in a couple hours?",
    "¿Podemos hablar mañana por la tarde?",
])
def test_verbatim_model_evidence_supports_other_wording_and_languages(utterance):
    transcript = [contact(utterance)]
    assert reconcile_outcome("callback", transcript, callback_request=utterance) == "callback"
    recorded = transcript + [{"role": "tool", "tool": "end_call",
                              "args": {"outcome": "callback", "callback_request": utterance}}]
    assert reconcile_outcome("callback", recorded) == "callback"


def test_callback_evidence_must_be_live_contact_speech():
    assert reconcile_outcome("callback", [contact(GREETINGS[0])], callback_request=GREETINGS[0]) == "voicemail"
    assert reconcile_outcome("callback", [contact("Hello?")], callback_request="Call me tomorrow") == "completed"


@pytest.mark.parametrize("transcript,quote,expected", [
    ([contact(GREETINGS[0])], GREETINGS[0], "voicemail"),
    ([contact("¿Podemos hablar mañana por la tarde?")], "¿Podemos hablar mañana por la tarde?", "callback"),
    ([contact("Hello?")], "Call me tomorrow", "completed"),
])
def test_ai_analysis_reconciles_its_own_callback_output(monkeypatch, transcript, quote, expected):
    import json
    from app.services import llm

    async def fake_chat(payload, **kwargs):
        return {"choices": [{"message": {"content": json.dumps({
            "outcome": "callback", "callback_request": quote, "extracted": {},
        })}}]}

    monkeypatch.setattr(llm, "_chat", fake_chat)
    result = asyncio.run(llm.analyze_call(transcript, None))
    assert result["outcome"] == expected
