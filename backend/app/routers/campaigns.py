"""
Campaigns router — contact lists an agent dials through, with concurrency
limits, pause/resume and per-campaign stats.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update

from app.database import AsyncSessionLocal
from app.services.crm.variables import needs_prefill, visible_fields
from app.models.account import Organization
from app.models.agent import Agent
from app.models.call_log import CallLog
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.services import entitlements
from app.services.accounts import InsufficientCredits, ensure_can_call
from app.services.auth import Context, CtxDep, DbDep
from app.services.contacts import CsvError, parse_contacts_csv

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class CallingRules(BaseModel):
    # Calling hours — local "HH:MM" in `timezone`, on the given weekdays (0=Mon … 6=Sun).
    call_window_start: str | None = None
    call_window_end: str | None = None
    call_days: list[int] | None = None
    timezone: str | None = None
    # Automatic retries for unanswered calls.
    max_attempts: int | None = None
    retry_delay_minutes: int | None = None


class CampaignCreate(CallingRules):
    name: str
    description: str = ""
    icp_description: str = ""
    agent_id: uuid.UUID | None = None
    max_concurrent_calls: int = Field(default=1, ge=1, le=20)
    direction: str = Field(default="outbound", pattern="^(outbound|inbound)$")
    phone_number_id: uuid.UUID | None = None


class CampaignUpdate(CallingRules):
    name: str | None = None
    description: str | None = None
    agent_id: uuid.UUID | None = None
    max_concurrent_calls: int | None = Field(default=None, ge=1, le=20)
    phone_number_id: uuid.UUID | None = None


async def _check_number(db, ctx, number_id: uuid.UUID | None) -> None:
    """Inbound campaigns answer one of the account's own numbers."""
    from app.models.billing import PhoneNumber

    if number_id is None:
        raise HTTPException(status_code=400, detail="Inbound campaigns need your own phone number — get one under Phone numbers first.")
    row = await db.get(PhoneNumber, number_id)
    if not row or row.org_id != ctx.org.id or row.status != "active":
        raise HTTPException(status_code=404, detail="Phone number not found")


class LeadImport(BaseModel):
    # Raw CSV text. Needs a phone column; name/company/email/role are recognised,
    # every other column is stored as a custom field usable as {{column}} in prompts.
    csv: str


class CallSelectedRequest(BaseModel):
    lead_ids: list[uuid.UUID]


# ── Calling rules ─────────────────────────────────────────────────────────────

DEFAULT_WINDOW_START = "09:00"
DEFAULT_WINDOW_END = "17:00"
DEFAULT_CALL_DAYS = [0, 1, 2, 3, 4]  # Mon–Fri
DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_MAX_ATTEMPTS = 1
DEFAULT_RETRY_DELAY = 60
MAX_ATTEMPTS_LIMIT = 5

# Lead outcomes that mean "nobody picked up" — worth another try.
RETRY_STATUSES = ("no_answer", "voicemail", "failed")

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _parse_hhmm(value: str) -> time:
    m = _HHMM.match(value or "")
    if not m:
        raise ValueError(value)
    return time(int(m.group(1)), int(m.group(2)))


def _tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def calling_rules(c) -> dict:
    """The campaign's effective calling rules, with NULL fields filled by defaults."""
    days = c.call_days if c.call_days else DEFAULT_CALL_DAYS
    return {
        "call_window_start": c.call_window_start or DEFAULT_WINDOW_START,
        "call_window_end": c.call_window_end or DEFAULT_WINDOW_END,
        "call_days": sorted({int(d) for d in days}),
        "timezone": c.timezone or DEFAULT_TIMEZONE,
        "max_attempts": c.max_attempts or DEFAULT_MAX_ATTEMPTS,
        "retry_delay_minutes": c.retry_delay_minutes or DEFAULT_RETRY_DELAY,
    }


def _window(c) -> tuple[time, time, list[int], ZoneInfo]:
    r = calling_rules(c)
    try:
        start, end = _parse_hhmm(r["call_window_start"]), _parse_hhmm(r["call_window_end"])
    except ValueError:
        start, end = _parse_hhmm(DEFAULT_WINDOW_START), _parse_hhmm(DEFAULT_WINDOW_END)
    return start, end, r["call_days"], _tz(r["timezone"])


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def within_calling_hours(campaign, now_utc: datetime) -> bool:
    """True if `now_utc` falls inside the campaign's calling window (in its own time zone)."""
    start, end, days, tz = _window(campaign)
    local = _aware(now_utc).astimezone(tz)
    return local.weekday() in days and start <= local.time().replace(tzinfo=None) < end


