"""Keeps every active Plivo number registered for Caller Reputation (AT&T and T-Mobile spam-label
vetting) under the account's approved business Profile. Newly bought or imported numbers are picked up
on the next sweep; the Phone Numbers page shows each number's progress."""
import asyncio
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.billing import PhoneNumber
from app.services import plivo

log = structlog.get_logger(__name__)
SWEEP_SECONDS = 1800
DELAY_SECONDS = 5  # let the purchase settle before registering
_PENDING: set[asyncio.Task] = set()  # keep post-purchase tasks referenced so they can't be dropped mid-run


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def sync_number(db, row: PhoneNumber, profile: str) -> None:
    """Attach the number if it isn't yet, and store its latest per-carrier status."""
    try:
        state = await plivo.reputation_status(row.number)
        if state["status"] in ("NOT_REGISTERED", "FAILED") and profile:
            state = await plivo.enable_reputation(row.number, profile)
            log.info("caller_reputation_submitted", number=row.number, status=state["status"])
    except plivo.PlivoError as exc:
        log.warning("caller_reputation_failed", number=row.number, error=str(exc)[:200])
        return
    row.reputation_status = state["status"]
    row.reputation_detail = state["carriers"]
    row.reputation_checked_at = _now()


async def sweep() -> int:
    if not plivo.ready():
        return 0
    try:
        profile = await plivo.reputation_profile()
    except plivo.PlivoError as exc:
        log.warning("caller_reputation_profile_failed", error=str(exc)[:200])
        return 0
    if not profile:
        log.warning("caller_reputation_no_approved_profile")
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(PhoneNumber).where(PhoneNumber.status == "active",
                                                           PhoneNumber.carrier == "plivo"))).scalars().all()
        for row in rows:
            if row.reputation_status == "ACTIVE" and row.reputation_checked_at and \
                    (_now() - row.reputation_checked_at.replace(tzinfo=row.reputation_checked_at.tzinfo or timezone.utc)).days < 1:
                continue  # active numbers are rechecked daily
            await sync_number(db, row, profile)
        await db.commit()
    return len(rows)


def register_soon(number_id) -> None:
    """Right after a purchase/import: register the new number without waiting for the next sweep."""
    async def go() -> None:
        try:
            await asyncio.sleep(DELAY_SECONDS)
            profile = await plivo.reputation_profile()
            if not profile:
                log.warning("caller_reputation_no_approved_profile", number_id=str(number_id))
            async with AsyncSessionLocal() as db:
                row = await db.get(PhoneNumber, number_id)
                if row and row.carrier == "plivo" and row.status == "active":
                    await sync_number(db, row, profile)
                    await db.commit()
        except Exception as exc:
            log.warning("caller_reputation_register_failed", error=str(exc)[:200])
    task = asyncio.create_task(go())
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)


def start_sweeper() -> asyncio.Task:
    async def loop() -> None:
        while True:
            try:
                await sweep()
            except Exception as exc:
                log.warning("caller_reputation_sweep_error", error=str(exc)[:200])
            await asyncio.sleep(SWEEP_SECONDS)
    return asyncio.create_task(loop())
