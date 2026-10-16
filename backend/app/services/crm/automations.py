"""Persisted Radar jobs. CRM actions set state and reconcile before retries; no call is dialed here."""
import asyncio
import datetime as dt
import uuid
import structlog
from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.exc import IntegrityError
from app.models.agent import Agent
from app.models.call_log import CallLog
from app.models.crm import CrmConnection
from app.models.lead import Lead
from app.models.radar_automation import RadarAutomation, RadarExecution, RadarPondMember, now
from app.services.contacts import normalize_phone
from app.services.crm.automation_schema import RuleSpec
from app.services.crm.http import CrmError
from app.services.crm import sync, verification
from app.services.crm.automation_resources import validate_spec

log = structlog.get_logger(__name__)
FINAL = ("completed", "failed", "no_answer")


def aware(value):
    return value.replace(tzinfo=dt.timezone.utc) if value and value.tzinfo is None else value


def verdict(call, lead):
    return verification.classify(call.transcript, lead.name, call.outcome or "")


def condition_matches(condition, call, evidence):
    if condition.kind == "verification":
        return condition.value == evidence["status"]
    if condition.kind == "outcome":
        return condition.value == call.outcome
    data = call.extracted_data or {}
    if condition.field not in data or data[condition.field] is None:
        return False
    value = str(data[condition.field]).strip()
    if condition.operator == "exists":
        return bool(value)
    if condition.operator == "contains":
        return condition.value.casefold() in value.casefold() if condition.value else False
    return value.casefold() == condition.value.casefold()


def source_matches(spec, call):
    return (not spec.source.agent_id or spec.source.agent_id == call.agent_id) and (
        not spec.source.campaign_id or spec.source.campaign_id == call.campaign_id)


async def inspect_call(db, conn, spec, call, lead, *, read_source=True):
    evidence = verdict(call, lead)
    if not source_matches(spec, call):
        return False, "Outside the selected source", evidence
    if lead.do_not_call or call.outcome == "do_not_call":
        return False, "Do not call / suppressed", evidence
    if call.call_type not in ("outbound", "inbound"):
        return False, "Browser and text tests are excluded", evidence
    if spec.source.blacksync_pond_id:
        member = await db.scalar(select(RadarPondMember.id).where(
            RadarPondMember.org_id == conn.org_id, RadarPondMember.pond_id == spec.source.blacksync_pond_id,
            RadarPondMember.lead_id == lead.id, RadarPondMember.phone == normalize_phone(call.to_phone or lead.phone)))
        if not member:
            return False, "Outside the selected BlackSync pond", evidence
    if spec.source.lead_source:
        ref = (lead.crm_refs or {}).get(conn.provider)
        if conn.provider != "followupboss" or not ref:
            return False, "No linked Follow Up Boss source contact", evidence
        _, http = sync.http_for(conn)
        person = await http.request("GET", f"/v1/people/{int(ref)}", params={"fields": "id,source"})
        if str(person.get("source") or "").casefold() != spec.source.lead_source.casefold():
            return False, "Outside the selected lead source", evidence
    if spec.source.pond_id:
        ref = (lead.crm_refs or {}).get(conn.provider)
        if conn.provider != "followupboss" or not ref:
            return False, "No linked person in the source pond", evidence
        _, http = sync.http_for(conn)
        person = await http.request("GET", f"/v1/people/{int(ref)}", params={"fields": "id,assignedPondId"})
        if str(person.get("assignedPondId") or "") != spec.source.pond_id:
            return False, "Outside the selected CRM pond", evidence
    match = condition_matches(spec.condition, call, evidence)
    return match, "Condition matched" if match else "Condition did not match", evidence


async def preview(db, conn, spec, limit=40):
    query = select(CallLog, Lead).join(Lead, Lead.id == CallLog.lead_id).where(
        CallLog.org_id == conn.org_id, Lead.org_id == conn.org_id, CallLog.status.in_(FINAL))
    if spec.source.agent_id:
        query = query.where(CallLog.agent_id == spec.source.agent_id)
    if spec.source.campaign_id:
        query = query.where(CallLog.campaign_id == spec.source.campaign_id)
    rows = (await db.execute(query.order_by(CallLog.started_at.desc()).limit(limit))).all()
    out = []
    for call, lead in rows:
        hit, reason, data = await inspect_call(db, conn, spec, call, lead)
        out.append({"call_id": str(call.id), "lead_id": str(lead.id), "name": lead.name,
                    "phone": normalize_phone(call.to_phone or lead.phone), "outcome": call.outcome,
                    "status": data["status"], "evidence": data["evidence"], "matches": hit, "reason": reason,
                    "started_at": call.started_at.isoformat()})
    return {"items": out, "matched": sum(x["matches"] for x in out), "checked": len(out),
            "limit": limit, "historical_preview": True, "writes_performed": False}


