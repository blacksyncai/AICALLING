"""Fresh Number Pack: 10 local numbers per pack, each swapped for a new one every 30 days.

Spreading call volume over many numbers, and retiring each before it wears out, keeps caller IDs from being
labelled spam. Packs are billed as a quantity on the plan subscription (catalog.PHONE_PACK); this module keeps
the numbers in line with what's paid for:
- A pack is 10 number credits: the customer picks each number (credits(), used by the number purchase), and
  reconcile() releases extras when a pack is removed or the plan ends.
- refresh_due(): swaps every pack number whose month is up for a fresh one in the same area code. The new number
  takes the old one's place in campaign rotations, agent caller IDs and the default, then the old one is released.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.billing import BillingSubscription, PhoneNumber
from app.models.campaign import Campaign
from app.services import telephony
from app.services.billing import catalog

log = structlog.get_logger(__name__)
LIVE = ("active", "trialing", "past_due")
PER_PACK = catalog.PHONE_PACK["numbers"]
LABEL = "Fresh pack"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=timezone.utc) if d and d.tzinfo is None else d


async def pack_numbers(db: AsyncSession, org_id: uuid.UUID) -> list[PhoneNumber]:
    return list((await db.execute(select(PhoneNumber).where(
        PhoneNumber.org_id == org_id, PhoneNumber.status == "active", PhoneNumber.pack_refresh_at.is_not(None),
    ).order_by(PhoneNumber.created_at))).scalars().all())


async def wanted(db: AsyncSession, org_id: uuid.UUID) -> int:
    """How many pack numbers this account is paying for right now."""
    row = await db.get(BillingSubscription, org_id)
    if row is None or row.status not in LIVE:
        return 0
    return (row.phone_packs or 0) * PER_PACK


async def _candidates(area_code: str, need: int, taken: set[str]) -> list[str]:
    """Numbers to buy: the chosen area code first, then any US number if that area code runs short."""
    out: list[str] = []
    for code in ([area_code] if area_code else []) + [""]:
        if len(out) >= need:
            break
        try:
            found = await telephony.search_available(code, limit=max(20, need * 2))
        except (telephony.TelephonyError, ValueError) as exc:
            log.warning("phone_pack_search_failed", area_code=code, error=str(exc)[:200])
            continue
        out += [n["number"] for n in found if n.get("number") and n["number"] not in taken and n["number"] not in out]
    return out[:need]


async def _buy(db: AsyncSession, org_id: uuid.UUID, area_code: str, need: int) -> list[PhoneNumber]:
    bought: list[PhoneNumber] = []
    taken = {n.number for n in await telephony.active_numbers(db, org_id)}
    for number in await _candidates(area_code, need, taken):
        try:
            row = await telephony.purchase(db, org_id, number, LABEL)
        except Exception as exc:  # one unavailable number mustn't stop the rest
            log.warning("phone_pack_buy_failed", org_id=str(org_id), error=str(exc)[:200])
            continue
        row.pack_refresh_at = _now() + timedelta(days=catalog.PHONE_PACK["refresh_days"])
        row.pack_area_code = area_code or number[2:5]
        await db.commit()
        bought.append(row)
    return bought


async def _swap_references(db: AsyncSession, old: PhoneNumber, new_number: str) -> None:
    """Put new_number wherever old was in use: campaign rotations, agent caller IDs, the account default."""
    campaigns = (await db.execute(select(Campaign).where(Campaign.org_id == old.org_id))).scalars().all()
    for c in campaigns:
        pool = list(c.caller_number_pool or [])
        if old.number in pool:
            c.caller_number_pool = [new_number if n == old.number else n for n in pool]
    await db.execute(update(Agent).where(Agent.org_id == old.org_id, Agent.caller_number == old.number)
                     .values(caller_number=new_number))
    new_row = (await db.execute(select(PhoneNumber).where(PhoneNumber.number == new_number))).scalar_one_or_none()
    if new_row is not None:
        await db.execute(update(Campaign).where(Campaign.org_id == old.org_id, Campaign.phone_number_id == old.id)
                         .values(phone_number_id=new_row.id))
    if old.is_default:
        new = (await db.execute(select(PhoneNumber).where(PhoneNumber.number == new_number))).scalar_one()
        await db.execute(update(PhoneNumber).where(PhoneNumber.org_id == old.org_id).values(is_default=None))
        new.is_default = True
        old.is_default = None
    await db.flush()


async def _retire(db: AsyncSession, row: PhoneNumber) -> None:
    """Take a pack number out of every rotation and give it back to the carrier (so it stops costing money)."""
    for c in (await db.execute(select(Campaign).where(Campaign.org_id == row.org_id))).scalars().all():
        if row.number in (c.caller_number_pool or []):
            c.caller_number_pool = [n for n in c.caller_number_pool if n != row.number]
            c.caller_rotation_cursor = 0
    await telephony.release(db, row, return_to_twilio=True)


async def credits(db: AsyncSession, org_id: uuid.UUID) -> dict:
    """Pack number credits: how many the packs give, how many are in use, how many are left to pick."""
    total, used = await wanted(db, org_id), len(await pack_numbers(db, org_id))
    return {"total": total, "used": used, "open": max(0, total - used)}


def mark(row: PhoneNumber) -> None:
    """Make a just-bought number a pack number: covered by the pack, swapped for a fresh one each month."""
    row.pack_refresh_at = _now() + timedelta(days=catalog.PHONE_PACK["refresh_days"])
    row.pack_area_code = row.number[2:5]


async def reconcile(db: AsyncSession, org_id: uuid.UUID, area_code: str = "") -> dict:
    """Release pack numbers beyond what the account pays for (a pack removed, or the plan ended).
    Numbers are never bought here: the customer picks them with their credits."""
    want = await wanted(db, org_id)
    have = await pack_numbers(db, org_id)
    removed = 0
    if len(have) > want:
        for row in sorted(have, key=lambda n: _aware(n.created_at) or _now(), reverse=True)[:len(have) - want]:
            await _retire(db, row)
            removed += 1
        log.info("phone_pack_reconciled", org_id=str(org_id), wanted=want, removed=removed)
    return {"wanted": want, "added": 0, "removed": removed}


async def refresh_due(db: AsyncSession, now: datetime | None = None) -> int:
    """Swap every pack number whose month is up for a fresh one. Returns how many were swapped."""
    now = now or _now()
    due = (await db.execute(select(PhoneNumber).where(
        PhoneNumber.status == "active", PhoneNumber.pack_refresh_at.is_not(None), PhoneNumber.pack_refresh_at <= now,
    ).order_by(PhoneNumber.pack_refresh_at).limit(50))).scalars().all()
    swapped = 0
    for old in due:
        if await wanted(db, old.org_id) == 0:
            continue  # reconcile() releases numbers that are no longer paid for
        fresh = await _buy(db, old.org_id, old.pack_area_code or old.number[2:5], 1)
        if not fresh:
            # Couldn't get a replacement right now: keep the old one working and try again in a day.
            old.pack_refresh_at = now + timedelta(days=1)
            await db.commit()
            continue
        await _swap_references(db, old, fresh[0].number)
        await db.commit()
        await _retire(db, old)
        swapped += 1
        log.info("phone_pack_number_refreshed", org_id=str(old.org_id), old=old.number[-4:], new=fresh[0].number[-4:])
    return swapped


# ── Fresh number every month (any purchased number, not just packs) ─────────

AUTO_LABEL_NOTE = "fresh monthly"


def renewal_eve(row: PhoneNumber, now: datetime | None = None) -> datetime:
    """Noon UTC the day before the number's next monthly renewal (its purchase day each month)."""
    from app.services.billing.manual_plans import add_months

    now = now or _now()
    bought = (_aware(row.created_at) or now).date()
    n = 1
    while add_months(bought, n) - timedelta(days=1) <= now.date():
        n += 1
    eve = add_months(bought, n) - timedelta(days=1)
    return datetime(eve.year, eve.month, eve.day, 12, tzinfo=timezone.utc)


