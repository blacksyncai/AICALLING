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


def test_worker_voicemail_marker_and_strict_greeting():
    from app.agent.runtime import is_voicemail_greeting

    marked = TALKED + [{"role": "tool", "tool": "voicemail", "args": {"action": "hung_up"}}]
    assert not person_answered(marked) and reconcile_outcome("voicemail", marked) == "voicemail"
    assert is_voicemail_greeting("Hi you've reached Sam, please leave a message after the beep")
    assert not is_voicemail_greeting("Sure, I can get back to you tomorrow")


def test_agent_voicemail_settings(client):
    a = client.post("/api/agents", json={"template": "blank"}).json()
    assert a["voicemail_action"] == "hang_up"
    r = client.patch(f"/api/agents/{a['id']}", json={"voicemail_action": "leave_message", "voicemail_message": "Hi {{name}}"})
    assert r.status_code == 200 and r.json()["voicemail_action"] == "leave_message"
    assert client.patch(f"/api/agents/{a['id']}", json={"voicemail_action": "scream"}).status_code == 422


def test_personal_greeting_is_voicemail_not_callback():
    from app.agent.runtime import looks_like_personal_greeting

    greet = "Hey, it's Hamza, I can't talk right now, I'll call you back or just text me"
    assert looks_like_personal_greeting(greet)
    assert not looks_like_personal_greeting("Hello?")
    assert not looks_like_personal_greeting("I'll call you back")  # too short to be a recording
    t = [{"role": "assistant", "text": "Hey, welcome to BlackSync AI!"}, {"role": "user", "text": greet}]
    assert not person_answered(t) and reconcile_outcome("voicemail", t) == "voicemail"


def test_reanalyze_can_fix_an_analyzer_outcome(client, monkeypatch):
    from app.services import llm, outbound_call

    async def fake(transcript, fields, criteria):
        return {"summary": "Voicemail greeting.", "outcome": "voicemail", "sentiment": "neutral", "extracted": {}}

    monkeypatch.setattr(llm, "analyze_call", fake)
    cid = uuid.uuid4()
    greet = [{"role": "user", "text": "Hey, it's Hamza, I can't talk right now, I'll call you back or text me"}]

    async def run():
        async with AsyncSessionLocal() as db:
            db.add(CallLog(id=cid, call_type="outbound", status="completed", outcome="callback", transcript=greet,
                           to_phone="+14155550101", duration_seconds=35, livekit_room_name=f"call-{cid}"))
            await db.commit()
        await outbound_call._analyze(str(cid))          # automatic: keeps the earlier label
        async with AsyncSessionLocal() as db:
            before = (await db.get(CallLog, cid)).outcome
        await outbound_call._analyze(str(cid), force=True)  # Re-analyze button
        async with AsyncSessionLocal() as db:
            return before, (await db.get(CallLog, cid)).outcome

    assert asyncio.run(run()) == ("callback", "voicemail")
