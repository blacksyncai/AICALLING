"""Admin: hot calls across every account."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from app.database import AsyncSessionLocal
from app.models.call_log import CallLog
from app.models.lead import Lead
from tests.test_phone_numbers import _account


def _add(org_id, outcome, name, company="", fields=None, call_type="outbound", days_ago=0, **ra):
    async def go():
        async with AsyncSessionLocal() as db:
            lead = Lead(id=uuid.uuid4(), org_id=uuid.UUID(org_id), name=name, phone="+14155550123",
                        company=company, custom_fields=fields)
            db.add(lead)
            call = CallLog(id=uuid.uuid4(), org_id=uuid.UUID(org_id), lead_id=lead.id, call_type=call_type,
                           to_phone="+14155550123", livekit_room_name=f"hot-{uuid.uuid4().hex[:8]}", status="completed",
                           outcome=outcome, summary=f"{name} call", response_analysis=ra or None,
                           started_at=datetime.now(timezone.utc) - timedelta(days=days_ago))
            db.add(call)
            await db.commit()
            return str(call.id)
    return asyncio.run(go())


def test_hot_calls_across_accounts_with_name_company_and_quote(client, make_client):
    a, owner_a = _account(client, make_client, "Hot A")
    b, _ = _account(client, make_client, "Hot B")
    booked = _add(a["id"], "meeting_booked", "Dana Cole", company="Cole Realty",
                  evidence_quote="Tuesday at 2 works.")
    cb = _add(b["id"], "callback", "Lee Park", fields={"property_address": "12 Oak St"},
              next_action_quote="Call me back Friday morning.")
    _add(b["id"], "not_interested", "Nope Person")             # no intent
    _add(a["id"], "interested", "Old Lead", days_ago=20)       # outside the window
    _add(a["id"], "interested", "Browser test", call_type="web")  # a test call

    assert owner_a.get("/api/admin/hot-calls").status_code in (401, 403)
    data = client.get("/api/admin/hot-calls?days=7").json()
    by_id = {i["id"]: i for i in data["items"]}
    assert by_id[booked]["name"] == "Dana Cole" and by_id[booked]["company"] == "Cole Realty"
    assert by_id[booked]["account"]["name"] == "Hot A" and by_id[booked]["quote"] == "Tuesday at 2 works."
    assert by_id[cb]["company"] == "12 Oak St" and by_id[cb]["quote"] == "Call me back Friday morning."
    names = {i["name"] for i in data["items"]}
    assert not names & {"Nope Person", "Old Lead", "Browser test"}

    only_b = client.get(f"/api/admin/hot-calls?org_id={b['id']}&group=callback").json()["items"]
    assert [i["id"] for i in only_b] == [cb]
    assert any(i["name"] == "Browser test" for i in client.get("/api/admin/hot-calls?include_tests=true").json()["items"])