def can_auto_refresh(row: PhoneNumber) -> str | None:
    """Why this number can't be swapped each month (None when it can)."""
    if row.source != "purchased" or not row.provider_sid:
        return "Only numbers bought through BlackSync can be swapped automatically."
    if row.carrier not in ("plivo", None, "twilio"):
        return "This carrier's numbers can't be swapped automatically yet."
    if row.pack_refresh_at is not None:
        return "Fresh Number Pack numbers are already swapped every month."
    if row.inbound_campaign_id:
        return "This number answers an inbound campaign, so its number has to stay the same."
    return None


async def set_auto_refresh(db: AsyncSession, row: PhoneNumber, on: bool) -> None:
    if on:
        reason = can_auto_refresh(row)
        if reason:
            raise ValueError(reason)
        row.auto_refresh, row.auto_refresh_at = True, renewal_eve(row)
    else:
        row.auto_refresh, row.auto_refresh_at = None, None
    await db.flush()


async def refresh_auto_due(db: AsyncSession, now: datetime | None = None) -> int:
    """Swap every "fresh number every month" number whose renewal is tomorrow: buy a new one in the same area code
    on the same carrier, move it into the old one's place, then release the old one so it isn't renewed."""
    now = now or _now()
    due = (await db.execute(select(PhoneNumber).where(
        PhoneNumber.status == "active", PhoneNumber.auto_refresh.is_(True), PhoneNumber.auto_refresh_at <= now,
    ).order_by(PhoneNumber.auto_refresh_at).limit(50))).scalars().all()
    swapped = 0
    for old_id in [r.id for r in due]:
        old = await db.get(PhoneNumber, old_id)
        if old is None:
            continue
        if can_auto_refresh(old):
            old.auto_refresh, old.auto_refresh_at = None, None
            await db.commit()
            continue
        org_id, number, label, carrier = old.org_id, old.number, old.label or "", old.carrier or "twilio"
        new = None
        taken = {n.number for n in await telephony.active_numbers(db, org_id)}
        for code in (number[2:5], ""):
            try:
                found = await telephony.search_available(code, carrier=carrier)
            except Exception as exc:
                log.warning("auto_refresh_search_failed", area_code=code, error=str(exc)[:200])
                continue
            for candidate in [n["number"] for n in found if n.get("number") and n["number"] not in taken][:5]:
                try:
                    new = await telephony.purchase(db, org_id, candidate, label, carrier=carrier)
                    break
                except Exception as exc:
                    await db.rollback()  # that number was gone: try the next one
                    log.warning("auto_refresh_buy_failed", org_id=str(org_id), error=str(exc)[:200])
            if new:
                break
        old = await db.get(PhoneNumber, old_id)
        if new is None:
            # No replacement right now: keep the old number working (it renews) and try again next month.
            old.auto_refresh_at = renewal_eve(old, now + timedelta(days=2))
            await db.commit()
            log.warning("auto_refresh_no_replacement", org_id=str(org_id), number=number[-4:])
            continue
        new.auto_refresh, new.auto_refresh_at = True, renewal_eve(new, now)
        await _swap_references(db, old, new.number)
        await db.commit()
        if new.carrier == "plivo":
            try:
                from app.services.billing import settings_store
                from app.services import plivo

                if await settings_store.get(db, "plivo_inbound_routing"):
                    await plivo.route_inbound(new.number)  # callbacks to the new number reach BlackSync
            except Exception as exc:
                log.warning("auto_refresh_inbound_routing_failed", number=new.number[-4:], error=str(exc)[:200])
        try:
            await _retire(db, old)
        except Exception as exc:
            # The new number is already in place; never buy yet another one for this number.
            await db.rollback()
            old = await db.get(PhoneNumber, old_id)
            if old is not None:
                old.auto_refresh, old.auto_refresh_at = None, None
                await db.commit()
            log.error("auto_refresh_release_failed", org_id=str(org_id), number=number[-4:], error=str(exc)[:200])
        swapped += 1
        log.info("auto_refresh_number_swapped", org_id=str(org_id), old=number[-4:], new=new.number[-4:])
    return swapped


async def tick() -> None:
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        orgs = set((await db.execute(select(BillingSubscription.org_id).where(
            BillingSubscription.phone_packs > 0))).scalars().all())
        orgs |= set((await db.execute(select(PhoneNumber.org_id).where(
            PhoneNumber.status == "active", PhoneNumber.pack_refresh_at.is_not(None)))).scalars().all())
        for org_id in orgs:
            try:
                await reconcile(db, org_id)
            except Exception as exc:
                await db.rollback()
                log.warning("phone_pack_reconcile_failed", org_id=str(org_id), error=str(exc)[:200])
        await refresh_due(db)
        await refresh_auto_due(db)


def start_worker() -> asyncio.Task:
    async def loop():
        while True:
            try:
                await tick()
            except Exception as exc:
                log.warning("phone_pack_worker_failed", error=str(exc)[:200])
            await asyncio.sleep(3600)

    return asyncio.create_task(loop())
