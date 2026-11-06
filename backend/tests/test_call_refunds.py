"""Admins can give back the credits a call used."""

import asyncio
import uuid
from datetime import datetime, timezone

from app.database import AsyncSessionLocal
from app.models.account import Organization
from app.models.call_log import CallLog
from tests.test_phone_numbers import _account


def _call(org_id, milli):
    async def go():
        async with AsyncSessionLocal() as db:
            call = CallLog(id=uuid.uuid4(), org_id=uuid.UUID(org_id), call_type="outbound", to_phone="+16505550100",
                           livekit_room_name="r-" + uuid.uuid4().hex[:6], status="completed", outcome="not_interested",
                           started_at=datetime.now(timezone.utc), duration_seconds=590,
                           credits_used_milli=milli, credits_charged=milli // 1000)
            db.add(call)
            await db.commit()
            return str(call.id)
    return asyncio.run(go())


def _balance(org_id):
    async def go():
        async with AsyncSessionLocal() as db:
            org = await db.get(Organization, uuid.UUID(org_id))
            return (org.credits_balance or 0) * 1000 - (org.credit_carry_milli or 0)
    return asyncio.run(go())


def test_admin_refunds_a_call_exactly_and_only_once(client, make_client):
    org, owner = _account(client, make_client, "Refund Co", credits=50)
    call_id = _call(org["id"], 12330)
    start = _balance(org["id"])

    # Only platform admins can refund.
    assert owner.post(f"/api/admin/calls/{call_id}/refund", json={}).status_code in (401, 403)

    r = client.post(f"/api/admin/calls/{call_id}/refund", json={"credits": 2.33, "note": "Prank caller"})
    assert r.status_code == 200, r.text
    assert r.json()["refunded"] == 2.33 and _balance(org["id"]) == start + 2330
    # Can't give back more than the call cost.
    assert client.post(f"/api/admin/calls/{call_id}/refund", json={"credits": 20}).status_code == 400
    # The rest by default.
    r = client.post(f"/api/admin/calls/{call_id}/refund", json={"note": "Prank caller"})
    assert r.json()["refunded"] == 10.0 and r.json()["call_refunded"] == 12.33
    assert _balance(org["id"]) == start + 12330
    assert client.post(f"/api/admin/calls/{call_id}/refund", json={}).status_code == 400

    calls = owner.get("/api/calls").json()
    items = calls.get("calls") or calls.get("items") or calls
    mine = next(c for c in items if c["id"] == call_id)
    assert mine["credits_refunded"] == 12.33 and mine["refund_note"] == "Prank caller"  # the account sees it
    history = owner.get("/api/billing/transactions").json() if owner.get("/api/billing/transactions").status_code == 200 else None
    if history is not None:
        rows = history.get("transactions") or history.get("items") or []
        assert any(t.get("kind") == "refund" for t in rows)
