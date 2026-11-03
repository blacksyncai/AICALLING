"""TEMPORARY read-only check (remove after it has run): what Lofty really returns for Radar.
Logs field names, value types and counts only (no names, phones or emails)."""
import structlog
from sqlalchemy import select

log = structlog.get_logger(__name__)


def _shape(v):
    if isinstance(v, dict):
        return {k: _shape(x) for k, x in list(v.items())[:40]}
    if isinstance(v, list):
        return [_shape(v[0])] if v else []
    if isinstance(v, str):
        return "date-ish:" + v[:25] if any(c.isdigit() for c in v[:4]) and ("-" in v[:10] or ":" in v) else "str"
    if isinstance(v, (int, float)) and v > 1_000_000_000:
        return f"num:{int(v)}"  # likely an epoch timestamp
    return type(v).__name__


async def run():
    from app.database import AsyncSessionLocal
    from app.models.crm import CrmConnection, CrmScan
    from app.services.crm import sync

    try:
        async with AsyncSessionLocal() as db:
            conns = (await db.execute(select(CrmConnection).where(CrmConnection.provider == "lofty"))).scalars().all()
            log.info("lofty_check_connections", count=len(conns), statuses=[c.status for c in conns])
            for conn in conns[:3]:
                scans = (await db.execute(select(CrmScan).where(CrmScan.connection_id == conn.id)
                         .order_by(CrmScan.created_at.desc()).limit(3))).scalars().all()
                for s in scans:
                    r = s.result or {}
                    log.info("lofty_check_scan", at=str(s.created_at)[:16], depth=r.get("depth"), scanned=r.get("scanned"),
                             plays={p.get("key"): p.get("count") for p in r.get("plays") or []}, error=str(r.get("error") or "")[:200])
                try:
                    _, http = sync.http_for(conn)
                except Exception as exc:
                    log.warning("lofty_check_http", error=str(exc)[:200]); continue
                for label, path, params in (
                    ("leads", "/v1.0/leads", {"offset": 0, "limit": 3, "sort": "CreateTime", "desc": "true"}),
                ):
                    try:
                        res = await http.request("GET", path, params=params)
                        leads = (res or {}).get("leads") or []
                        log.info("lofty_check_leads", top_keys=list((res or {}).keys())[:20], n=len(leads),
                                 lead_shape=_shape(leads[0]) if leads else None)
                    except Exception as exc:
                        log.warning("lofty_check_leads_failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
                        leads = []
                lid = next((str(l.get("leadId")) for l in leads if l.get("leadId")), None)
                if not lid:
                    continue
                for label, path, params in (
                    ("calls_v1", "/v1.0/communication/call", {"leadId": int(lid), "offset": 0, "limit": 5}),
                    ("calls_v2", "/v1.0/communication/call/v2", {"leadId": int(lid)}),
                    ("acts_v1", f"/v1.0/leads/{lid}/activities", {"offset": 0, "limit": 5}),
                    ("acts_v2", f"/v2.0/leads/{lid}/activities", {}),
                ):
                    try:
                        res = await http.request("GET", path, params=params)
                        log.info("lofty_check_endpoint", which=label, shape=_shape(res))
                    except Exception as exc:
                        log.warning("lofty_check_endpoint_failed", which=label, error=f"{type(exc).__name__}: {str(exc)[:200]}")
    except Exception as exc:
        log.warning("lofty_check_failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
