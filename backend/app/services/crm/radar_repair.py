"""TEMPORARY read-only check (remove after it has run). Logs counts only."""
from datetime import timedelta

import structlog
from sqlalchemy import select

log = structlog.get_logger(__name__)


async def run():
    import asyncio
    from app.database import AsyncSessionLocal
    from app.models.account import Organization
    from app.models.radar_automation import RadarAutomation, RadarExecution, now

    await asyncio.sleep(120)  # let the Radar worker take its turn first
    try:
        async with AsyncSessionLocal() as db:
            org = (await db.execute(select(Organization).where(Organization.name.ilike("Compass Multi Family%")))).scalars().first()
            if not org:
                return
            vm = {r.id for r in (await db.execute(select(RadarAutomation).where(RadarAutomation.org_id == org.id))).scalars()
                  if (r.spec.get("condition") or {}).get("value") == "named_voicemail"}
            jobs = (await db.execute(select(RadarExecution).where(RadarExecution.org_id == org.id))).scalars().all()
            recent, errors = {}, []
            for j in jobs:
                if j.updated_at and j.updated_at >= now() - timedelta(minutes=45):
                    recent[j.status] = recent.get(j.status, 0) + 1
                    if j.error:
                        errors.append(j.error[:160])
            skipped_vm = sum(1 for j in jobs if j.status == "skipped" and j.automation_id in vm)
            log.info("radar_vm_check", recent=recent, errors=errors[:10], skipped_named_vm_jobs=skipped_vm)
    except Exception as exc:
        log.warning("radar_vm_check_failed", error=str(exc)[:500])
