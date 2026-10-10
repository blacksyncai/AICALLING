"""
Pounce — /api/campaigns router
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.models.campaign import Campaign
from app.models.lead import Lead

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class CampaignCreate(BaseModel):
    name: str
    description: str = ""
    icp_description: str = ""
    agent_id: uuid.UUID | None = None
    max_concurrent_calls: int = Field(default=1, ge=1, le=20)


class CampaignUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    agent_id: uuid.UUID | None = None
    max_concurrent_calls: int | None = Field(default=None, ge=1, le=20)


class LeadImport(BaseModel):
    # Raw CSV text. Needs a phone column; name/company/email/role are recognised,
    # every other column is stored as a custom field usable as {{column}} in prompts.
    csv: str


class CallSelectedRequest(BaseModel):
    lead_ids: list[uuid.UUID]


def _campaign_to_dict(c: Campaign) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "description": c.description,
        "status": c.status,
        "icp_description": c.icp_description,
        "agent_id": str(c.agent_id) if c.agent_id else None,
        "max_concurrent_calls": c.max_concurrent_calls or 1,
        "total_targets": c.total_targets,
        "total_dialed": c.total_dialed,
        "total_qualified": c.total_qualified,
        "total_booked": c.total_booked,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/")
async def list_campaigns(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    stmt = (
        select(Campaign)
        .order_by(Campaign.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    campaigns = result.scalars().all()
    return {"campaigns": [_campaign_to_dict(c) for c in campaigns]}


@router.get("/{campaign_id}")
async def get_campaign(
    campaign_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return _campaign_to_dict(campaign)


@router.post("/", status_code=201)
async def create_campaign(
    body: CampaignCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    campaign = Campaign(
        id=uuid.uuid4(),
        name=body.name,
        description=body.description,
        icp_description=body.icp_description,
        agent_id=body.agent_id,
        max_concurrent_calls=body.max_concurrent_calls,
        status="draft",
    )
    db.add(campaign)
    await db.commit()
    log.info("campaign_created", campaign_id=str(campaign.id), name=campaign.name)
    return _campaign_to_dict(campaign)


@router.patch("/{campaign_id}")
async def update_campaign(
    campaign_id: uuid.UUID,
    body: CampaignUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(campaign, key, value)
    campaign.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return _campaign_to_dict(campaign)


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(
    campaign_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    await db.execute(delete(Lead).where(Lead.campaign_id == campaign_id))
    await db.delete(campaign)
    await db.commit()


_PHONE_KEYS = ("phone", "phone_number", "mobile", "number", "phone number", "telephone", "cell")
_NAME_KEYS = ("name", "full_name", "full name", "contact", "contact_name", "first_name", "first name")
_KNOWN = {"company": ("company", "company_name", "organization", "business"),
          "email": ("email", "email_address", "e-mail"),
          "role": ("role", "title", "job_title", "position")}


def _normalize_phone(raw: str) -> str:
    raw = (raw or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""
    if raw.startswith("+"):
        return "+" + digits
    if len(digits) == 10:          # assume North American number without country code
        return "+1" + digits
    return "+" + digits


@router.post("/{campaign_id}/leads/import", status_code=201)
async def import_leads(
    campaign_id: uuid.UUID,
    body: LeadImport,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Import leads from CSV text (header row required)."""
    import csv
    import io

    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    reader = csv.DictReader(io.StringIO(body.csv.strip().lstrip("\ufeff")))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV needs a header row")
    cols = {c: (c or "").strip().lower() for c in reader.fieldnames}

    def pick(row: dict, keys: tuple) -> tuple[str, str | None]:
        for orig, low in cols.items():
            if low in keys and (row.get(orig) or "").strip():
                return row[orig].strip(), orig
        return "", None

    if not any(low in _PHONE_KEYS for low in cols.values()):
        raise HTTPException(status_code=400, detail="CSV needs a phone column (e.g. 'phone')")

    created, skipped = 0, 0
    for row in reader:
        phone, phone_col = pick(row, _PHONE_KEYS)
        phone = _normalize_phone(phone)
        if len(phone) < 11:
            skipped += 1
            continue
        name, name_col = pick(row, _NAME_KEYS)
        used = {phone_col, name_col}
        known: dict[str, str] = {}
        for field, keys in _KNOWN.items():
            val, col = pick(row, keys)
            known[field] = val
            used.add(col)
        custom = {
            cols[c].replace(" ", "_"): (v or "").strip()
            for c, v in row.items() if c and c not in used and (v or "").strip()
        }
        db.add(Lead(
            id=uuid.uuid4(), name=name or phone, company=known["company"], phone=phone,
            email=known["email"], role=known["role"], campaign_id=campaign_id,
            intent_source="csv", status="new", custom_fields=custom or None,
        ))
        created += 1

    campaign.total_targets = (campaign.total_targets or 0) + created
    campaign.updated_at = datetime.now(timezone.utc)
    await db.commit()
    log.info("leads_imported", campaign_id=str(campaign_id), created=created, skipped=skipped)
    return {"created": created, "skipped": skipped}


