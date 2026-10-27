"""A contact's board stage follows its calls: clear results stick, no-answers never undo them."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from tests.test_activity import _add, _call, _owner


def test_next_status_rules():
    from app.services.contacts import next_status

    assert next_status("new", "voicemail") == "voicemail"
    assert next_status("callback", "voicemail") is None          # a later voicemail doesn't undo "call me back"
    assert next_status("interested", "no_answer") is None
    assert next_status("completed", "callback") == "callback"     # the reviewed outcome moves the contact
    assert next_status("callback", "completed") is None           # a vague talk doesn't replace a clear one
    assert next_status("voicemail", "completed") == "completed"
    assert next_status("interested", "not_interested") == "not_interested"  # a clear later answer wins
    assert next_status("meeting_booked", "interested") is None
    assert next_status("interested", "meeting_booked") == "meeting_booked"
    assert next_status("not_interested", "interested") == "interested"
    assert next_status("new", None) is None


def _lead_status(lead_id):
    from app.database import AsyncSessionLocal
    from app.models.lead import Lead

    async def go():
        async with AsyncSessionLocal() as db:
            return (await db.get(Lead, uuid.UUID(lead_id))).status

    return asyncio.run(go())


def test_calls_and_repair_move_contacts_to_the_right_stage(client, make_client):
    from app.services.outbound_call import outbound_call_service, repair_contact_statuses

    owner, org_id, agent, _ = _owner(client, make_client, name="Stages Co")
    agent_id = uuid.UUID(agent["id"])
    phone = lambda: f"+1415558{uuid.uuid4().int % 10000:04d}"
    a = owner.post("/api/contacts", json={"name": "Ann Callback", "phone": phone()}).json()["id"]
    b = owner.post("/api/contacts", json={"name": "Bo Booked", "phone": phone()}).json()["id"]
    c = owner.post("/api/contacts", json={"name": "Cy Manual", "phone": phone()}).json()["id"]

    # Ann said "call me back", then a later call hit voicemail: she stays on Follow-up.
    now = datetime.now(timezone.utc)
    first = _call(org_id, agent_id, now - timedelta(minutes=30), outcome="callback")
    first.lead_id = uuid.UUID(a)
    later = _call(org_id, agent_id, now - timedelta(minutes=5), outcome=None, answered=False)
    later.status, later.lead_id = "in_progress", uuid.UUID(a)
    _add(first, later)
    owner.patch(f"/api/contacts/{a}", json={"status": "callback"})

    async def report():
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await outbound_call_service.update_call_outcome(call_log_id=str(later.id), outcome="voicemail",
                                                            transcript=[], meeting_link=None,
                                                            qualification_score=None, db=db)
    asyncio.run(report())
    assert _lead_status(a) == "callback"

    # Old data: Bo's calls say meeting booked but his status was left at "completed" (the old bug);
    # Cy was moved to Not interested by hand and stays there.
    for lead, outcomes in ((b, ["meeting_booked", "voicemail"]), (c, ["interested"])):
        rows = []
        for i, o in enumerate(outcomes):
            r = _call(org_id, agent_id, now - timedelta(hours=3 - i), outcome=o)
            r.lead_id = uuid.UUID(lead)
            rows.append(r)
        _add(*rows)
    owner.patch(f"/api/contacts/{b}", json={"status": "completed"})
    owner.patch(f"/api/contacts/{c}", json={"status": "not_interested"})
    asyncio.run(repair_contact_statuses())
    assert _lead_status(b) == "meeting_booked"
    assert _lead_status(c) == "not_interested"
    assert asyncio.run(repair_contact_statuses()) == 0  # nothing left to fix

    # The board can ask for a whole column (several statuses) at once.
    col = owner.get("/api/contacts", params={"status": "meeting_booked,transferred"}).json()
    assert [i["name"] for i in col["items"]] == ["Bo Booked"]
