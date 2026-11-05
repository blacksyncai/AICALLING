"""Why a contact said no: tracked as a reason, shown instead of a generic "Not interested"."""

import asyncio
import uuid
from datetime import datetime, timezone

from app.services.call_reasons import from_rules
from app.services.response_review import review_response


def _review(said, outcome="not_interested", **raw):
    t = [{"role": "assistant", "text": "Are you still looking to sell, or have your plans changed?"},
         {"role": "user", "text": said}]
    ra = {"evidence_quote": said, "response_scope": "offer", "certainty": "clear", "next_action": "none_agreed", **raw}
    return review_response({"outcome": outcome, "sentiment": "neutral", "response_analysis": ra}, t)


def test_already_sold_is_tracked_from_the_contacts_words():
    r = _review("My house already sold.")
    assert r["response_analysis"]["reason"] == "already_sold"
    assert r["response_analysis"]["reason_quote"] == "My house already sold."


def test_common_reasons():
    cases = {"We already have a realtor": "working_with_agent", "I'm just the tenant here": "not_owner",
             "We're renting it out now": "renting_out", "We decided not to sell": "not_selling",
             "We bought a house in Texas": "already_bought", "We're under contract": "already_sold"}
    for said, reason in cases.items():
        assert from_rules([said])[0] == reason, said
    assert from_rules(["It didn't sell, we pulled it"]) is None
    assert from_rules(["Nah, not interested"]) is None


def test_the_models_reason_is_kept_only_with_the_contacts_own_words():
    r = _review("The price you'd get me isn't worth it", reason="price_value",
                reason_quote="The price you'd get me isn't worth it")
    assert r["response_analysis"]["reason"] == "price_value"
    r = _review("No thanks", reason="price_value", reason_quote="the agent made this up")
    assert "reason" not in r["response_analysis"]


def test_reasons_are_counted_and_filterable(client):
    from app.database import AsyncSessionLocal
    from app.models.call_log import CallLog

    org_id = uuid.UUID(client.get("/api/auth/me").json()["org"]["id"])

    async def add():
        async with AsyncSessionLocal() as db:
            for reason in ("already_sold", "already_sold", "working_with_agent"):
                db.add(CallLog(org_id=org_id, livekit_room_name="r-" + uuid.uuid4().hex, call_type="outbound",
                               status="completed", outcome="not_interested", started_at=datetime.now(timezone.utc),
                               response_analysis={"version": 1, "reason": reason}))
            await db.commit()
    asyncio.run(add())
    out = client.get("/api/calls/reasons").json()
    counts = {r["reason"]: r["count"] for r in out["reasons"]}
    assert counts["already_sold"] >= 2 and counts["working_with_agent"] >= 1
    items = client.get("/api/calls/", params={"reason": "working_with_agent"}).json()["items"]
    assert items and all(c["response_analysis"]["reason"] == "working_with_agent" for c in items)


def test_garbled_call_with_a_need_is_a_potential_follow_up():
    t = [{"role": "assistant", "text": "Are you still looking around, or leaning towards somewhere else?"},
         {"role": "user", "text": "I kinda need to help. So that's the reason why I'm"},
         {"role": "assistant", "text": "Got it. Just to confirm, are you still looking around the area?"}]
    r = review_response({"outcome": "no_decision", "sentiment": "neutral", "response_analysis": {
        "evidence_quote": "I kinda need to help. So that's the reason why I'm", "response_scope": "permission_to_speak",
        "certainty": "ambiguous", "next_action": "none_agreed"}}, t)
    assert r["outcome"] == "potential_follow_up"
    t2 = [{"role": "assistant", "text": "Still looking?"}, {"role": "user", "text": "No, I'm not looking anymore."}]
    r2 = review_response({"outcome": "no_decision", "sentiment": "neutral", "response_analysis": {
        "evidence_quote": "No, I'm not looking anymore.", "response_scope": "offer", "certainty": "ambiguous",
        "next_action": "none_agreed"}}, t2)
    assert r2["outcome"] != "potential_follow_up"


def test_a_call_result_can_be_corrected_by_hand(client):
    from app.database import AsyncSessionLocal
    from app.models.call_log import CallLog

    org_id = uuid.UUID(client.get("/api/auth/me").json()["org"]["id"])

    async def add():
        async with AsyncSessionLocal() as db:
            c = CallLog(org_id=org_id, livekit_room_name="e-" + uuid.uuid4().hex, call_type="outbound",
                        status="completed", outcome="no_decision", started_at=datetime.now(timezone.utc),
                        response_analysis={"version": 1, "response": "no_decision"})
            db.add(c)
            await db.commit()
            return str(c.id)
    cid = asyncio.run(add())
    r = client.patch(f"/api/calls/{cid}", json={"outcome": "potential_follow_up", "summary": "Audio was muffled."})
    assert r.status_code == 200 and r.json()["outcome"] == "potential_follow_up"
    call = client.get(f"/api/calls/{cid}").json()
    assert call["outcome"] == "potential_follow_up" and call["summary"] == "Audio was muffled."
    assert client.patch(f"/api/calls/{cid}", json={"outcome": "made_up"}).status_code == 422
