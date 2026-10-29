"""TEMPORARY read-only check (remove after it has run): which address columns Compass contacts carry.
Logs column names and counts only, plus Mario Medal's address-like columns."""
import structlog
from sqlalchemy import select

log = structlog.get_logger(__name__)


async def run():
    from app.database import AsyncSessionLocal
    from app.models.account import Organization
    from app.models.lead import Lead

    try:
        async with AsyncSessionLocal() as db:
            org = (await db.execute(select(Organization).where(Organization.name.ilike("Compass Multi Family%")))).scalars().first()
            if not org:
                return
            leads = (await db.execute(select(Lead).where(Lead.org_id == org.id).limit(3000))).scalars().all()
            keys = {}
            for lead in leads:
                for k in (lead.custom_fields or {}):
                    keys[k] = keys.get(k, 0) + 1
                for k in ((lead.custom_fields or {}).get("crm_fields") or {}):
                    keys["crm_fields." + k] = keys.get("crm_fields." + k, 0) + 1
            mario = next((l for l in leads if (l.name or "").lower().startswith("mario medal")), None)
            no_city = [l for l in leads if (l.custom_fields or {}).get("address") and not (l.custom_fields or {}).get("city")]
            sample = []
            for l in no_city[:5]:
                cf = l.custom_fields or {}
                sample.append({k: str(v)[:40] for k, v in cf.items() if k in ("address", "custom2", "custom3", "custom4",
                               "property_address", "property_street", "mailing_address", "source", "listing_status")})
            log.info("compass_no_city_sample", count=len(no_city), sample=sample,
                     mario_keys=sorted((mario.custom_fields or {}).keys()) if mario else None)
            addr = {}
            if mario:
                cf = mario.custom_fields or {}
                for k, v in {**cf, **{("crm_fields." + a): b for a, b in (cf.get("crm_fields") or {}).items()}}.items():
                    if any(w in k.lower() for w in ("addr", "city", "state", "zip", "street", "postal")):
                        addr[k] = str(v)[:60]
            cols = [c for c in Lead.__table__.columns.keys() if any(w in c for w in ("addr", "city", "state", "zip"))]
            log.info("compass_address_check", leads=len(leads), lead_columns=cols,
                     keys=dict(sorted(keys.items(), key=lambda x: -x[1])[:40]), mario=addr,
                     mario_cols={c: getattr(mario, c) for c in cols} if mario else None)
    except Exception as exc:
        log.warning("compass_address_check_failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
