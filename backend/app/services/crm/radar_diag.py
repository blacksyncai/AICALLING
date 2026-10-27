"""TEMPORARY read-only diagnostic for one account's Radar rules (remove after use).

Logs rule settings and why recent calls were skipped. Ids, statuses and reasons only: no names, phones or transcripts.
"""
import datetime as dt
import json
from collections import Counter

import structlog
from sqlalchemy import select

log = structlog.get_logger(__name__)
ORG_PREFIX = "Compass Multi Family"


def _out(kind, **data):
    log.info("radar_diag", kind=kind, data=json.dumps(data, default=str)[:3500])


async def run():
    from app.database import AsyncSessionLocal
    from app.models.account import Organization
    from app.models.call_log import CallLog
    from app.models.crm import CrmConnection
    from app.models.lead import Lead
    from app.models.radar_automation import RadarAutomation, RadarExecution
    from app.services.crm import sync, verification
    from app.services.crm.automation_resources import resources

    try:
        async with AsyncSessionLocal() as db:
            org = (await db.execute(select(Organization).where(Organization.name.ilike(f"{ORG_PREFIX}%")))).scalars().first()
            if not org:
                _out("no_org")
                return
            rules = (await db.execute(select(RadarAutomation).where(RadarAutomation.org_id == org.id))).scalars().all()
            for r in rules:
                _out("rule", id=r.id, name=r.name, status=r.status, version=r.version, activated_at=r.activated_at, spec=r.spec)
            conn = (await db.execute(select(CrmConnection).where(CrmConnection.org_id == org.id,
                                                                 CrmConnection.provider == "followupboss"))).scalars().first()
            if conn:
                try:
                    res = await resources(db, conn)
                    _out("crm", ponds=res["crm_ponds"], deal_pipelines=res["deal_pipelines"], warnings=res["warnings"])
                except Exception as exc:
                    _out("crm_error", error=str(exc)[:300])
            since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=4)
            jobs = (await db.execute(select(RadarExecution).where(RadarExecution.org_id == org.id,
                                                                  RadarExecution.created_at >= since))).scalars().all()
            names = {r.id: r.name for r in rules}
            tally = Counter((names.get(j.automation_id, "?"), j.status, (j.result or {}).get("reason") or j.error[:80]) for j in jobs)
            _out("jobs", total=len(jobs), by=[[*k, n] for k, n in tally.most_common(40)])
            ver = Counter(((j.result or {}).get("verification") or {}).get("status") for j in jobs)
            _out("job_verification", counts=dict(ver))

            # Round 2: failed jobs, the agent's opener, and how conversations start (contact name redacted).
            from app.models.agent import Agent
            import re
            failed = [j for j in jobs if j.status == "failed"]
            _out("failed_jobs", items=[{"rule": names.get(j.automation_id), "error": j.error[:300],
                                        "result_keys": sorted((j.result or {}).keys())} for j in failed])
            agent_ids = {(r.spec.get("source") or {}).get("agent_id") for r in rules} - {None, ""}
            for aid in agent_ids:
                a = await db.get(Agent, __import__("uuid").UUID(aid))
                if a:
                    _out("agent", first_message=(a.first_message or "")[:300], prompt_has_is_this="is this" in (a.system_prompt or "").lower())
            q = select(CallLog, Lead).join(Lead, Lead.id == CallLog.lead_id).where(
                CallLog.org_id == org.id, CallLog.started_at >= since, CallLog.call_type == "outbound",
                CallLog.outcome.in_(("completed", "not_interested", "meeting_booked", "callback", "interested", "wrong_number", "do_not_call")))
            convs = []
            for call, lead in (await db.execute(q.limit(25))).all():
                first = ((lead.name or "").split() or [""])[0]
                def red(t):
                    t = str(t or "")[:200]
                    for tok in (lead.name or "").split():
                        if len(tok) > 1:
                            t = re.sub(re.escape(tok), "{NAME}", t, flags=re.I)
                    return t
                turns = [t for t in (call.transcript or []) if isinstance(t, dict) and t.get("role") in ("user", "assistant")][:5]
                convs.append({"outcome": call.outcome, "name_tokens": len((lead.name or "").split()), "first_len": len(first),
                              "turns": [[t["role"][0], red(t.get("text") or t.get("content"))] for t in turns]})
            _out("conversations", items=convs[:12])
            _out("conversations2", items=convs[12:25])
    except Exception as exc:
        _out("failed", error=str(exc)[:500])
