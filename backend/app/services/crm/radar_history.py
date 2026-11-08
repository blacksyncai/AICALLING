"""Evidence-based groups for contact-reading adapters, enriched by saved BlackSync calls."""
import datetime as dt
from sqlalchemy import select
from app.models.call_log import CallLog
from app.models.lead import Lead
from app.services.contacts import normalize_phone
from app.services.crm import radar


def aware(value):
    return value.replace(tzinfo=dt.timezone.utc) if value and value.tzinfo is None else value


async def enrich(db, org_id, provider, signals):
    ids = {s.external_id for s in signals}
    if not ids:
        return
    leads = (await db.execute(select(Lead.id, Lead.phone, Lead.crm_refs).where(
        Lead.org_id == org_id, Lead.crm_refs[provider].as_string().in_(ids)))).all()
    by_key = {(s.external_id, normalize_phone(s.phone)): s for s in signals}
    mapped = {lead.id: by_key[(str(lead.crm_refs[provider]), normalize_phone(lead.phone))]
              for lead in leads if (str(lead.crm_refs[provider]), normalize_phone(lead.phone)) in by_key}
    if not mapped:
        return
    rows = (await db.execute(select(CallLog.lead_id, CallLog.call_type, CallLog.outcome,
        CallLog.started_at, CallLog.duration_seconds, CallLog.to_phone, CallLog.from_phone).where(
        CallLog.org_id == org_id, CallLog.lead_id.in_(mapped), CallLog.status.in_(("completed", "failed", "no_answer")),
        CallLog.call_type.in_(("outbound", "inbound"))).order_by(CallLog.started_at))).all()
    for call in rows:
        s = mapped[call.lead_id]
        phone = call.from_phone if call.call_type == "inbound" else call.to_phone
        when = aware(call.started_at)
        if not when or normalize_phone(phone) != normalize_phone(s.phone):
            continue
        if call.outcome == "do_not_call":
            s.dnc = True
        connected = (call.duration_seconds or 0) > 0 and call.outcome not in (
            "voicemail", "screened", "no_answer", "failed", "wrong_number")
        s.extra["blacksync_history"] = True
        s.last_activity_at = max(filter(None, [s.last_activity_at, when]))
        if call.call_type == "outbound":
            if s.contacted is False:
                s.contacted = None  # Saved attempts supersede a stale CRM untouched flag.
            s.calls += 1
            s.last_call_at, s.last_call_result = when, call.outcome or ""
        elif connected:
            s.last_inbound_at, s.inbound_kind = when, "Called your BlackSync agent"
        if connected:
            s.connected_calls += 1
            s.contacted = True


def build(signals, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    groups = {p["key"]: [] for p in radar.PLAYS}
    groups.update(contacted=[], unknown=[])
    descriptions = [*radar.PLAYS,
        {"key": "contacted", "title": "Contacted", "why": "A recorded conversation or the CRM's explicit contacted flag.",
         "suggest": "Review the last conversation before choosing a next step."},
        {"key": "unknown", "title": "Needs activity data", "why": "Not enough verified history to classify this contact.",
         "suggest": "Missing history does not mean the contact has never been called."}]
    for s in signals:
        if s.dnc or not s.phone or any(word in s.status.casefold() for word in (
                "lost", "dead", "trash", "not interested", "do not")):
            continue
        # Without activity dates, the absence of CRM history cannot establish that an old lead is quiet.
        has_evidence = s.calls_known or s.contacted is False or any((s.last_activity_at, s.last_inbound_at,
                                                  s.last_call_at, s.deal_updated_at, s.won_at))
        if s.extra.get("activity_incomplete"):
            hit = (("stuck", f"No deal updates in {s.deal_stage} since {s.deal_updated_at.date()}")
                   if s.deal_open and s.deal_updated_at and (now-s.deal_updated_at).days >= 21 else None)
        else:
            hit = radar.classify(s, now) if has_evidence else None
        if hit:
            key, reason = hit
        elif s.contacted is False:
            key, reason = "never_called", "CRM explicitly marks this contact as not contacted"
        elif s.contacted is True or s.connected_calls:
            key, reason = "contacted", "Contacted in the CRM" if not s.connected_calls else "Recorded conversation"
        else:
            key, reason = "unknown", "CRM call and stage history is unavailable"
        if s.extra.get("blacksync_history"):
            reason = "BlackSync call history · " + reason
        item = radar.build_segment([s], "", "", now)["plays"][0]["items"][0]
        item.update(reason=reason, calls=s.calls if s.extra.get("blacksync_history") or s.calls_known else None,
                    last_touch=(s.last_activity_at or s.last_call_at or s.last_inbound_at).isoformat()
                               if any((s.last_activity_at, s.last_call_at, s.last_inbound_at)) else None)
        groups[key].append(item)
    return {"scanned": len(signals), "plays": [{**p, "items": groups[p["key"]], "count": len(groups[p["key"]])}
                                                for p in descriptions]}
