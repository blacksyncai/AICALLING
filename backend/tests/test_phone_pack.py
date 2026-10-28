"""Fresh Number Pack: 10 numbers per pack on the plan, bought in the chosen area code, swapped monthly."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_billing import _account, stripe  # noqa: F401  (fixture)
from tests.test_entitlements import _subscribe


@pytest.fixture
def carrier(monkeypatch):
    """Fake number inventory: search returns fresh numbers in the asked area code; buy/release are local."""
    from app.models.billing import PhoneNumber
    from app.services import telephony

    state = {"bought": [], "released": [], "counter": 1000, "short": set()}

    async def search_available(area_code="", contains="", country="US", limit=20, carrier=None):
        if area_code in state["short"]:
            return [{"number": f"+1{area_code}555{state['counter'] + 1:04d}"}]  # only one left there
        code = area_code or "415"
        out = []
        for _ in range(limit):
            state["counter"] += 1
            out.append({"number": f"+1{code}555{state['counter']:04d}"})
        return out

    async def purchase(db, org_id, number, label="", *, carrier=None):
        row = PhoneNumber(id=uuid.uuid4(), org_id=org_id, number=number, label=label, source="fake", status="active")
        db.add(row)
        await db.commit()
        state["bought"].append(number)
        return row

    async def noop(*a, **k):
        return None

    real_release = telephony.release

    async def release(db, row, *, return_to_twilio, sync_media=True):
        state["released"].append(row.number)
        await real_release(db, row, return_to_twilio=return_to_twilio, sync_media=False)

    monkeypatch.setattr(telephony, "search_available", search_available)
    monkeypatch.setattr(telephony, "purchase", purchase)
    monkeypatch.setattr(telephony, "release", release)
    monkeypatch.setattr(telephony, "_livekit_numbers", noop)
    return state


def _run(coro):
    return asyncio.run(coro)


def test_buy_refresh_and_remove_a_pack(client, make_client, stripe, carrier):  # noqa: F811
    org, c = _account(client, make_client, "Pack Co")
    info = c.get("/api/billing/addons/phone-packs").json()
    assert info["amount_cents"] == 2500 and info["numbers"] == [] and info["packs"] == 0 and info["available"]
    # Needs a plan first.
    assert c.post("/api/billing/addons/phone-packs", json={"quantity": 1, "confirm": True}).status_code == 409
    _subscribe(client, c, stripe, "solo")
    assert c.post("/api/billing/addons/phone-packs", json={"quantity": 1}).status_code == 400  # needs confirm

    out = c.post("/api/billing/addons/phone-packs", json={"quantity": 1, "area_code": "512", "confirm": True}).json()
    assert out["packs"] == 1 and len(out["numbers"]) == 10
    assert all(n["number"].startswith("+1512") and n["pack_refresh_at"] for n in out["numbers"])
    assert stripe.slot_calls[-1] == (1, "error_if_incomplete")  # charged now, refused if the card fails
    # Pack numbers never count toward the plan's included numbers or the $3.50 add-on.
    nums = c.get("/api/phone-numbers").json()
    assert nums["pricing"]["active"] == 0

    # A campaign rotating through two pack numbers and an agent calling from one.
    agent = c.post("/api/agents/", json={"template": "sales_sdr"}).json()
    old, other = out["numbers"][0]["number"], out["numbers"][1]["number"]
    camp = c.post("/api/campaigns/", json={"name": "Rotate", "agent_id": agent["id"]}).json()
    from app.database import AsyncSessionLocal
    from app.models.agent import Agent
    from app.models.billing import PhoneNumber
    from app.models.campaign import Campaign
    from app.services import phone_pack

    async def setup():
        async with AsyncSessionLocal() as db:
            cp = await db.get(Campaign, uuid.UUID(camp["id"]))
            cp.number_rotation_enabled, cp.caller_number_pool = True, [old, other]
            (await db.get(Agent, uuid.UUID(agent["id"]))).caller_number = old
            row = (await db.execute(__import__("sqlalchemy").select(PhoneNumber).where(PhoneNumber.number == old))).scalar_one()
            row.pack_refresh_at = datetime.now(timezone.utc) - timedelta(minutes=1)  # its month is up
            await db.commit()

    _run(setup())

    async def refresh():
        async with AsyncSessionLocal() as db:
            return await phone_pack.refresh_due(db)

    assert _run(refresh()) == 1
    assert carrier["released"] == [old]
    new = carrier["bought"][-1]
    assert new.startswith("+1512") and new != old

    async def check():
        async with AsyncSessionLocal() as db:
            cp = await db.get(Campaign, uuid.UUID(camp["id"]))
            ag = await db.get(Agent, uuid.UUID(agent["id"]))
            return cp.caller_number_pool, ag.caller_number

    pool, caller = _run(check())
    assert pool == [new, other] and caller == new  # the fresh number took the old one's place
    assert len(c.get("/api/billing/addons/phone-packs").json()["numbers"]) == 10

    # Removing the pack releases its numbers and takes them out of rotations.
    out = c.post("/api/billing/addons/phone-packs", json={"quantity": 0, "confirm": True}).json()
    assert out["packs"] == 0 and out["numbers"] == []
    assert stripe.slot_calls[-1] == (0, None)
    assert len(carrier["released"]) == 11
    assert _run(check())[0] == []


def test_short_area_code_fills_from_elsewhere_and_card_failure_buys_nothing(client, make_client, stripe, carrier):  # noqa: F811
    org, c = _account(client, make_client, "Pack Short Co")
    _subscribe(client, c, stripe, "solo")
    stripe.charge_status = "failed"
    r = c.post("/api/billing/addons/phone-packs", json={"quantity": 1, "area_code": "907", "confirm": True})
    assert r.status_code == 402 and carrier["bought"] == []
    stripe.charge_status = "succeeded"
    carrier["short"].add("907")
    out = c.post("/api/billing/addons/phone-packs", json={"quantity": 1, "area_code": "907", "confirm": True}).json()
    assert len(out["numbers"]) == 10
    assert sum(n["number"].startswith("+1907") for n in out["numbers"]) == 1  # the rest came from other area codes
