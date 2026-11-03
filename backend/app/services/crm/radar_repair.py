"""TEMPORARY read-only check (remove after it has run): a real Lofty Radar scan with the fixed reader.
Logs card counts and timing only."""
import time

import structlog
from sqlalchemy import select

log = structlog.get_logger(__name__)


async def run():
    from app.database import AsyncSessionLocal
    from app.models.crm import CrmConnection
    from app.services.crm import radar, sync
    from app.services.crm.providers import PROVIDERS

    try:
        async with AsyncSessionLocal() as db:
            conn = (await db.execute(select(CrmConnection).where(CrmConnection.provider == "lofty"))).scalars().first()
            if not conn:
                return
            p, http = sync.http_for(conn)
            for depth in ("quick", "recent"):
                t = time.monotonic()
                signals = await PROVIDERS["lofty"].scan_signals(http, conn.config or {}, depth=depth)
                plays = radar.build_plays(signals)
                log.info("lofty_scan_check", depth=depth, seconds=round(time.monotonic() - t, 1), scanned=plays["scanned"],
                         with_created=sum(1 for s in signals if s.created_at), with_calls=sum(1 for s in signals if s.calls),
                         with_inbound=sum(1 for s in signals if s.last_inbound_at),
                         cards={pl["key"]: pl["count"] for pl in plays["plays"]})
    except Exception as exc:
        log.warning("lofty_scan_check_failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
