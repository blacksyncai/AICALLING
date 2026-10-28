"""TEMPORARY read-only check (remove after it has run): Compass's FUB deal board, counts per stage."""
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
            out = await fub_deals.summary(http, "9", limit=0)
            log.info("fub_board_check", pipeline=out["pipeline"]["name"], total=out["total_active_deals"], by_stage=out["by_stage"])
    except Exception as exc:
        log.warning("fub_board_check_failed", error=str(exc)[:500])