def _ensure_can_dial(campaign: Campaign) -> None:
    from app.config import settings

    if not campaign.agent_id:
        raise HTTPException(status_code=400, detail="Pick an agent for this campaign first.")
    if not settings.phone_ready:
        raise HTTPException(
            status_code=400,
            detail="Phone calling isn't configured yet — see Settings for the keys you need "
                   "(LiveKit, Deepgram, Cartesia, OpenAI and a LiveKit SIP outbound trunk).",
        )


@router.post("/{campaign_id}/start")
async def start_campaign(
    campaign_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Start a campaign:
    1. Set status = running
    2. Enqueue all 'new' leads in background asyncio task
    """
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status not in ("draft", "paused"):
        raise HTTPException(
            status_code=400,
            detail=f"Campaign is {campaign.status}, cannot start",
        )
    _ensure_can_dial(campaign)

    campaign.status = "running"
    campaign.updated_at = datetime.now(timezone.utc)
    await db.commit()

    # Kick off background call queue (asyncio, no Celery)
    background_tasks.add_task(_process_call_queue, str(campaign_id))

    log.info("campaign_started", campaign_id=str(campaign_id))
    return {"message": "Campaign started", "campaign": _campaign_to_dict(campaign)}


@router.post("/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    campaign.status = "paused"
    campaign.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "Campaign paused", "campaign": _campaign_to_dict(campaign)}


@router.post("/{campaign_id}/cancel")
async def cancel_campaign(
    campaign_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    campaign.status = "cancelled"
    campaign.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "Campaign cancelled", "campaign": _campaign_to_dict(campaign)}


@router.get("/{campaign_id}/leads")
async def list_campaign_leads(
    campaign_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    # Verify campaign exists
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Campaign not found")

    stmt = select(Lead).where(Lead.campaign_id == campaign_id)
    if status:
        stmt = stmt.where(Lead.status == status)
    stmt = stmt.order_by(Lead.created_at.desc()).offset((page - 1) * page_size).limit(page_size)

    leads_result = await db.execute(stmt)
    leads = leads_result.scalars().all()

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
                "custom_fields": l.custom_fields or {},
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in leads
        ],
    }


@router.post("/{campaign_id}/call")
async def call_selected_leads(
    campaign_id: uuid.UUID,
    body: CallSelectedRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Fire outbound calls for a specific set of selected leads (checkbox
    selection in the UI). Each lead is dialed via LiveKit SIP outbound using
    its own (editable) phone number — no demo override. Leads with no valid
    phone are skipped server-side with an error logged.
    """
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if not body.lead_ids:
        raise HTTPException(status_code=400, detail="No leads selected")
    _ensure_can_dial(campaign)

    # Only dial leads that actually belong to this campaign.
    rows = await db.execute(
        select(Lead.id).where(
            Lead.campaign_id == campaign_id,
            Lead.id.in_(body.lead_ids),
        )
    )
    valid_ids = [str(r) for r in rows.scalars().all()]
    if not valid_ids:
        raise HTTPException(status_code=404, detail="No matching leads in this campaign")

    # Mark the campaign running so the pipeline/stats reflect live activity.
    if campaign.status in ("draft", "paused"):
        campaign.status = "running"
        campaign.updated_at = datetime.now(timezone.utc)
        await db.commit()

    background_tasks.add_task(_dispatch_selected, str(campaign_id), valid_ids)
    log.info("call_selected", campaign_id=str(campaign_id), count=len(valid_ids))
    return {"dispatched": len(valid_ids), "lead_ids": valid_ids}


async def _dispatch_selected(campaign_id: str, lead_ids: list[str]) -> None:
    """Background task: dial each selected lead sequentially via LiveKit SIP."""
    from app.services.outbound_call import outbound_call_service

    campaign_uuid = uuid.UUID(campaign_id)
    for lid in lead_ids:
        if not await _wait_for_capacity(campaign_uuid):
            break
        async with AsyncSessionLocal() as db:
            lead = await db.get(Lead, uuid.UUID(lid))
            if not lead:
                continue
            try:
                await outbound_call_service.dispatch_call(lead, db)
                campaign = await db.get(Campaign, campaign_uuid)
                if campaign:
                    campaign.total_dialed += 1
                    campaign.updated_at = datetime.now(timezone.utc)
                    await db.commit()
            except Exception as exc:
                log.error("call_selected_dispatch_error", lead_id=lid, error=str(exc))
        await asyncio.sleep(2)

    log.info("call_selected_completed", campaign_id=campaign_id, count=len(lead_ids))


# ── Background call queue processor ──────────────────────────────────────────


_IN_FLIGHT = ("initiated", "ringing", "connected")


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
            if active < (campaign.max_concurrent_calls or 1):
                return True
        await asyncio.sleep(3)


async def _process_call_queue(campaign_id: str) -> None:
    """
    Background asyncio task: dispatch outbound calls for all 'new' leads
    in this campaign sequentially with a small delay between each. Each lead is
    dialed using its own (editable) phone number; leads with no valid phone are
    skipped by dispatch_call's guard. Checks campaign status before each call to
    respect pause/cancel.
    """
    from app.services.outbound_call import outbound_call_service

    log.info("call_queue_started", campaign_id=campaign_id)
    campaign_uuid = uuid.UUID(campaign_id)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Lead)
            .where(Lead.campaign_id == campaign_uuid, Lead.status == "new")
            .order_by(Lead.created_at.asc())
        )
        leads = result.scalars().all()

    log.info("call_queue_leads_found", count=len(leads), campaign_id=campaign_id)

    for lead in leads:
        # Respect pause/cancel and the concurrency limit before each call.
        if not await _wait_for_capacity(campaign_uuid):
            log.info("call_queue_halted", campaign_id=campaign_id)
            return
        async with AsyncSessionLocal() as db:
            c_result = await db.execute(
                select(Campaign).where(Campaign.id == campaign_uuid)
            )
            campaign = c_result.scalar_one_or_none()
            if not campaign or campaign.status != "running":
                log.info(
                    "call_queue_halted",
                    reason=campaign.status if campaign else "not_found",
                    campaign_id=campaign_id,
                )
                return

            try:
                # Re-fetch lead inside this session
                l_result = await db.execute(
                    select(Lead).where(Lead.id == lead.id, Lead.status == "new")
                )
                fresh_lead = l_result.scalar_one_or_none()
                if not fresh_lead:
                    continue  # already called or status changed

                await outbound_call_service.dispatch_call(fresh_lead, db)

                # Increment dialed counter
                campaign.total_dialed += 1
                campaign.updated_at = datetime.now(timezone.utc)
                await db.commit()

            except Exception as exc:
                log.error(
                    "call_queue_dispatch_error",
                    lead_id=str(lead.id),
                    error=str(exc),
                )

        # Brief delay between calls to avoid SIP trunk saturation
        await asyncio.sleep(2)

    async with AsyncSessionLocal() as db:
        campaign = await db.get(Campaign, campaign_uuid)
        if campaign and campaign.status == "running":
            campaign.status = "completed"
            campaign.updated_at = datetime.now(timezone.utc)
            await db.commit()
    log.info("call_queue_completed", campaign_id=campaign_id)
