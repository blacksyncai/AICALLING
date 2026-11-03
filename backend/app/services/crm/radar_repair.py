"""TEMPORARY read-only check (remove after it has run): where the Lofty account's leads come from.
Logs counts, sources, date range and the list metadata only."""
import structlog
from sqlalchemy import select

log = structlog.get_logger(__name__)


async def run():
    from app.database import AsyncSessionLocal
    from app.models.account import Organization
    from app.models.crm import CrmConnection
    from app.services.crm import sync

    try:
        async with AsyncSessionLocal() as db:
            conn = (await db.execute(select(CrmConnection).where(CrmConnection.provider == "lofty"))).scalars().first()
            if not conn:
                return
            org = await db.get(Organization, conn.org_id)
            _, http = sync.http_for(conn)
            me = await http.request("GET", "/v1.0/me")
            me = (me or {}).get("data", me) or {}
            rows, meta, offset = [], None, 0
            while offset < 3000:
                res = await http.request("GET", "/v1.0/leads", params={"offset": offset, "limit": 100, "sort": "CreateTime", "desc": "true"})
                meta = meta or (res or {}).get("_metadata")
                page = (res or {}).get("leads") or []
                rows += page
                if len(page) < 100:
                    break
                offset += 100
            sources, assigned, days = {}, {}, {}
            for r in rows:
                sources[str(r.get("source") or "none")[:30]] = sources.get(str(r.get("source") or "none")[:30], 0) + 1
                assigned[str(r.get("assignedUserId"))] = assigned.get(str(r.get("assignedUserId")), 0) + 1
                d = str(r.get("createTime") or "")[:10]
                days[d] = days.get(d, 0) + 1
            log.info("lofty_origin_check", org=(org.name if org else "")[:40], account=conn.account_label[:60] if conn.account_label else "",
                     me_role=me.get("role") or me.get("roleName"), me_id=me.get("userId") or me.get("id"),
                     metadata=meta, leads=len(rows), with_phone=sum(1 for r in rows if r.get("phones")),
                     sources=dict(sorted(sources.items(), key=lambda x: -x[1])[:12]),
                     assigned_users=dict(sorted(assigned.items(), key=lambda x: -x[1])[:6]),
                     created_days=dict(sorted(days.items())[-15:]), oldest=min(days) if days else None)
    except Exception as exc:
        log.warning("lofty_origin_check_failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
