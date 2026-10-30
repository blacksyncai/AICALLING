"""TEMPORARY read-only check (remove after it has run): Compass Radar pushes since 2026-10-29 15:00 UTC."""
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

log = structlog.get_logger(__name__)
SINCE = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)


async def run():
    from app.database import AsyncSessionLocal
    from app.models.account import Organization
    from app.models.call_log import CallLog
    from app.models.crm import CrmConnection
    from app.models.lead import Lead
    from app.models.radar_automation import RadarAutomation, RadarExecution
    from app.services.crm import fub_deals, sync

    try:
        async with AsyncSessionLocal() as db:
            org = (await db.execute(select(Organization).where(Organization.name.ilike("Compass Multi Family%")))).scalars().first()
            if not org:
                return
            rules = {r.id: r.name for r in (await db.execute(select(RadarAutomation).where(RadarAutomation.org_id == org.id))).scalars()}
            jobs = (await db.execute(select(RadarExecution).where(RadarExecution.org_id == org.id,
                    RadarExecution.created_at >= SINCE).order_by(RadarExecution.created_at))).scalars().all()
            counts, pushed, errors = {}, [], []
            for j in jobs:
                counts[j.status] = counts.get(j.status, 0) + 1
                if j.status == "succeeded":
                    call = await db.get(CallLog, j.call_id)
                    lead = await db.get(Lead, call.lead_id) if call and call.lead_id else None
                    pushed.append({"at": j.updated_at.strftime("%m-%d %H:%M") if j.updated_at else "",
                                   "rule": rules.get(j.automation_id, "")[:50], "name": (lead.name if lead else "")[:40]})
                elif j.status in ("failed", "retry") and j.error:
                    errors.append(j.error[:120])
            calls = (await db.execute(select(CallLog).where(CallLog.org_id == org.id, CallLog.started_at >= SINCE))).scalars().all()
            board = None
            conn = (await db.execute(select(CrmConnection).where(CrmConnection.org_id == org.id,
                    CrmConnection.provider == "followupboss"))).scalars().first()
            if conn:
                _, http = sync.http_for(conn)
                board = (await fub_deals.summary(http, "9", limit=0))["by_stage"]
            log.info("compass_push_check", calls_since=len(calls), jobs=counts, pushed=pushed[:40],
                     errors=errors[:8], board=board)
    except Exception as exc:
        log.warning("compass_push_check_failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
