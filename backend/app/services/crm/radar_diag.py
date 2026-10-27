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

            # Recent finished calls from the rules' agents: what the classifier heard, re-run now.
            agent_ids = {(r.spec.get("source") or {}).get("agent_id") for r in rules} - {None, ""}
            q = select(CallLog, Lead).join(Lead, Lead.id == CallLog.lead_id).where(
                CallLog.org_id == org.id, CallLog.started_at >= since, CallLog.call_type.in_(("outbound", "inbound")))
            rows = (await db.execute(q)).all()
            stats = Counter()
            samples = []
            for call, lead in rows:
                v = verification.classify(call.transcript, lead.name, call.outcome or "")
                in_rules = str(call.agent_id) in agent_ids
                stats[(call.outcome, v["status"], in_rules, bool(call.transcript))] += 1
                if v["status"] == "unverified" and call.outcome in ("voicemail",) and len(samples) < 12:
                    user = [t for t in (call.transcript or []) if isinstance(t, dict) and t.get("role") == "user"]
                    first = (lead.name or "").split()[0] if lead.name else ""
                    text = " ".join(str(t.get("text") or t.get("content") or "") for t in user)
                    samples.append({"call": call.id, "user_turns": len(user), "name_len": len(first),
                                    "name_in_text": bool(first) and first.lower() in text.lower(),
                                    "greeting_words": len(text.split()), "has_vm_phrase": any(
                                        p in text.lower() for p in ("leave", "message", "tone", "beep", "reached"))})
            _out("calls", total=len(rows), agents=list(agent_ids),
                 by=[[*k, n] for k, n in stats.most_common(40)])
            _out("vm_unverified_samples", items=samples)

            # Skips for "Outside the selected CRM pond": where is that person now?
            pond_skips = [j for j in jobs if (j.result or {}).get("reason") == "Outside the selected CRM pond"][:15]
            if conn and pond_skips:
                _, http = sync.http_for(conn)
                where = []
                for j in pond_skips:
                    call = await db.get(CallLog, j.call_id)
                    lead = await db.get(Lead, call.lead_id) if call and call.lead_id else None
                    ref = (lead.crm_refs or {}).get("followupboss") if lead else None
                    pond = None
                    if ref:
                        try:
                            person = await http.request("GET", f"/v1/people/{int(ref)}", params={"fields": "id,assignedPondId"})
                            pond = person.get("assignedPondId")
                        except Exception as exc:
                            pond = f"error: {str(exc)[:80]}"
                    where.append({"rule_pond": (j.spec.get("source") or {}).get("pond_id"), "person_pond": pond,
                                  "linked": bool(ref), "verification": ((j.result or {}).get("verification") or {}).get("status")})
                _out("pond_skips", items=where)
    except Exception as exc:
        _out("failed", error=str(exc)[:500])
