"""TEMPORARY one-time repair for one account's Radar jobs (remove after it has run).

1. Calls skipped because the name check didn't know the "Hey, this is Robert, right?" opener: re-check them with
   the fixed check and queue the ones that now match, so they're routed like new calls.
2. Pushes that failed because FUB reserves the "First Name" field: clear the half-done marker and retry.
Logs counts only.
"""
import structlog
from sqlalchemy import select

log = structlog.get_logger(__name__)
ORG_PREFIX = "Compass Multi Family"


async def run():
    from app.database import AsyncSessionLocal
    from app.models.account import Organization
    from app.models.call_log import CallLog
    from app.models.lead import Lead
    from app.models.radar_automation import RadarAutomation, RadarExecution, now
    from app.services.crm import verification
    from app.services.crm.automation_schema import RuleSpec

    try:
        async with AsyncSessionLocal() as db:
            org = (await db.execute(select(Organization).where(Organization.name.ilike(f"{ORG_PREFIX}%")))).scalars().first()
            if not org:
                return
            rules = {r.id: r for r in (await db.execute(select(RadarAutomation).where(
                RadarAutomation.org_id == org.id, RadarAutomation.status == "active"))).scalars()}
            jobs = (await db.execute(select(RadarExecution).where(RadarExecution.org_id == org.id, RadarExecution.status.in_(
                ("skipped", "failed"))))).scalars().all()
            requeued = retried = 0
            for j in jobs:
                rule = rules.get(j.automation_id)
                if not rule or rule.version != j.version:
                    continue
                if j.status == "failed" and "reserved by the system" in (j.error or ""):
                    j.result = {k: v for k, v in (j.result or {}).items() if k != "pending_csv_field"}
                    j.status, j.error, j.attempts, j.next_at = "retry", "", 0, now()
                    retried += 1
                    continue
                if j.status != "skipped" or (j.result or {}).get("reason") != "Condition did not match":
                    continue
                spec = RuleSpec.model_validate(j.spec)
                if spec.condition.kind != "verification":
                    continue
                call = await db.get(CallLog, j.call_id)
                lead = await db.get(Lead, call.lead_id) if call and call.lead_id else None
                if not lead:
                    continue
                if verification.classify(call.transcript, lead.name, call.outcome or "")["status"] == spec.condition.value:
                    await verification.record(db, call, lead)
                    j.status, j.error, j.attempts, j.next_at = "queued", "", 0, now()
                    requeued += 1
            await db.commit()
            log.info("radar_repair", requeued=requeued, retried=retried, checked=len(jobs))
    except Exception as exc:
        log.warning("radar_repair_failed", error=str(exc)[:500])
