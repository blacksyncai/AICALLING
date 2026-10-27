"""TEMPORARY read-only check of long voicemail calls on one account (remove after use). Names redacted."""
import datetime as dt
import json
import re
from collections import Counter

import structlog
from sqlalchemy import select

log = structlog.get_logger(__name__)
ORG_PREFIX = "Compass Multi Family"


async def run():
    from app.database import AsyncSessionLocal
    from app.models.account import Organization
    from app.models.call_log import CallLog
    from app.models.lead import Lead

    try:
        async with AsyncSessionLocal() as db:
            org = (await db.execute(select(Organization).where(Organization.name.ilike(f"{ORG_PREFIX}%")))).scalars().first()
            if not org:
                return
            since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)
            rows = (await db.execute(select(CallLog, Lead).outerjoin(Lead, Lead.id == CallLog.lead_id).where(
                CallLog.org_id == org.id, CallLog.started_at >= since, CallLog.call_type == "outbound",
                CallLog.outcome.in_(("voicemail", "screened", "no_answer"))))).all()
            buckets = Counter()
            for c, _ in rows:
                d = c.duration_seconds or 0
                buckets[(c.outcome, "0-9" if d < 10 else "10-19" if d < 20 else "20-39" if d < 40 else "40-69" if d < 70 else "70+")] += 1
            log.info("vm_diag_buckets", total=len(rows), by=json.dumps(sorted([[*k, v] for k, v in buckets.items()])))
            long = [(c, l) for c, l in rows if (c.duration_seconds or 0) >= 20]
            long.sort(key=lambda x: -(x[0].duration_seconds or 0))
            for c, l in long[:25]:
                names = [t for t in ((l.name if l else "") or "").split() if len(t) > 1]

                def red(t):
                    t = str(t or "")[:160]
                    for n in names:
                        t = re.sub(re.escape(n), "{N}", t, flags=re.I)
                    return re.sub(r"\d{3,}", "#", t)
                tl = []
                for t in c.transcript or []:
                    if not isinstance(t, dict):
                        continue
                    ts = t.get("ts")
                    if t.get("role") == "tool":
                        tl.append(["tool", ts, t.get("tool"), json.dumps(t.get("args") or {})[:120]])
                    else:
                        tl.append([t.get("role", "?")[0], ts, red(t.get("text") or t.get("content"))])
                log.info("vm_diag_call", outcome=c.outcome, dur=c.duration_seconds, data=json.dumps(tl[:14])[:3000])
    except Exception as exc:
        log.warning("vm_diag_failed", error=str(exc)[:500])
