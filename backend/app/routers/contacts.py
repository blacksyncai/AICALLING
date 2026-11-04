"""
Contacts router — the account's CRM: every lead across campaigns, with
search, pipeline status, notes, tags, CSV import and call history.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import String, cast, delete, func, or_, select, update

from app.models.agent import Agent
from app.services.crm.variables import visible_fields
from app.services.public_errors import public_summary
from app.models.call_log import CallLog
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.services.accounts import emit_event
from app.services.auth import CtxDep, DbDep
from app.services import lead_phones
from app.services.contacts import CsvError, normalize_phone, parse_contacts_csv

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/contacts", tags=["contacts"])

PIPELINE = ("no_decision", "insufficient_conversation", "busy", "information_requested", "declined_conversation",
            "potential_follow_up", "new", "calling", "interested", "callback", "qualified", "meeting_booked",
            "not_interested", "not_qualified", "no_answer", "voicemail", "screened", "language_barrier", "hung_up", "completed", "failed")


class ContactIn(BaseModel):
    name: str = ""
    phone: str = ""
    # Every number, in call order: "+1415..." or {"number", "label", "status"}. The first is the primary.
    phones: list | None = None
    company: str = ""
    email: str = ""
    role: str = ""
    notes: str = ""
    tags: list[str] = []
    campaign_id: uuid.UUID | None = None
    # Extra fields usable as {{variables}} in agent prompts (e.g. {"area": "Austin"}).
    custom_fields: dict[str, str] | None = None


def _variables(raw: dict | None) -> dict[str, str]:
    """Variable names as the CSV import stores them (lowercase, spaces to underscores), values trimmed."""
    out: dict[str, str] = {}
    for k, v in (raw or {}).items():
        key = str(k).strip().lower().replace(" ", "_")[:60]
        if key:
            out[key] = "" if v is None else str(v).strip()[:500]
    return out


def _merge_variables(current: dict | None, new: dict | None) -> dict | None:
    """Sets the given variables on top of the current ones; an empty value removes one."""
    merged = dict(current or {})
    for k, v in _variables(new).items():
        if v:
            merged[k] = v
        else:
            merged.pop(k, None)
    return merged or None


class ContactPatch(BaseModel):
    name: str | None = None
    phone: str | None = None
    company: str | None = None
    email: str | None = None
    role: str | None = None
    notes: str | None = None
    status: str | None = None
    tags: list[str] | None = None
    campaign_id: uuid.UUID | None = None
    do_not_call: bool | None = None
    custom_fields: dict[str, str] | None = None  # merged into the contact's variables; "" removes one
    phones: list | None = None  # the full number list in call order (replaces it; known numbers keep their history)


class ContactImport(BaseModel):
    csv: str
    # Phone columns to use, in call order (default: every phone column the file has, detected automatically).
    phone_columns: list[str] | None = None
    campaign_id: uuid.UUID | None = None
    tags: list[str] = []
    # Numbers already in contacts: fill in this CSV's columns (variables, blank details) instead of skipping them.
    update_existing: bool = False
    # Numbers the file flags DNC: mark them do-not-call (never dialed). Off = they're called like any other.
    skip_dnc: bool = False


class CallContact(BaseModel):
    agent_id: uuid.UUID


class BulkAction(BaseModel):
    ids: list[uuid.UUID]
    action: str  # delete | add_to_campaign | set_status | add_tag | dnc_on | dnc_off
    campaign_id: uuid.UUID | None = None
    status: str | None = None
    tag: str | None = None


def _iso(d: datetime | None) -> str | None:
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()


def contact_to_dict(l: Lead, campaign_name: str | None = None) -> dict:
    return {
        "id": str(l.id),
        "name": l.name,
        "company": l.company,
        "phone": l.phone,
        "phones": lead_phones.public(l),
        "email": l.email,
        "role": l.role or "",
        "status": l.status,
        "notes": l.notes or "",
        "tags": l.tags or [],
        "custom_fields": visible_fields(l.custom_fields),
        "source": "lead_finder" if l.intent_source == "dataskip" else l.intent_source,  # never name the data vendor
        "campaign_id": str(l.campaign_id) if l.campaign_id else None,
        "campaign_name": campaign_name,
        "last_called_at": _iso(l.last_called_at),
        "do_not_call": bool(l.do_not_call),
        "attempts": l.attempts or 0,
        "created_at": _iso(l.created_at),
        "updated_at": _iso(l.updated_at),
    }


def _clean_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for t in tags:
        t = t.strip()[:40]
        if t and t not in out:
            out.append(t)
    return out[:20]


async def _campaign_in_org(db, ctx, campaign_id: uuid.UUID | None) -> Campaign | None:
    if campaign_id is None:
        return None
    campaign = await db.get(Campaign, campaign_id)
    if not campaign or campaign.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


async def _contact(db, ctx, contact_id: uuid.UUID) -> Lead:
    lead = await db.get(Lead, contact_id)
    if not lead or lead.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Contact not found")
    return lead


async def _recount_targets(db, campaign_ids: set) -> None:
    for cid in campaign_ids:
        if cid is None:
            continue
        n = (await db.execute(select(func.count()).select_from(Lead).where(Lead.campaign_id == cid))).scalar_one()
        await db.execute(update(Campaign).where(Campaign.id == cid).values(total_targets=n))


async def _detach_calls(db, lead_ids: list) -> None:
    """Deleting a contact keeps its call history (and billing) — just unlink it."""
    if lead_ids:
        await db.execute(update(CallLog).where(CallLog.lead_id.in_(lead_ids)).values(lead_id=None))


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("")
@router.get("/")
async def list_contacts(
    ctx: CtxDep, db: DbDep,
    q: str = "",
    status: str | None = None,
    campaign_id: uuid.UUID | None = None,
    tag: str | None = None,
    dnc: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort: str = "",
):
    base = select(Lead).where(Lead.org_id == ctx.org.id)
    if q.strip():
        like = f"%{q.strip()}%"
        base = base.where(or_(Lead.name.ilike(like), Lead.company.ilike(like), Lead.email.ilike(like),
                              Lead.phone.ilike(like), cast(Lead.phones, String).ilike(like)))
    if campaign_id:
        base = base.where(Lead.campaign_id == campaign_id)
    # Status counts reflect the search/campaign filter but not the status filter itself.
    if tag:
        base = base.where(cast(Lead.tags, String).ilike(f'%"{tag}"%'))
    if dnc is True:
        base = base.where(Lead.do_not_call.is_(True))
    elif dnc is False:
        base = base.where(or_(Lead.do_not_call.is_(None), Lead.do_not_call.is_(False)))
    sub = base.subquery()
    counts = dict((await db.execute(select(sub.c.status, func.count()).group_by(sub.c.status))).all())
    dnc_count = (await db.execute(
        select(func.count()).select_from(sub).where(sub.c.do_not_call.is_(True))
    )).scalar_one()
    filtered = base
    if status:
        # One status, or several comma-separated (a board column groups related ones).
        wanted = [x.strip() for x in status.split(",") if x.strip()]
        filtered = filtered.where(Lead.status.in_(wanted) if len(wanted) > 1 else Lead.status == wanted[0])
    if sort == "longest_call":
        # Longest single conversation first (the pipeline board); contacts never reached go last.
        longest_q = (select(CallLog.lead_id, func.max(CallLog.duration_seconds).label("secs"))
                     .where(CallLog.org_id == ctx.org.id).group_by(CallLog.lead_id).subquery())
        ordered = (filtered.outerjoin(longest_q, longest_q.c.lead_id == Lead.id)
                   .order_by(func.coalesce(longest_q.c.secs, 0).desc(), Lead.updated_at.desc()))
    else:
        ordered = filtered.order_by(Lead.created_at.desc())
    rows = (await db.execute(ordered.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    total = (await db.execute(select(func.count()).select_from(filtered.subquery()))).scalar_one()
    names = dict((await db.execute(
        select(Campaign.id, Campaign.name).where(Campaign.org_id == ctx.org.id)
    )).all())
    # How long each contact's latest call lasted (the little timer next to their status).
    # And their longest call, for contacts called more than once.
    last_call: dict = {}
    longest: dict = {}
    if rows:
        calls = (await db.execute(
            select(CallLog.lead_id, CallLog.duration_seconds)
            .where(CallLog.org_id == ctx.org.id, CallLog.lead_id.in_([l.id for l in rows]))
            .order_by(CallLog.started_at.desc()))).all()
        for lead_id, secs in calls:
            last_call.setdefault(lead_id, int(secs or 0))
            longest[lead_id] = max(longest.get(lead_id, 0), int(secs or 0))
    return {
        "items": [{**contact_to_dict(l, names.get(l.campaign_id)), "last_call_seconds": last_call.get(l.id),
                   "longest_call_seconds": longest.get(l.id)} for l in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "status_counts": counts,
        "dnc_count": dnc_count,
    }


@router.post("", status_code=201)
@router.post("/", status_code=201)
async def create_contact(body: ContactIn, ctx: CtxDep, db: DbDep):
    numbers = lead_phones.build([*([body.phone] if body.phone else []), *(body.phones or [])])
    phone = numbers[0]["number"] if numbers else normalize_phone(body.phone)
    if len(phone) < 11:
        raise HTTPException(status_code=400, detail="Enter a valid phone number, e.g. +14155550123.")
    campaign = await _campaign_in_org(db, ctx, body.campaign_id)
    lead = Lead(
        id=uuid.uuid4(), org_id=ctx.org.id, name=body.name.strip() or phone, phone=phone,
        company=body.company.strip(), email=body.email.strip(), role=body.role.strip(),
        notes=body.notes.strip() or None, tags=_clean_tags(body.tags) or None,
        campaign_id=campaign.id if campaign else None, intent_source="manual", status="new",
        custom_fields=_merge_variables(None, body.custom_fields),
        phones=numbers if len(numbers) > 1 else None,
    )
    db.add(lead)
    if campaign:
        campaign.total_targets = (campaign.total_targets or 0) + 1
    await db.commit()
    data = contact_to_dict(lead, campaign.name if campaign else None)
    await emit_event(ctx.org.id, "contact.created", data)
    return data


@router.post("/import", status_code=201)
async def import_contacts(body: ContactImport, ctx: CtxDep, db: DbDep):
    """Import a CSV. Numbers already in your contacts are skipped as duplicates."""
    campaign = await _campaign_in_org(db, ctx, body.campaign_id)
    try:
        rows, skipped = parse_contacts_csv(body.csv, body.phone_columns, body.skip_dnc)
    except CsvError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Dedupe by contact, not by number: a row matches a contact that has any of its numbers.
    owners: dict[str, uuid.UUID] = {}
    for lid, phone, phones in (await db.execute(select(Lead.id, Lead.phone, Lead.phones)
                                                .where(Lead.org_id == ctx.org.id))).all():
        for n in [phone, *[p.get("number") for p in (phones or []) if isinstance(p, dict)]]:
            if n:
                owners.setdefault(n, lid)
    tags = _clean_tags(body.tags) or None
    created, duplicates, updated = [], 0, 0
    touched: set[uuid.UUID] = set()
    for row in rows:
        row_numbers = [p["number"] for p in row["phones"]]
        match = next((owners[n] for n in row_numbers if n in owners), None)
        if match is not None:
            if body.update_existing and isinstance(match, uuid.UUID) and match not in touched:
                touched.add(match)
                for lead in [await db.get(Lead, match)]:
                    if lead is None:
                        continue
                    lead_phones.add_numbers(lead, row["phones"])
                    for n in lead_phones.all_numbers(lead):
                        owners.setdefault(n, match)
                    lead.custom_fields = _merge_variables(lead.custom_fields, row.get("custom_fields"))
                    for field in ("company", "email", "role"):
                        if row.get(field) and not getattr(lead, field):
                            setattr(lead, field, row[field])
                    if row.get("name") and (not lead.name or lead.name == lead.phone):
                        lead.name = row["name"]
                    lead.updated_at = datetime.now(timezone.utc)
                updated += 1
                continue
            duplicates += 1
            continue
        for n in row_numbers:
            owners[n] = "new"  # a later row with one of these numbers is the same person
        if len(row["phones"]) == 1 and row["phones"][0]["status"] == "untried":
            row = {**row, "phones": None}
        lead = Lead(id=uuid.uuid4(), org_id=ctx.org.id, campaign_id=campaign.id if campaign else None,
                    intent_source="csv", status="new", tags=tags, **row)
        db.add(lead)
        created.append(lead)
    if campaign:
        campaign.total_targets = (campaign.total_targets or 0) + len(created)
    await db.commit()
    log.info("contacts_imported", org_id=str(ctx.org.id), created=len(created), skipped=skipped, dupes=duplicates,
             updated=updated)
    for lead in created[:500]:
        await emit_event(ctx.org.id, "contact.created", contact_to_dict(lead, campaign.name if campaign else None))
    return {"created": len(created), "skipped": skipped, "duplicates": duplicates, "updated": updated}


@router.post("/bulk")
async def bulk_action(body: BulkAction, ctx: CtxDep, db: DbDep):
    if not body.ids:
        raise HTTPException(status_code=400, detail="Select at least one contact.")
    leads = (await db.execute(
        select(Lead).where(Lead.org_id == ctx.org.id, Lead.id.in_(body.ids))
    )).scalars().all()
    touched_campaigns = {l.campaign_id for l in leads}
    if body.action == "delete":
        await _detach_calls(db, [l.id for l in leads])
        await db.execute(delete(Lead).where(Lead.id.in_([l.id for l in leads])))
    elif body.action == "add_to_campaign":
        campaign = await _campaign_in_org(db, ctx, body.campaign_id)
        if not campaign:
            raise HTTPException(status_code=400, detail="Pick a campaign.")
        for l in leads:
            l.campaign_id = campaign.id
            if l.status not in ("meeting_booked",):
                l.status = "new"  # queue them up for the campaign
                l.attempts = 0
                l.next_attempt_at = None
        touched_campaigns.add(campaign.id)
    elif body.action == "set_status":
        if body.status not in PIPELINE:
            raise HTTPException(status_code=400, detail="Unknown status.")
        for l in leads:
            l.status = body.status
    elif body.action == "add_tag":
        tag = (body.tag or "").strip()[:40]
        if not tag:
            raise HTTPException(status_code=400, detail="Enter a tag.")
        for l in leads:
            l.tags = _clean_tags([*(l.tags or []), tag])
    elif body.action in ("dnc_on", "dnc_off"):
        for l in leads:
            l.do_not_call = body.action == "dnc_on"
    else:
        raise HTTPException(status_code=400, detail="Unknown action.")
    await db.flush()
    await _recount_targets(db, touched_campaigns)
    await db.commit()
    return {"updated": len(leads)}


@router.get("/{contact_id}")
async def get_contact(contact_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    lead = await _contact(db, ctx, contact_id)
    campaign = await db.get(Campaign, lead.campaign_id) if lead.campaign_id else None
    calls = (await db.execute(
        select(CallLog, Agent).outerjoin(Agent, Agent.id == CallLog.agent_id)
        .where(CallLog.lead_id == lead.id).order_by(CallLog.started_at.desc())
    )).all()
    return {
        **contact_to_dict(lead, campaign.name if campaign else None),
        "calls": [{
            "id": str(c.id), "status": c.status, "outcome": c.outcome, "summary": public_summary(c.status, c.summary),
            "duration_seconds": c.duration_seconds, "agent_name": a.name if a else None, "number": c.to_phone,
            "started_at": _iso(c.started_at),
        } for c, a in calls],
    }


@router.post("/{contact_id}/call")
async def call_contact(contact_id: uuid.UUID, body: CallContact, ctx: CtxDep, db: DbDep):
    """Have an agent call this contact right now."""
    from app.services.accounts import InsufficientCredits
    from app.services.outbound_call import CallSetupError, call_service

    lead = await _contact(db, ctx, contact_id)
    if lead.do_not_call:
        raise HTTPException(status_code=400, detail="This contact is on your Do-Not-Call list.")
    agent = await db.get(Agent, body.agent_id)
    if not agent or agent.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        call = await call_service.dispatch_call(lead, db, agent=agent)
    except InsufficientCredits as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    except (CallSetupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"call_id": str(call.id), "status": call.status}


@router.patch("/{contact_id}")
async def update_contact(contact_id: uuid.UUID, body: ContactPatch, ctx: CtxDep, db: DbDep):
    lead = await _contact(db, ctx, contact_id)
    data = body.model_dump(exclude_unset=True)
    old_campaign = lead.campaign_id
    if "phone" in data and data["phone"] is not None:
        phone = normalize_phone(data.pop("phone"))
        if len(phone) < 11:
            raise HTTPException(status_code=400, detail="Enter a valid phone number, e.g. +14155550123.")
        lead.phone = phone
    if "status" in data and data["status"] is not None and data["status"] not in PIPELINE:
        raise HTTPException(status_code=400, detail="Unknown status.")
    if "tags" in data and data["tags"] is not None:
        data["tags"] = _clean_tags(data["tags"])
    if "campaign_id" in data:
        await _campaign_in_org(db, ctx, data["campaign_id"])
    if "custom_fields" in data:
        lead.custom_fields = _merge_variables(lead.custom_fields, data.pop("custom_fields"))
    if data.get("phones") is not None:
        rows = lead_phones.build(data.pop("phones"), lead_phones.numbers(lead))
        if not rows:
            raise HTTPException(status_code=400, detail="Enter at least one valid phone number, e.g. +14155550123.")
        lead.phones, lead.phone = rows, rows[0]["number"]
        data.pop("phone", None)
    data.pop("phones", None)
    for key, value in data.items():
        if key == "campaign_id" or value is not None:
            setattr(lead, key, value.strip() if isinstance(value, str) else value)
    lead.updated_at = datetime.now(timezone.utc)
    await db.flush()
    if lead.campaign_id != old_campaign:
        await _recount_targets(db, {old_campaign, lead.campaign_id})
    await db.commit()
    campaign = await db.get(Campaign, lead.campaign_id) if lead.campaign_id else None
    return contact_to_dict(lead, campaign.name if campaign else None)


@router.delete("/{contact_id}", status_code=204)
async def delete_contact(contact_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    lead = await _contact(db, ctx, contact_id)
    cid = lead.campaign_id
    await _detach_calls(db, [lead.id])
    await db.execute(delete(Lead).where(Lead.id == lead.id))
    await db.flush()
    await _recount_targets(db, {cid})
    await db.commit()
