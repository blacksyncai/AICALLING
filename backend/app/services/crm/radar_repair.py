"""TEMPORARY read-only check (remove after it has run): who the Compass FUB deals belong to. Logs counts/ids only."""
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
            me = await http.request("GET", "/v1/me")
            deals = await fub_deals.in_pipeline(http, "9")
            sample = deals[:3]
            people = []
            for d in sample:
                for p in d.get("people") or []:
                    if isinstance(p, dict) and p.get("id"):
                        row = await http.request("GET", f"/v1/people/{int(p['id'])}", params={"fields": "id,assignedUserId,assignedTo"})
                        people.append({"assignedUserId": row.get("assignedUserId"), "assignedTo": row.get("assignedTo")})
            users = {}
            for d in deals:
                key = ",".join(str(u.get("id")) for u in d.get("users") or [] if isinstance(u, dict)) or "none"
                users[key] = users.get(key, 0) + 1
            log.info("fub_deal_owner_check", me={"id": me.get("id"), "name": me.get("name"), "role": me.get("role")},
                     account=conn.account_label, deals=len(deals), deal_users=users,
                     sample_keys=sorted(sample[0].keys()) if sample else [], sample_people=people)
    except Exception as exc:
        log.warning("fub_deal_owner_check_failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
