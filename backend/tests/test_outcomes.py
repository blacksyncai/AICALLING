import asyncio
import uuid

from app.agent.runtime import person_answered, reconcile_outcome
from app.database import AsyncSessionLocal
from app.models.call_log import CallLog

TALKED = [{"role": "assistant", "text": "Hey there, this is Alex from Acme, did I catch you at an okay time?"},
          {"role": "user", "text": "Yeah. Sure."},
          {"role": "assistant", "text": "Great, thanks!"},
          {"role": "user", "text": "Can you say that again?"}]
VOICEMAIL = [{"role": "assistant", "text": "Hi, this is Alex"},
             {"role": "user", "text": "Hi, you've reached Sam. Please leave a message after the tone."}]


def test_person_answered():
    assert person_answered(TALKED)
    assert not person_answered(VOICEMAIL)
    assert not person_answered([{"role": "assistant", "text": "Hello?"}])


def test_reconcile_never_no_answer_when_they_talked():
    assert reconcile_outcome("no_answer", TALKED) == "completed"
    assert reconcile_outcome("voicemail", TALKED) == "completed"
    assert reconcile_outcome("voicemail", VOICEMAIL) == "voicemail"
    assert reconcile_outcome("interested", TALKED) == "interested"


def test_repair_existing_mislabeled_calls(client, monkeypatch):
    from app.services import llm, outbound_call

    async def fake_analyze(transcript, fields, criteria):
        return {"summary": "They asked to repeat.", "outcome": "no_answer", "sentiment": "neutral", "extracted": {}}

    monkeypatch.setattr(llm, "analyze_call", fake_analyze)
    cid = uuid.uuid4()

    async def run():
        async with AsyncSessionLocal() as db:
            db.add(CallLog(id=cid, call_type="outbound", status="completed", outcome="no_answer", transcript=TALKED,
                           to_phone="+14155550100", duration_seconds=54, livekit_room_name=f"call-{cid}"))
            await db.commit()
        n = await outbound_call.fix_mislabeled_outcomes()
        async with AsyncSessionLocal() as db:
            return n, await db.get(CallLog, cid)

    n, call = asyncio.run(run())
    assert n >= 1 and call.outcome == "completed" and call.summary == "They asked to repeat."