def next_window_start(campaign, now_utc: datetime) -> datetime | None:
    """
    When the queue may next dial, in UTC: `now_utc` itself if already inside the
    window, otherwise the start of the next allowed window. None if no day is allowed.
    """
    now_utc = _aware(now_utc)
    if within_calling_hours(campaign, now_utc):
        return now_utc
    start, _end, days, tz = _window(campaign)
    local = now_utc.astimezone(tz)
    for offset in range(0, 8):
        day: date = local.date() + timedelta(days=offset)
        if day.weekday() not in days:
            continue
        candidate = datetime.combine(day, start, tzinfo=tz)
        if candidate > local:
            return candidate.astimezone(timezone.utc)
    return None


def _validate_rules(data: dict, current: Campaign | None = None) -> None:
    """Check calling-hours / retry fields in a create or update body (HTTP 400 on bad input)."""
    def bad(msg: str):
        raise HTTPException(status_code=400, detail=msg)

    for key in ("call_window_start", "call_window_end"):
        if data.get(key) is not None:
            try:
                _parse_hhmm(data[key])
            except ValueError:
                bad("Calling hours must be times like 09:00 or 17:30.")
    start = data.get("call_window_start") or (current.call_window_start if current else None) or DEFAULT_WINDOW_START
    end = data.get("call_window_end") or (current.call_window_end if current else None) or DEFAULT_WINDOW_END
    if ("call_window_start" in data or "call_window_end" in data) and _parse_hhmm(start) >= _parse_hhmm(end):
        bad("The calling window has to end after it starts.")
    if data.get("call_days") is not None:
        days = data["call_days"]
        if not days:
            bad("Pick at least one day to call on.")
        if any(d not in range(7) for d in days):
            bad("Calling days must be weekdays 0 (Mon) to 6 (Sun).")
        data["call_days"] = sorted(set(days))
    if data.get("timezone") is not None:
        try:
            ZoneInfo(data["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            bad("Unknown time zone.")
    if data.get("max_attempts") is not None and not 1 <= data["max_attempts"] <= MAX_ATTEMPTS_LIMIT:
        bad(f"Tries per contact must be between 1 and {MAX_ATTEMPTS_LIMIT}.")
    if data.get("retry_delay_minutes") is not None and not 5 <= data["retry_delay_minutes"] <= 7 * 24 * 60:
        bad("Wait between tries must be between 5 minutes and 7 days.")


def dial_eligibility(lead, campaign, now_utc: datetime) -> str | None:
    """
    Whether the campaign queue should dial this contact:
      "now"   — dial it now (new, or an unanswered contact whose retry is due)
      "later" — an unanswered contact with a retry still to come
      None    — nothing left to do for it (answered, out of tries, Do-Not-Call…)
    """
    if lead.do_not_call:
        return None
    if lead.status == "new":
        return "now"
    if lead.status in RETRY_STATUSES:
        # Contacts called before tries were tracked count as one attempt.
        attempts = max(lead.attempts or 0, 1)
        if attempts >= calling_rules(campaign)["max_attempts"]:
            return None
        due = lead.next_attempt_at
        if due is None or _aware(due) <= _aware(now_utc):
            return "now"
        return "later"
    return None


def _campaign_to_dict(c: Campaign, pending_retries: int = 0, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    nxt = next_window_start(c, now)
    return {
        "id": str(c.id),
        "name": c.name,
        "description": c.description,
        "status": c.status,
        "direction": c.direction or "outbound",
        "phone_number_id": str(c.phone_number_id) if c.phone_number_id else None,
        "pause_reason": c.pause_reason if c.status == "paused" else None,
        "icp_description": c.icp_description,
        "agent_id": str(c.agent_id) if c.agent_id else None,
        "max_concurrent_calls": c.max_concurrent_calls or 1,
        **calling_rules(c),
        "within_calling_hours": within_calling_hours(c, now),
        "next_window_at": nxt.isoformat() if nxt else None,
        "pending_retries": pending_retries,
        "total_targets": c.total_targets,
        "total_dialed": c.total_dialed,
        "total_qualified": c.total_qualified,
        "total_booked": c.total_booked,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


async def _pending_retries(db, campaign_ids: list[uuid.UUID]) -> dict:
    """Contacts per campaign that didn't pick up and still have a try left."""
    if not campaign_ids:
        return {}
    rows = await db.execute(
        select(Lead.campaign_id, func.count())
        .join(Campaign, Campaign.id == Lead.campaign_id)
        .where(
            Lead.campaign_id.in_(campaign_ids),
            Lead.status.in_(RETRY_STATUSES),
            or_(Lead.do_not_call.is_(None), Lead.do_not_call.is_(False)),
            func.coalesce(Lead.attempts, 1) < func.coalesce(Campaign.max_attempts, DEFAULT_MAX_ATTEMPTS),
        )
        .group_by(Lead.campaign_id)
    )
    return dict(rows.all())


async def _campaign_out(db, c: Campaign) -> dict:
    return _campaign_to_dict(c, (await _pending_retries(db, [c.id])).get(c.id, 0))


async def _get_campaign(db, ctx: Context, campaign_id: uuid.UUID) -> Campaign:
    campaign = await db.get(Campaign, campaign_id)
    if not campaign or campaign.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


async def _check_agent(db, ctx: Context, agent_id: uuid.UUID | None) -> None:
    if agent_id is not None:
        agent = await db.get(Agent, agent_id)
        if not agent or agent.org_id != ctx.org.id:
            raise HTTPException(status_code=404, detail="Agent not found")


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/")
async def list_campaigns(
    ctx: CtxDep,
    db: DbDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    stmt = (
        select(Campaign)
        .where(Campaign.org_id == ctx.org.id)
        .order_by(Campaign.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    campaigns = result.scalars().all()
    pending = await _pending_retries(db, [c.id for c in campaigns])
    now = datetime.now(timezone.utc)
    return {"campaigns": [_campaign_to_dict(c, pending.get(c.id, 0), now) for c in campaigns]}


@router.get("/{campaign_id}")
async def get_campaign(
    campaign_id: uuid.UUID,
    ctx: CtxDep,
    db: DbDep,
):
    campaign = await _get_campaign(db, ctx, campaign_id)
    return await _campaign_out(db, campaign)


@router.post("/", status_code=201)
async def create_campaign(
    body: CampaignCreate,
    ctx: CtxDep,
    db: DbDep,
):
    await _check_agent(db, ctx, body.agent_id)
    if body.direction == "inbound":
        await _check_number(db, ctx, body.phone_number_id)
    rules = body.model_dump(include=set(CallingRules.model_fields), exclude_none=True)
    _validate_rules(rules)
    await entitlements.check_concurrency(db, ctx.org, body.max_concurrent_calls)
    campaign = Campaign(
        direction=body.direction,
        phone_number_id=body.phone_number_id if body.direction == "inbound" else None,
        id=uuid.uuid4(),
        org_id=ctx.org.id,
        name=body.name,
        description=body.description,
        icp_description=body.icp_description,
        agent_id=body.agent_id,
        max_concurrent_calls=body.max_concurrent_calls,
        status="draft",
        **rules,
    )
    db.add(campaign)
    await db.commit()
    log.info("campaign_created", campaign_id=str(campaign.id), name=campaign.name)
    if body.direction == "inbound" and campaign.agent_id:
        # Inbound goes live right away — there's no list to prepare, and forgetting "Go live" means missed calls.
        from app.services.inbound import InboundError, activate

        try:
            agent = await db.get(Agent, campaign.agent_id)
            await entitlements.check_agent_can_call(db, ctx.org, agent)
            await activate(db, campaign)
            campaign.status = "running"
            await db.commit()
        except (InboundError, Exception) as exc:
            await db.rollback()
            log.warning("inbound_autolive_failed", campaign_id=str(campaign.id), error=str(exc)[:200])
            campaign = await db.get(Campaign, campaign.id)
    return _campaign_to_dict(campaign)


@router.patch("/{campaign_id}")
async def update_campaign(
    campaign_id: uuid.UUID,
    body: CampaignUpdate,
    ctx: CtxDep,
    db: DbDep,
):
    campaign = await _get_campaign(db, ctx, campaign_id)
    await _check_agent(db, ctx, body.agent_id)
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "phone_number_id" in data:
        if (campaign.direction or "outbound") != "inbound":
            data.pop("phone_number_id")
        else:
            await _check_number(db, ctx, data["phone_number_id"])
    _validate_rules(data, campaign)
    if data.get("max_concurrent_calls") and data["max_concurrent_calls"] > (campaign.max_concurrent_calls or 1):
        await entitlements.check_concurrency(db, ctx.org, data["max_concurrent_calls"])
    relink = (campaign.direction == "inbound" and campaign.status == "running"
              and ("agent_id" in data or "phone_number_id" in data))
    if relink:
        from app.services.inbound import deactivate

        await deactivate(db, campaign)
    for key, value in data.items():
        setattr(campaign, key, value)
    if relink:
        from app.services.inbound import InboundError, activate

        try:
            await activate(db, campaign)
        except InboundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    campaign.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return await _campaign_out(db, campaign)


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(
    campaign_id: uuid.UUID,
    ctx: CtxDep,
    db: DbDep,
):
    campaign = await _get_campaign(db, ctx, campaign_id)
    # Its contacts stay in the CRM, just no longer in this campaign.
    await db.execute(update(Lead).where(Lead.campaign_id == campaign_id).values(campaign_id=None))
    from app.services.inbound import deactivate

    await deactivate(db, campaign)
    await db.delete(campaign)
    await db.commit()


@router.post("/{campaign_id}/leads/import", status_code=201)
async def import_leads(
    campaign_id: uuid.UUID,
    body: LeadImport,
    ctx: CtxDep,
    db: DbDep,
):
    """Import contacts into this campaign from CSV text (header row required)."""
    campaign = await _get_campaign(db, ctx, campaign_id)
    try:
        rows, skipped = parse_contacts_csv(body.csv)
    except CsvError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    for row in rows:
        db.add(Lead(id=uuid.uuid4(), org_id=ctx.org.id, campaign_id=campaign_id,
                    intent_source="csv", status="new", **row))
    campaign.total_targets = (campaign.total_targets or 0) + len(rows)
    campaign.updated_at = datetime.now(timezone.utc)
    await db.commit()
    log.info("leads_imported", campaign_id=str(campaign_id), created=len(rows), skipped=skipped)
    return {"created": len(rows), "skipped": skipped}


def _ensure_can_dial(campaign: Campaign, org: Organization) -> None:
    from app.config import settings

    if not campaign.agent_id:
        raise HTTPException(status_code=400, detail="Pick an agent for this campaign first.")
    if not settings.phone_ready:
        raise HTTPException(
            status_code=400,
            detail="Calling isn't available on your account right now — message us in the chat and we'll get it sorted.",
        )
    try:
        ensure_can_call(org)
    except InsufficientCredits as exc:
        raise HTTPException(status_code=402, detail=str(exc))


@router.post("/{campaign_id}/start")
async def start_campaign(
    campaign_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    ctx: CtxDep,
    db: DbDep,
):
    """
    Start a campaign:
    1. Set status = running
    2. Enqueue all 'new' leads in background asyncio task
    """
    campaign = await _get_campaign(db, ctx, campaign_id)
    if campaign.status not in ("draft", "paused"):
        raise HTTPException(
            status_code=400,
            detail=f"Campaign is {campaign.status}, cannot start",
        )
    if campaign.agent_id:
        agent = await db.get(Agent, campaign.agent_id)
        if agent is not None:
            await entitlements.check_agent_can_call(db, ctx.org, agent)
    if (campaign.direction or "outbound") == "inbound":
        # Inbound: go live — the number's calls are answered by the campaign's agent.
        from app.services.inbound import InboundError, activate

        try:
            await activate(db, campaign)
        except InboundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            log.error("inbound_activate_failed", campaign_id=str(campaign_id), error=str(exc))
            raise HTTPException(status_code=502, detail="Couldn't connect the number to the agent. Try again in a minute.") from exc
        campaign.status = "running"
        campaign.pause_reason = None
        campaign.updated_at = datetime.now(timezone.utc)
        await db.commit()
        return {"message": "Answering calls", "campaign": await _campaign_out(db, campaign)}

    _ensure_can_dial(campaign, ctx.org)

    campaign.status = "running"
    campaign.pause_reason = None
    campaign.updated_at = datetime.now(timezone.utc)
    await db.commit()

    # Kick off background call queue (asyncio, no Celery)
    ensure_queue(str(campaign_id))

    log.info("campaign_started", campaign_id=str(campaign_id))
    return {"message": "Campaign started", "campaign": await _campaign_out(db, campaign)}


@router.post("/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: uuid.UUID,
    ctx: CtxDep,
    db: DbDep,
):
    campaign = await _get_campaign(db, ctx, campaign_id)

    campaign.status = "paused"
    campaign.pause_reason = None
    campaign.updated_at = datetime.now(timezone.utc)
    if (campaign.direction or "outbound") == "inbound":
        from app.services.inbound import deactivate

        await deactivate(db, campaign)
    await db.commit()
    return {"message": "Campaign paused", "campaign": await _campaign_out(db, campaign)}


@router.post("/{campaign_id}/cancel")
async def cancel_campaign(
    campaign_id: uuid.UUID,
    ctx: CtxDep,
    db: DbDep,
):
    campaign = await _get_campaign(db, ctx, campaign_id)

    campaign.status = "cancelled"
    campaign.updated_at = datetime.now(timezone.utc)
    from app.services.inbound import deactivate

    await deactivate(db, campaign)
    await db.commit()
    return {"message": "Campaign cancelled", "campaign": await _campaign_out(db, campaign)}


@router.get("/{campaign_id}/leads")
async def list_campaign_leads(
    campaign_id: uuid.UUID,
    ctx: CtxDep,
    db: DbDep,
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    await _get_campaign(db, ctx, campaign_id)

    stmt = select(Lead).where(Lead.campaign_id == campaign_id)
    if status:
        stmt = stmt.where(Lead.status == status)
    stmt = stmt.order_by(Lead.created_at.desc()).offset((page - 1) * page_size).limit(page_size)

    leads_result = await db.execute(stmt)
    leads = leads_result.scalars().all()
    # Tiny result tags: voicemails left/reached and whether we ever talked to the person.
    live = {"meeting_booked", "qualified", "not_qualified", "interested", "not_interested", "callback",
            "transferred", "completed", "do_not_call"}
    tags: dict = {l.id: {"voicemails": 0, "verified": False, "wrong_number": False} for l in leads}
    if leads:
        for lead_id, outcome in (await db.execute(select(CallLog.lead_id, CallLog.outcome).where(
                CallLog.lead_id.in_(list(tags))))).all():
            t = tags[lead_id]
            t["voicemails"] += outcome == "voicemail"
            t["verified"] = t["verified"] or outcome in live
            t["wrong_number"] = t["wrong_number"] or outcome == "wrong_number"

    return {
        "campaign_id": str(campaign_id),
        "leads": [
            {
                "id": str(l.id),
                "name": l.name,
                "company": l.company,
                "phone": l.phone,
                "email": l.email,
                "role": l.role,
                "status": l.status,
                "qualification_score": l.qualification_score,
                "notes": l.notes,
                "custom_fields": visible_fields(l.custom_fields),
                "fields_pending": needs_prefill(l),
                **tags[l.id],
                "do_not_call": bool(l.do_not_call),
                "attempts": l.attempts or 0,
                "next_attempt_at": _aware(l.next_attempt_at).isoformat() if l.next_attempt_at else None,
                "last_called_at": _aware(l.last_called_at).isoformat() if l.last_called_at else None,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in leads
        ],
    }


@router.post("/{campaign_id}/crm-fields")
async def fill_crm_fields(campaign_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    """Pull CRM fields for this campaign's CRM contacts that don't have them yet (older Radar campaigns)."""
    from app.models.crm import CrmConnection
    from app.services.crm import sync as crm_sync

    campaign = await _get_campaign(db, ctx, campaign_id)
    agent = await db.get(Agent, campaign.agent_id) if campaign.agent_id else None
    leads = (await db.execute(select(Lead).where(Lead.campaign_id == campaign_id))).scalars().all()
    todo = [l for l in leads if needs_prefill(l)][:200]
    if not agent or not todo:
        return {"filled": 0}
    conns = (await db.execute(select(CrmConnection).where(CrmConnection.org_id == campaign.org_id))).scalars().all()
    filled = 0
    for conn in conns:
        filled += await crm_sync.prefill_fields(conn, agent, [l for l in todo if conn.provider in (l.crm_refs or {})])
    await db.commit()
    return {"filled": filled}


@router.post("/{campaign_id}/call")
async def call_selected_leads(
    campaign_id: uuid.UUID,
    body: CallSelectedRequest,
    background_tasks: BackgroundTasks,
    ctx: CtxDep,
    db: DbDep,
):
    """
    Fire outbound calls for a specific set of selected leads (checkbox
    selection in the UI). Each lead is dialed via LiveKit SIP outbound using
    its own (editable) phone number — no demo override. Leads with no valid
    phone are skipped server-side with an error logged.
    """
    campaign = await _get_campaign(db, ctx, campaign_id)

    if not body.lead_ids:
        raise HTTPException(status_code=400, detail="No leads selected")
    _ensure_can_dial(campaign, ctx.org)

    # Only dial leads that actually belong to this campaign.
    rows = await db.execute(
        select(Lead.id, Lead.do_not_call).where(
            Lead.campaign_id == campaign_id,
            Lead.id.in_(body.lead_ids),
        )
    )
    matched = rows.all()
    if not matched:
        raise HTTPException(status_code=404, detail="No matching leads in this campaign")
    # Contacts on the Do-Not-Call list are never dialed.
    valid_ids = [str(lid) for lid, dnc in matched if not dnc]
    skipped_dnc = len(matched) - len(valid_ids)
    if not valid_ids:
        raise HTTPException(status_code=400, detail="All selected contacts are on your Do-Not-Call list.")

    # Mark the campaign running so the pipeline/stats reflect live activity.
    if campaign.status in ("draft", "paused"):
        campaign.status = "running"
        campaign.pause_reason = None
        campaign.updated_at = datetime.now(timezone.utc)
        await db.commit()

    background_tasks.add_task(_dispatch_selected, str(campaign_id), valid_ids)
    log.info("call_selected", campaign_id=str(campaign_id), count=len(valid_ids))
    return {"dispatched": len(valid_ids), "lead_ids": valid_ids, "skipped_dnc": skipped_dnc}


async def _dispatch_selected(campaign_id: str, lead_ids: list[str]) -> None:
    """Background task: dial each selected lead sequentially via LiveKit SIP."""
    from app.services.outbound_call import outbound_call_service

    campaign_uuid = uuid.UUID(campaign_id)
    for lid in lead_ids:
        if not await _wait_for_capacity(campaign_uuid):
            break
        async with AsyncSessionLocal() as db:
            lead = await db.get(Lead, uuid.UUID(lid))
            if not lead or lead.do_not_call:
                continue
            try:
                campaign = await db.get(Campaign, campaign_uuid)
                if campaign:
                    _record_attempt(lead, campaign)
                await outbound_call_service.dispatch_call(lead, db)
                if campaign:
                    campaign.total_dialed += 1
                    campaign.updated_at = datetime.now(timezone.utc)
                    await db.commit()
            except InsufficientCredits as exc:
                await _pause_for_credits(campaign_uuid, str(exc), "plan" if isinstance(exc, entitlements.PlanLimit) else "credits")
                break
            except Exception as exc:
                log.error("call_selected_dispatch_error", lead_id=lid, error=str(exc))
        await asyncio.sleep(2)

    log.info("call_selected_completed", campaign_id=campaign_id, count=len(lead_ids))


# ── Background call queue processor ──────────────────────────────────────────


_IN_FLIGHT = ("initiated", "ringing", "connected")


async def _pause_for_credits(campaign_uuid: uuid.UUID, reason: str, kind: str = "credits") -> None:
    async with AsyncSessionLocal() as db:
        campaign = await db.get(Campaign, campaign_uuid)
        if campaign and campaign.status == "running":
            campaign.status = "paused"
            campaign.pause_reason = kind  # credits | plan (agent over the plan's limit)
            campaign.updated_at = datetime.now(timezone.utc)
            await db.commit()
    log.warning("campaign_paused_no_credits", campaign_id=str(campaign_uuid), reason=reason)


async def _wait_for_capacity(campaign_uuid: uuid.UUID) -> bool:
    """
    Block until the campaign has fewer in-flight calls than its concurrency
    limit. Returns False if the campaign stopped running while waiting.
    Calls older than 20 minutes are treated as stale so a lost outcome
    webhook can never wedge the queue.
    """
    from datetime import timedelta

    from app.models.call_log import CallLog

    while True:
        async with AsyncSessionLocal() as db:
            campaign = await db.get(Campaign, campaign_uuid)
            if not campaign or campaign.status != "running":
                return False
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=20)
            active = (await db.execute(
                select(func.count()).select_from(CallLog).where(
                    CallLog.campaign_id == campaign_uuid,
                    CallLog.status.in_(_IN_FLIGHT),
                    CallLog.started_at >= cutoff,
                )
            )).scalar_one()
            from app.models.account import Organization

            org = await db.get(Organization, campaign.org_id)
            cap = await entitlements.concurrency_cap(db, org) if org else None
            limit = campaign.max_concurrent_calls or 1
            if cap is not None:
                limit = min(limit, cap)  # a plan downgrade lowers running campaigns too
            if active < limit:
                return True
        await asyncio.sleep(3)


def _record_attempt(lead: Lead, campaign: Campaign, now: datetime | None = None) -> None:
    """Count a dial and schedule when a retry would be due if nobody picks up."""
    now = now or datetime.now(timezone.utc)
    lead.attempts = (lead.attempts or 0) + 1
    lead.last_called_at = now
    lead.next_attempt_at = now + timedelta(minutes=calling_rules(campaign)["retry_delay_minutes"])


async def _idle(campaign_uuid: uuid.UUID, seconds: float) -> bool:
    """Sleep up to `seconds`, waking early if the campaign is paused or cancelled.
    Returns False if the campaign stopped running."""
    remaining = max(seconds, 1)
    while remaining > 0:
        step = min(5.0, remaining)
        await asyncio.sleep(step)
        remaining -= step
        async with AsyncSessionLocal() as db:
            campaign = await db.get(Campaign, campaign_uuid)
            if not campaign or campaign.status != "running":
                return False
    return True


async def _next_lead(db, campaign: Campaign, now: datetime) -> tuple[Lead | None, int, datetime | None]:
    """
    Pick the next contact to dial. Returns (lead to dial now or None,
    number of contacts still waiting on a retry, earliest retry time).
    """
    candidates = (await db.execute(
        select(Lead)
        .where(
            Lead.campaign_id == campaign.id,
            Lead.status.in_(("new", "calling", *RETRY_STATUSES)),
            or_(Lead.do_not_call.is_(None), Lead.do_not_call.is_(False)),
        )
        .order_by(Lead.created_at.asc())
    )).scalars().all()
    waiting, earliest = 0, None
    max_attempts = calling_rules(campaign)["max_attempts"]
    recent = now - timedelta(minutes=20)
    for lead in candidates:
        if lead.status == "calling":
            if lead.last_called_at and _aware(lead.last_called_at) >= recent:
                # A call in progress may still end unanswered and need another try.
                if max_attempts > 1 and (lead.attempts or 0) < max_attempts:
                    waiting += 1
                    due = now + timedelta(seconds=60)
                    earliest = due if earliest is None else min(earliest, due)
                continue
            # Stuck "calling" for 20+ minutes: its call never reported back (e.g. a restart cut it off).
            # Only someone who never picked up gets another try — if they answered, they had a
            # conversation and are never called back.
            from app.models.call_log import CallLog

            answered = (await db.execute(select(func.count()).select_from(CallLog).where(
                CallLog.lead_id == lead.id, CallLog.answered_at.is_not(None)))).scalar_one()
            if answered:
                lead.status = "completed"
                continue
            lead.status = "no_answer"
        state = dial_eligibility(lead, campaign, now)
        if state == "now":
            return lead, waiting, earliest
        if state == "later":
            waiting += 1
            due = _aware(lead.next_attempt_at)
            earliest = due if earliest is None else min(earliest, due)
    return None, waiting, earliest


# One dialer per campaign in this process. Starting a campaign twice (or waking it from an import)
# never runs two dialers side by side.
_QUEUES: dict[str, asyncio.Task] = {}


def ensure_queue(campaign_id: str) -> bool:
    """Start the campaign's dialer unless one is already running. Returns True if it started one."""
    task = _QUEUES.get(campaign_id)
    if task is not None and not task.done():
        return False
    task = asyncio.create_task(_process_call_queue(campaign_id))
    _QUEUES[campaign_id] = task
    task.add_done_callback(lambda t, cid=campaign_id: _QUEUES.pop(cid, None) if _QUEUES.get(cid) is t else None)
    return True


async def resume_running_campaigns() -> int:
    """After a restart: pick every running outbound campaign back up (dialers live in memory and die
    with the process, which used to leave campaigns "Running" with nothing dialing and no redials)."""
    async with AsyncSessionLocal() as db:
        ids = (await db.execute(select(Campaign.id).where(
            Campaign.status == "running",
            or_(Campaign.direction.is_(None), Campaign.direction != "inbound"),
        ))).scalars().all()
    started = sum(ensure_queue(str(cid)) for cid in ids)
    log.info("campaigns_resumed", count=started)
    return started


async def _process_call_queue(campaign_id: str) -> None:
    """
    Background asyncio task: dial this campaign's contacts one after another,
    inside its calling hours and within its concurrency limit. Contacts that
    don't pick up are retried after the campaign's delay until they run out of
    tries; Do-Not-Call contacts are skipped. Respects pause/cancel throughout and
    marks the campaign completed only once nothing is left to dial now or later.
    """
    from app.services.outbound_call import outbound_call_service

    log.info("call_queue_started", campaign_id=campaign_id)
    campaign_uuid = uuid.UUID(campaign_id)

    while True:
        async with AsyncSessionLocal() as db:
            campaign = await db.get(Campaign, campaign_uuid)
            if not campaign or campaign.status != "running":
                log.info("call_queue_halted", campaign_id=campaign_id,
                         reason=campaign.status if campaign else "not_found")
                return
            now = datetime.now(timezone.utc)
            in_hours = within_calling_hours(campaign, now)
            nxt = None if in_hours else next_window_start(campaign, now)

        if not in_hours:
            # Outside calling hours: wait (still honouring pause/cancel) instead of finishing.
            wait = (nxt - now).total_seconds() if nxt else 60
            if not await _idle(campaign_uuid, min(max(wait, 1), 60)):
                log.info("call_queue_halted", campaign_id=campaign_id)
                return
            continue

        # Respect pause/cancel and the concurrency limit before each call.
        if not await _wait_for_capacity(campaign_uuid):
            log.info("call_queue_halted", campaign_id=campaign_id)
            return

        async with AsyncSessionLocal() as db:
            campaign = await db.get(Campaign, campaign_uuid)
            if not campaign or campaign.status != "running":
                log.info("call_queue_halted", campaign_id=campaign_id,
                         reason=campaign.status if campaign else "not_found")
                return
            now = datetime.now(timezone.utc)
            lead, waiting, earliest = await _next_lead(db, campaign, now)

            if lead is None:
                if not waiting:
                    campaign.status = "completed"
                    campaign.updated_at = now
                    await db.commit()
                    log.info("call_queue_completed", campaign_id=campaign_id)
                    return
                wait = (earliest - now).total_seconds() if earliest else 60
            else:
                wait = 0
                lead_id, prev_attempts = lead.id, lead.attempts or 0
                try:
                    _record_attempt(lead, campaign, now)
                    await outbound_call_service.dispatch_call(lead, db)
                    campaign.total_dialed += 1
                    campaign.updated_at = datetime.now(timezone.utc)
                    await db.commit()
                except InsufficientCredits as exc:
                    await _pause_for_credits(campaign_uuid, str(exc), "plan" if isinstance(exc, entitlements.PlanLimit) else "credits")
                    return
                except Exception as exc:
                    log.error("call_queue_dispatch_error", lead_id=str(lead.id), error=str(exc))
                    await db.rollback()
                    # Count the failed try so a contact that can't be dialed
                    # (bad number, setup error) isn't redialed in a tight loop.
                    fresh = await db.get(Lead, lead_id)
                    campaign = await db.get(Campaign, campaign_uuid)
                    if fresh and campaign:
                        await db.refresh(fresh)
                        if (fresh.attempts or 0) == prev_attempts:
                            _record_attempt(fresh, campaign)
                        if fresh.status in ("new", "calling"):
                            fresh.status = "failed"
                        await db.commit()

        if wait:
            # Retries are pending but none is due yet — wait for the earliest.
            if not await _idle(campaign_uuid, min(max(wait, 1), 60)):
                log.info("call_queue_halted", campaign_id=campaign_id)
                return
        else:
            # Brief delay between calls to avoid SIP trunk saturation
            await asyncio.sleep(2)
