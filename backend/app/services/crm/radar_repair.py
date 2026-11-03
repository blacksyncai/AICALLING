"""TEMPORARY read-only check (remove after it has run): Compass FUB ponds — FUB's own totals vs what Radar reads.
Logs counts only."""
import time

import structlog
from sqlalchemy import select

log = structlog.get_logger(__name__)


async def run():
    from app.database import AsyncSessionLocal
    from app.models.account import Organization
    from app.models.crm import CrmConnection, CrmScan
    from app.services.crm import sync
    from app.services.crm.automation_resources import fub_collection
    from app.services.crm.providers import PROVIDERS

    try:
        async with AsyncSessionLocal() as db:
            org = (await db.execute(select(Organization).where(Organization.name.ilike("Compass Multi Family%")))).scalars().first()
            conn = org and (await db.execute(select(CrmConnection).where(
                CrmConnection.org_id == org.id, CrmConnection.provider == "followupboss"))).scalars().first()
            if not conn:
                return
            _, http = sync.http_for(conn)
            ponds = await fub_collection(http, "ponds")
            for pond in ponds:
                pid = str(pond.get("id"))
                first = await http.request("GET", "/v1/people", params={"assignedPondId": pid, "limit": 1, "fields": "id"})
                log.info("fub_pond_total", pond=pond.get("name"), id=pid, fub_total=(first.get("_metadata") or {}).get("total"))
            scans = (await db.execute(select(CrmScan).where(CrmScan.connection_id == conn.id)
                     .order_by(CrmScan.created_at.desc()).limit(5))).scalars().all()
            for s in scans:
                r = s.result or {}
                log.info("fub_recent_scan", at=str(s.created_at)[:16], depth=r.get("depth"), segment=r.get("segment"),
                         scanned=r.get("scanned"), plays={p.get("key"): p.get("count") for p in r.get("plays") or []})
            for pond in ponds:
                if "cold" not in str(pond.get("name") or "").lower():
                    continue
                pid = str(pond.get("id"))
                t = time.monotonic()
                fub = PROVIDERS["followupboss"]
                people = await fub._pages(http, "/v1/people", "people", 10000,
                                          {"sort": "-created", "fields": fub._FIELDS, "assignedPondId": pid})
                in_pond = [p for p in people if str(p.get("assignedPondId") or "") == pid]
                log.info("fub_pond_read", pond=pond.get("name"), fetched=len(people), in_pond=len(in_pond),
                         with_phone=sum(1 for p in in_pond if any(x.get("value") for x in p.get("phones") or [])),
                         seconds=round(time.monotonic() - t, 1))
    except Exception as exc:
        log.warning("fub_pond_check_failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