async def add_job(db, rule, call):
    if not call.lead_id or call.org_id != rule.org_id or call.call_type not in ("outbound", "inbound"):
        return False
    if not source_matches(RuleSpec.model_validate(rule.spec), call):
        return False
    if await db.scalar(select(RadarExecution.id).where(RadarExecution.automation_id == rule.id,
                                                     RadarExecution.version == rule.version,
                                                     RadarExecution.call_id == call.id)):
        return False
    try:
        async with db.begin_nested():
            db.add(RadarExecution(org_id=rule.org_id, automation_id=rule.id, call_id=call.id,
                                  version=rule.version, spec=rule.spec))
            await db.flush()
        return True
    except IntegrityError:
        return False


async def on_analyzed_call(db, call):
    lead = await db.get(Lead, call.lead_id) if call.lead_id else None
    if not lead or lead.org_id != call.org_id:
        return
    await verification.record(db, call, lead)
    rules = (await db.execute(select(RadarAutomation).where(RadarAutomation.org_id == call.org_id,
                                                           RadarAutomation.status == "active"))).scalars()
    for rule in rules:
        if rule.activated_at and aware(call.started_at) >= aware(rule.activated_at):
            await add_job(db, rule, call)


async def perform_action(db, conn, action, call, lead, catalog):
    phone = normalize_phone(call.to_phone or lead.phone)
    if action.kind == "blacksync_pond":
        pond_id = uuid.UUID(action.target_id)
        existing = await db.scalar(select(RadarPondMember.id).where(RadarPondMember.pond_id == pond_id,
                                  RadarPondMember.lead_id == lead.id, RadarPondMember.phone == phone))
        if not existing:
            try:
                async with db.begin_nested():
                    db.add(RadarPondMember(org_id=conn.org_id, pond_id=pond_id, lead_id=lead.id,
                                          phone=phone, call_id=call.id))
                    await db.flush()
            except IntegrityError:
                pass
        return "Added to BlackSync pond"
    ref = str((lead.crm_refs or {}).get(conn.provider) or "")
    if not ref:
        raise CrmError("This contact isn't linked to the selected CRM. Import/link it before routing.")
    p, http = sync.http_for(conn)
    if action.kind == "crm_deal_stage":
        from app.services.crm.fub_deals import route
        return await route(http, ref, action.pipeline_id, action.target_id, lead.name)
    if action.kind == "crm_stage":
        pipe = next(x for x in catalog["pipelines"] if x["id"] == action.pipeline_id)
        result = await p.set_stage(http, conn.config or {}, ref, pipe, action.target_id,
                                   create=False, forward_only=True, name=lead.name)
        return result or "Stage unchanged (already there or protected by CRM stage rules)"
    person = await http.request("GET", f"/v1/people/{int(ref)}", params={"fields": "id,tags,stage,assignedPondId"})
    if (person.get("stage") or "").casefold() in {"trash", "closed", "past client", "sphere"}:
        raise CrmError("The CRM person is closed or suppressed; routing was not applied.")
    if action.kind == "crm_pond":
        if str(person.get("assignedPondId") or "") != action.target_id:
            await http.request("PUT", f"/v1/people/{int(ref)}", json={"assignedPondId": int(action.target_id)})
        return "Routed to Follow Up Boss pond"
    tags = [str(t) for t in person.get("tags") or []]
    if action.target_id.casefold() not in {t.casefold() for t in tags}:
        await http.request("PUT", f"/v1/people/{int(ref)}", json={"tags": tags + [action.target_id]})
    return "Tag added"


async def recover_jobs(db):
    """Recover completed-call work after restarts; only calls started after activation are eligible."""
    rules = (await db.execute(select(RadarAutomation).where(RadarAutomation.status == "active"))).scalars().all()
    for rule in rules:
        if not rule.activated_at:
            continue
        known = exists().where(RadarExecution.automation_id == rule.id, RadarExecution.version == rule.version,
                               RadarExecution.call_id == CallLog.id)
        query = select(CallLog).where(CallLog.org_id == rule.org_id, CallLog.lead_id.is_not(None),
                 CallLog.call_type.in_(("outbound", "inbound")), CallLog.status.in_(FINAL),
                 CallLog.started_at >= rule.activated_at, CallLog.ended_at < now() - dt.timedelta(minutes=2), ~known)
        spec = RuleSpec.model_validate(rule.spec)
        if spec.source.agent_id:
            query = query.where(CallLog.agent_id == spec.source.agent_id)
        if spec.source.campaign_id:
            query = query.where(CallLog.campaign_id == spec.source.campaign_id)
        # Do not execute a connected call before its analysis is ready. No-answer calls need no transcript.
        query = query.where(or_(CallLog.summary.is_not(None), CallLog.outcome.in_(("no_answer", "failed"))))
        for call in (await db.execute(query.order_by(CallLog.started_at).limit(50))).scalars():
            await add_job(db, rule, call)


