import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.services.response_review import review_response, routing_outcome


def transcript(text):
    return [
        {"role": "assistant", "text": "Could I explain the service?"},
        {"role": "user", "text": text},
    ]


def result(outcome, quote=None, scope="offer", **extra):
    return {
        "outcome": outcome,
        "summary": "Reviewed",
        "extracted": {},
        "response_analysis": {
            "evidence_quote": quote,
            "response_scope": scope,
            "certainty": "clear",
            "next_action": "none_agreed",
            **extra,
        },
    }


@pytest.mark.parametrize(
    "text,proposed,scope,expected",
    [
        ("So this is a solicitation?", "not_interested", "unknown", "no_decision"),
        ("Thank you.", "not_interested", "offer", "insufficient_conversation"),
        ("Nope. I'm sorry. I'm too busy.", "not_interested", "timing", "busy"),
        (
            "No. No. Thank you.",
            "not_interested",
            "permission_to_speak",
            "declined_conversation",
        ),
        ("We do not want this service.", "not_interested", "offer", "not_interested"),
        ("Sure.", "interested", "permission_to_speak", "insufficient_conversation"),
        ("What does your service cost?", "interested", "offer", "interested"),
        (
            "I don't know if I want a meeting.",
            "not_interested",
            "meeting",
            "no_decision",
        ),
        ("I'm sorry, I don't have time right now.", "callback", "timing", "busy"),
    ],
)
def test_question_scope_and_contact_evidence(text, proposed, scope, expected):
    reviewed = review_response(result(proposed, text, scope), transcript(text))
    assert reviewed["outcome"] == expected
    assert reviewed["response_analysis"]["next_action"] == "none_agreed"


def test_refusing_meeting_can_coexist_with_accepting_text_information():
    turns = transcript("I don't know if I want a call.") + [
        {"role": "assistant", "text": "Can we send the valuation by text?"},
        {"role": "user", "text": "Yeah. That works."},
    ]
    reviewed = review_response(
        result(
            "completed",
            "I don't know if I want a call.",
            "meeting",
            next_action="send_information",
            next_action_quote="Yeah. That works.",
            channel="text",
            meeting_response="declined",
        ),
        turns,
    )
    assert reviewed["outcome"] == "information_requested"
    assert reviewed["response_analysis"]["meeting_response"] == "declined"
    assert reviewed["response_analysis"]["channel"] == "text"


def test_callback_needs_a_grounded_request_and_busy_alone_is_not_enough():
    busy = "I'm too busy and can't talk."
    reviewed = review_response(
        result(
            "callback",
            busy,
            "timing",
            next_action="callback_requested",
            next_action_quote=busy,
        ),
        transcript(busy),
    )
    assert reviewed["outcome"] == "busy"
    assert reviewed["response_analysis"]["next_action"] == "none_agreed"
    request = "Can you call me tomorrow afternoon?"
    reviewed = review_response(
        result(
            "no_decision",
            request,
            "offer",
            next_action="callback_requested",
            next_action_quote=request,
        ),
        transcript(request),
    )
    assert reviewed["outcome"] == "no_decision"
    assert (
        routing_outcome(
            SimpleNamespace(
                outcome=reviewed["outcome"],
                response_analysis=reviewed["response_analysis"],
            )
        )
        == "callback"
    )


def test_agent_suggestion_invented_quotes_and_greetings_are_not_evidence():
    turns = transcript("Who is calling and what is this about?")
    reviewed = review_response(
        result("not_interested", "I do not want the service"), turns
    )
    assert (
        reviewed["outcome"] == "no_decision"
        and reviewed["response_analysis"]["evidence_quote"] is None
    )
    reviewed = review_response(
        result(
            "callback",
            "Could I explain the service?",
            next_action="callback_requested",
            next_action_quote="Call tomorrow",
        ),
        turns,
    )
    assert reviewed["outcome"] != "callback"
    greeting = "Please leave a message and I'll call you back."
    assert (
        review_response(result("interested", greeting), transcript(greeting))["outcome"]
        == "voicemail"
    )


