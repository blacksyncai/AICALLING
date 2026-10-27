"""TEMPORARY read-only count for one account's Radar rules (remove after use). Logs counts only."""
from collections import Counter

import structlog
from sqlalchemy import select

log = structlog.get_logger(__name__)
ORG_PREFIX = "Compass Multi Family"


async def run():
    from app.database import AsyncSessionLocal
    from app.models.account import Organization
    from app.models.call_log import CallLog
    from app.models.lead import Lead
    from app.models.radar_automation import RadarAutomation, RadarExecution
    from app.services.crm import verification

    try:
        async with AsyncSessionLocal() as db:
            org = (await db.execute(select(Organization).where(Organization.name.ilike(f"{ORG_PREFIX}%")))).scalars().first()
            if not org:
                return
            rules = {r.id: r for r in (await db.execute(select(RadarAutomation).where(
                RadarAutomation.org_id == org.id, RadarAutomation.status == "active"))).scalars()}
            jobs = (await db.execute(select(RadarExecution).where(RadarExecution.org_id == org.id))).scalars().all()
            calls = {j.call_id for j in jobs}
            now_status, outcomes = Counter(), Counter()
            routed = {j.call_id for j in jobs if j.status == "succeeded"}
            for cid in calls:
                call = await db.get(CallLog, cid)
                lead = await db.get(Lead, call.lead_id) if call and call.lead_id else None
                if not lead:
                    continue
                v = verification.classify(call.transcript, lead.name, call.outcome or "")["status"]
                now_status[v] += 1
                if v == "name_confirmed":
                    outcomes[call.outcome] += 1
            failed_reserved = sum(1 for j in jobs if j.status == "failed" and "reserved by the system" in (j.error or ""))
            log.info("radar_count", calls=len(calls), by_status=dict(now_status), confirmed_outcomes=dict(outcomes),
                     already_routed=len(routed), failed_reserved=failed_reserved, rules=len(rules),
                     first_call=min((j.created_at for j in jobs), default=None))
    except Exception as exc:
        log.warning("radar_count_failed", error=str(exc)[:500])