async def run_execution(execution_id):
    from app.database import AsyncSessionLocal
    from app.services import entitlements
    from app.models.account import Organization
    stamp = now()
    eligible = or_(and_(RadarExecution.status.in_(("queued", "retry")), RadarExecution.next_at <= stamp),
                   and_(RadarExecution.status == "running", RadarExecution.lease_until < stamp))
    async with AsyncSessionLocal() as db:
        claimed = await db.execute(update(RadarExecution).where(RadarExecution.id == execution_id, eligible).values(
            status="running", lease_until=stamp + dt.timedelta(minutes=5), attempts=RadarExecution.attempts + 1))
        await db.commit()
        if claimed.rowcount != 1:
            return
    async with AsyncSessionLocal() as db:
        job = await db.get(RadarExecution, execution_id)
        try:
            rule = await db.get(RadarAutomation, job.automation_id)
            if not rule or rule.status != "active" or rule.version != job.version:
                job.status, job.error = "skipped", "Rule is paused or its draft has changed"
                await db.commit()
                return
            conn = await db.get(CrmConnection, rule.connection_id)
            call = await db.get(CallLog, job.call_id)
            lead = await db.get(Lead, call.lead_id) if call and call.lead_id else None
            if not conn or conn.org_id != job.org_id or not call or call.org_id != job.org_id or not lead or lead.org_id != job.org_id:
                raise CrmError("The source contact or CRM connection is no longer available in this workspace.")
            org = await db.get(Organization, job.org_id)
            if not org or org.status != "active":
                raise CrmError("This workspace is suspended or unavailable.")
            await entitlements.require(db, org, "radar", "Radar is not enabled for this workspace.")
            spec = RuleSpec.model_validate(job.spec)
            hit, reason, evidence = await inspect_call(db, conn, spec, call, lead)
            job.result = {**(job.result or {}), "verification": evidence, "reason": reason}
            if not hit:
                job.status = "skipped"
                await db.commit()
                return
            catalog = await validate_spec(db, conn, spec)
            done = dict((job.result or {}).get("actions") or {})
            for index, action in enumerate(spec.actions):
                if str(index) in done:
                    continue
                if action.kind == "crm_deal_stage":
                    if (job.result or {}).get("pending_deal") is not None:
                        job.status, job.error = "failed", "A previous deal request may have reached the CRM. Review its receipt and deal before retrying."
                        await db.commit()
                        return
                    job.result = {**job.result, "pending_deal": index}
                    await db.commit()
                    # Serialize deal reconciliation for this contact across workers/rules.
                    await db.execute(select(Lead).where(Lead.id == lead.id).with_for_update())
                done[str(index)] = await perform_action(db, conn, action, call, lead, catalog)
                job.result = {k: v for k, v in {**job.result, "actions": dict(done)}.items() if k != "pending_deal"}
                job.lease_until = now() + dt.timedelta(minutes=5)
                await db.commit()
            job.status, job.error = "succeeded", ""
            await sync.add_log(db, conn, "radar", "ok", f"Radar automation “{rule.name}” applied.", call_id=call.id)
        except Exception as exc:
            # State-setting actions reconcile their target before retrying. Persist partial progress.
            await db.rollback()
            job = await db.get(RadarExecution, execution_id)
            job.status = "failed" if job.attempts >= 5 or (job.result or {}).get("pending_deal") is not None else "retry"
            job.error = str(exc)[:600]
            job.next_at = now() + dt.timedelta(seconds=min(3600, 30 * 2 ** job.attempts))
        job.lease_until, job.updated_at = None, now()
        await db.commit()


async def tick():
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await recover_jobs(db)
        await db.commit()
        ids = (await db.execute(select(RadarExecution.id).where(or_(
            and_(RadarExecution.status.in_(("queued", "retry")), RadarExecution.next_at <= now()),
            and_(RadarExecution.status == "running", RadarExecution.lease_until < now())))
            .order_by(RadarExecution.created_at).limit(20))).scalars().all()
    for key in ids:
        await run_execution(key)


def start_worker():
    async def loop():
        while True:
            try:
                await tick()
            except Exception as exc:
                log.warning("radar_worker_failed", error=str(exc)[:200])
            await asyncio.sleep(20)
    return asyncio.create_task(loop())
