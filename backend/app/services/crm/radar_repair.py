"""TEMPORARY one-time fix (remove after it has run): give Compass's unassigned FUB deals an agent so they show
on Gabe's Deals board, then re-read the board to confirm. Logs counts only."""
import structlog
from sqlalchemy import select

log = structlog.get_logger(__name__)


async def run():
    from app.database import AsyncSessionLocal
    from app.models.account import Organization
    from app.models.crm import CrmConnection
    from app.services.crm import fub_deals, sync

    try:
        async with AsyncSessionLocal() as db:
            org = (await db.execute(select(Organization).where(Organization.name.ilike("Compass Multi Family%")))).scalars().first()
            conn = org and (await db.execute(select(CrmConnection).where(
                CrmConnection.org_id == org.id, CrmConnection.provider == "followupboss"))).scalars().first()
            if not conn:
                return
            _, http = sync.http_for(conn)
            fixed = await fub_deals.assign_unowned(http, "9")
            deals = await fub_deals.in_pipeline(http, "9")
            owners = {}
            for d in deals:
                key = ",".join(str(u.get("id")) for u in d.get("users") or [] if isinstance(u, dict)) or "none"
                owners[key] = owners.get(key, 0) + 1
            log.info("fub_deals_assigned", fixed=fixed, deals=len(deals), owners=owners)
    except Exception as exc:
        log.warning("fub_deals_assign_failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
