"""TEMPORARY read-only check of the Compass Radar repair (remove after it has run). Logs counts only."""
from datetime import timedelta

import structlog
from sqlalchemy import select

log = structlog.get_logger(__name__)


async def run():
    import asyncio
    from app.database import AsyncSessionLocal
    from app.models.account import Organization
    from app.models.radar_automation import RadarExecution, now

    await asyncio.sleep(90)  # let the Radar worker take its turn first
    try:
        async with AsyncSessionLocal() as db:
            org = (await db.execute(select(Organization).where(Organization.name.ilike("Compass Multi Family%")))).scalars().first()
            if not org:
                return
            jobs = (await db.execute(select(RadarExecution).where(RadarExecution.org_id == org.id,
                RadarExecution.updated_at >= now() - timedelta(hours=3)))).scalars().all()
            counts, errors, results = {}, [], []
            for j in jobs:
                counts[j.status] = counts.get(j.status, 0) + 1
                if j.error:
                    errors.append(j.error[:160])
                if j.status == "succeeded":
                    results.append({k: v for k, v in (j.result or {}).items() if k in ("stage_id", "unchanged", "reason", "pipeline_id")})
            log.info("radar_repair_check", counts=counts, errors=errors[:10], results=results[:12])
    except Exception as exc:
        log.warning("radar_repair_check_failed", error=str(exc)[:500])