@pytest.mark.parametrize("outcome", ["meeting_booked", "transferred", "do_not_call"])
def test_hard_results_remain_protected(outcome):
    assert review_response(result(outcome), transcript("Thanks."))["outcome"] == outcome


def test_router_consumers_do_not_turn_uncertainty_into_lost_or_callback():
    from app.routers.campaigns import RETRY_STATUSES
    from app.services.call_alerts import DEFAULT_OUTCOMES, matches_outcome
    from app.services.contacts import next_status
    from app.services.crm.automations import condition_matches
    from app.services.crm.sync import OUTCOME_TO_KEY

    for outcome in (
        "busy",
        "no_decision",
        "declined_conversation",
        "insufficient_conversation",
    ):
        call = SimpleNamespace(outcome=outcome, response_analysis={}, extracted_data={})
        assert OUTCOME_TO_KEY[outcome] is None
        assert outcome not in DEFAULT_OUTCOMES and outcome not in RETRY_STATUSES
        assert not matches_outcome(call, ["callback"])
        assert not condition_matches(
            SimpleNamespace(kind="outcome", value="callback"), call, {}
        )
        assert next_status("interested", outcome) is None


@pytest.mark.parametrize("available", [True, False])
@pytest.mark.parametrize("reported", ["interested", "not_interested"])
def test_postcall_correction_and_counters_are_idempotent(
    client, monkeypatch, available, reported
):
    from app.database import AsyncSessionLocal
    from app.models.call_log import CallLog
    from app.models.campaign import Campaign
    from app.models.lead import Lead
    from app.services import llm, outbound_call
    from app.services.crm import automations

    cid = uuid.uuid4()
    routed = []

    async def no_charge(*args):
        pass

    async def analyze(*args):
        return (
            result("no_decision", "Is this a solicitation?", "unknown")
            if available
            else None
        )

    async def on_analyzed(db, call):
        routed.append(call.outcome)

    monkeypatch.setattr(outbound_call, "charge_call", no_charge)
    monkeypatch.setattr(llm, "analyze_call", analyze)
    monkeypatch.setattr(automations, "on_analyzed_call", on_analyzed)

    async def run():
        async with AsyncSessionLocal() as db:
            campaign = Campaign(
                name="Review counters", total_qualified=0, total_booked=0
            )
            lead = Lead(name="Review", phone="+14155550101", status="calling")
            db.add_all([campaign, lead])
            await db.flush()
            db.add(
                CallLog(
                    id=cid,
                    campaign_id=campaign.id,
                    lead_id=lead.id,
                    call_type="outbound",
                    livekit_room_name=f"review-{cid}",
                    answered_at=datetime.now(UTC),
                )
            )
            await db.commit()
            await outbound_call.outbound_call_service.update_call_outcome(
                str(cid),
                reported,
                transcript("Is this a solicitation?"),
                None,
                None,
                db,
            )
            campaign_id, lead_id = campaign.id, lead.id
        await outbound_call._analyze(str(cid))
        await outbound_call._analyze(str(cid))
        async with AsyncSessionLocal() as db:
            call, lead, campaign = (
                await db.get(CallLog, cid),
                await db.get(Lead, lead_id),
                await db.get(Campaign, campaign_id),
            )
            return (
                call.outcome,
                lead.status,
                campaign.total_qualified,
                call.response_analysis,
            )

    outcome, status, count, review = asyncio.run(run())
    assert outcome == status == "no_decision" and count == 0
    assert review["version"] == 1 and routed == ["no_decision", "no_decision"]


def test_legacy_calls_are_not_automatically_given_new_outcomes(client, monkeypatch):
    from app.database import AsyncSessionLocal
    from app.models.call_log import CallLog
    from app.services import llm, outbound_call

    async def analyze(*args):
        return result("no_decision", "Is this a solicitation?", "unknown")

    monkeypatch.setattr(llm, "analyze_call", analyze)
    cid = uuid.uuid4()

    async def run():
        async with AsyncSessionLocal() as db:
            db.add(
                CallLog(
                    id=cid,
                    livekit_room_name=f"legacy-{cid}",
                    outcome="not_interested",
                    transcript=transcript("Is this a solicitation?"),
                )
            )
            await db.commit()
        await outbound_call._analyze(str(cid))
        async with AsyncSessionLocal() as db:
            call = await db.get(CallLog, cid)
            assert call.outcome == "not_interested" and call.response_analysis is None
        await outbound_call._analyze(str(cid), force=True)
        async with AsyncSessionLocal() as db:
            assert (await db.get(CallLog, cid)).outcome == "no_decision"

    asyncio.run(run())


