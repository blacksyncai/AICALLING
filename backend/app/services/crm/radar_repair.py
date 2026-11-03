"""TEMPORARY read-only check (remove after it has run): Plivo numbers in BlackSync vs Plivo's own inventory.
Logs counts and the last 4 digits only. Never changes anything."""
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

log = structlog.get_logger(__name__)


async def run():
    from app.config import settings
    from app.database import AsyncSessionLocal
    from app.models.account import Organization
    from app.models.billing import PhoneNumber
    from app.services import plivo

    try:
        log.info("plivo_sync_check_settings", enabled=settings.plivo_inventory_sync_enabled,
                 startup_jobs=settings.run_startup_jobs, has_creds=bool(settings.plivo_auth_id and settings.plivo_auth_token))
        inventory = await plivo.inventory_numbers()
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(PhoneNumber).where(PhoneNumber.carrier == "plivo",
                    PhoneNumber.status == "active"))).scalars().all()
            missing = [r for r in rows if r.number not in inventory]
            out = []
            for r in missing[:15]:
                org = await db.get(Organization, r.org_id)
                exists = await plivo.number_exists(r.number)
                out.append({"last4": r.number[-4:], "org": (org.name if org else "")[:30],
                            "missing_since": str(r.provider_missing_since)[:16] if r.provider_missing_since else None,
                            "check_account_matches": r.provider_check_account in (None, settings.plivo_auth_id),
                            "plivo_says_exists": exists, "age_days": (datetime.now(timezone.utc) - (r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc))).days})
            log.info("plivo_sync_check", plivo_inventory=len(inventory), blacksync_active=len(rows),
                     missing_from_plivo=len(missing), sample=out)
    except Exception as exc:
        log.warning("plivo_sync_check_failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