def test_permission_to_hear_pitch_is_not_callback_or_information_consent():
    turns = transcript("Sure.")
    for action in ("callback_requested", "send_information"):
        reviewed = review_response(
            result(
                "interested",
                "Sure.",
                "permission_to_speak",
                next_action=action,
                next_action_quote="Sure.",
            ),
            turns,
        )
        assert reviewed["outcome"] == "insufficient_conversation"
        assert reviewed["response_analysis"]["next_action"] == "none_agreed"


def test_agreement_to_callback_offer_is_grounded_in_actual_context():
    turns = [
        {"role": "assistant", "text": "Can I call you tomorrow?"},
        {"role": "user", "text": "Yes, that works."},
    ]
    reviewed = review_response(
        result(
            "no_decision",
            "Yes, that works.",
            "timing",
            next_action="callback_requested",
            next_action_quote="Yes, that works.",
        ),
        turns,
    )
    assert reviewed["response_analysis"]["next_action"] == "callback_requested"


def test_response_and_next_step_filters_are_independent_and_hide_internal_metadata(
    client,
):
    from app.database import AsyncSessionLocal
    from app.models.call_log import CallLog
    from app.models.campaign import Campaign

    org_id = uuid.UUID(client.get("/api/auth/me").json()["org"]["id"])
    cid = uuid.uuid4()
    camp_id = uuid.uuid4()

    async def seed():
        async with AsyncSessionLocal() as db:
            db.add(Campaign(id=camp_id, org_id=org_id, name="Filter review"))
            await db.flush()
            for action in ("callback_requested", "none_agreed"):
                db.add(
                    CallLog(
                        id=cid if action == "callback_requested" else uuid.uuid4(),
                        org_id=org_id,
                        campaign_id=camp_id,
                        livekit_room_name="filter-" + uuid.uuid4().hex,
                        outcome="no_decision",
                        response_analysis={
                            "version": 1,
                            "response": "no_decision",
                            "next_action": action,
                            "_lead_status_before": "calling",
                        },
                    )
                )
            await db.commit()

    asyncio.run(seed())
    response = client.get(
        "/api/calls/",
        params={
            "campaign_id": str(camp_id),
            "outcome": "no_decision",
            "next_action": "callback_requested",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1 and response.json()["items"][0]["id"] == str(
        cid
    )
    assert "_lead_status_before" not in response.json()["items"][0]["response_analysis"]
    assert (
        client.get("/api/calls/", params={"next_action": "invented_action"}).status_code
        == 422
    )


@pytest.mark.parametrize(
    "words",
    [
        "I'm sorry. I don't have time to take the call right now, but thanks.",
        "I'm too busy and cannot talk.",
    ],
)
def test_timing_refusal_is_not_callback_permission_even_when_it_mentions_call(words):
    reviewed = review_response(
        result(
            "callback",
            words,
            "timing",
            next_action="callback_requested",
            next_action_quote=words,
        ),
        transcript(words),
    )
    assert reviewed["outcome"] == "busy"
    assert reviewed["response_analysis"]["next_action"] == "none_agreed"


def test_busy_person_can_accept_an_actual_callback_offer():
    words = "I'm busy but yes, please do."
    turns = [
        {"role": "assistant", "text": "Can I call you tomorrow?"},
        {"role": "user", "text": words},
    ]
    reviewed = review_response(
        result(
            "busy",
            words,
            "timing",
            next_action="callback_requested",
            next_action_quote=words,
        ),
        turns,
    )
    assert reviewed["response_analysis"]["next_action"] == "callback_requested"
