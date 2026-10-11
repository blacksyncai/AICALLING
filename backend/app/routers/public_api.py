"""
Public API v1 — for Zapier, Make, n8n or your own code. Authenticate with an
account API key: `Authorization: Bearer bsk_…` (create one under Integrations).
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.services.billing.credits import exact, exact_balance_milli
from app.models.agent import Agent
from app.models.call_log import CallLog
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.routers.calls import call_to_dict
from app.routers.contacts import contact_to_dict
from app.services.accounts import InsufficientCredits, emit_event
from app.services.auth import ApiOrgDep, DbDep
from app.services.contacts import normalize_phone

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["public api"])


class ContactCreate(BaseModel):
    name: str = ""
    phone: str
    email: str = ""
    company: str = ""
    role: str = ""
    notes: str = ""
    tags: list[str] = []
    campaign_id: uuid.UUID | None = None
    # Optional: have this agent call the contact right away.
    call_with_agent_id: uuid.UUID | None = None


class CallCreate(BaseModel):
    agent_id: uuid.UUID
    to_phone: str | None = None
    contact_id: uuid.UUID | None = None


async def _agent(db, org, agent_id: uuid.UUID) -> Agent:
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org.id:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def _place_call(db, org, agent: Agent, lead: Lead | None, to_phone: str | None) -> CallLog:
    from app.services.outbound_call import CallSetupError, call_service

    try:
        return await call_service.dispatch_call(lead, db, agent=agent, to_phone=to_phone)
    except InsufficientCredits as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    except (CallSetupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/me")
async def whoami(org: ApiOrgDep):
    """Check a key works (used by Zapier's connection test)."""
    return {"account_id": str(org.id), "account_name": org.name, "credits_balance": exact(exact_balance_milli(org)),
            "unlimited_credits": org.unlimited_credits}


@router.get("/agents")
async def list_agents(org: ApiOrgDep, db: DbDep):
    agents = (await db.execute(select(Agent).where(Agent.org_id == org.id).order_by(Agent.created_at))).scalars()
    return {"agents": [{"id": str(a.id), "name": a.name, "status": a.status} for a in agents]}


@router.get("/campaigns")
async def list_campaigns(org: ApiOrgDep, db: DbDep):
    rows = (await db.execute(select(Campaign).where(Campaign.org_id == org.id)
                             .order_by(Campaign.created_at.desc()))).scalars()
    return {"campaigns": [{"id": str(c.id), "name": c.name, "status": c.status} for c in rows]}


@router.get("/contacts")
async def list_contacts(org: ApiOrgDep, db: DbDep, phone: str | None = None,
                        limit: int = Query(default=50, ge=1, le=200)):
    stmt = select(Lead).where(Lead.org_id == org.id)
    if phone:
        stmt = stmt.where(Lead.phone == normalize_phone(phone))
    rows = (await db.execute(stmt.order_by(Lead.created_at.desc()).limit(limit))).scalars()
    return {"contacts": [contact_to_dict(l) for l in rows]}


@router.post("/contacts", status_code=201)
async def create_contact(body: ContactCreate, org: ApiOrgDep, db: DbDep):
    """Add a contact (e.g. a new form fill), optionally to a campaign, optionally calling them now."""
    phone = normalize_phone(body.phone)
    if len(phone) < 11:
        raise HTTPException(status_code=400, detail="Enter a valid phone number, e.g. +14155550123.")
    campaign = None
    if body.campaign_id:
        campaign = await db.get(Campaign, body.campaign_id)
        if not campaign or campaign.org_id != org.id:
            raise HTTPException(status_code=404, detail="Campaign not found")
    agent = await _agent(db, org, body.call_with_agent_id) if body.call_with_agent_id else None
    lead = Lead(
        id=uuid.uuid4(), org_id=org.id, name=body.name.strip() or phone, phone=phone, email=body.email.strip(),
        company=body.company.strip(), role=body.role.strip(), notes=body.notes.strip() or None,
        tags=[t.strip() for t in body.tags if t.strip()][:20] or None,
        campaign_id=campaign.id if campaign else None, intent_source="api", status="new",
    )
    db.add(lead)
    if campaign:
        campaign.total_targets = (campaign.total_targets or 0) + 1
    await db.commit()
    data = contact_to_dict(lead, campaign.name if campaign else None)
    await emit_event(org.id, "contact.created", data)
    if agent:
        call = await _place_call(db, org, agent, lead, None)
        data["call_id"] = str(call.id)
    return data


@router.post("/calls", status_code=201)
async def create_call(body: CallCreate, org: ApiOrgDep, db: DbDep):
    """Have an agent call a contact (contact_id) or any number (to_phone) now."""
    agent = await _agent(db, org, body.agent_id)
    lead = None
    if body.contact_id:
        lead = await db.get(Lead, body.contact_id)
        if not lead or lead.org_id != org.id:
            raise HTTPException(status_code=404, detail="Contact not found")
    elif not body.to_phone:
        raise HTTPException(status_code=400, detail="Send contact_id or to_phone.")
    call = await _place_call(db, org, agent, lead, body.to_phone)
    return {"call_id": str(call.id), "status": call.status, "to_phone": call.to_phone}


@router.get("/calls")
async def list_calls(org: ApiOrgDep, db: DbDep, limit: int = Query(default=25, ge=1, le=100)):
    rows = (await db.execute(
        select(CallLog, Lead, Agent, Campaign)
        .outerjoin(Lead, Lead.id == CallLog.lead_id)
        .outerjoin(Agent, Agent.id == CallLog.agent_id)
        .outerjoin(Campaign, Campaign.id == CallLog.campaign_id)
        .where(CallLog.org_id == org.id).order_by(CallLog.started_at.desc()).limit(limit)
    )).all()
    return {"calls": [call_to_dict(c, l, a, cp) for c, l, a, cp in rows]}


@router.get("/calls/{call_id}")
async def get_call(call_id: uuid.UUID, org: ApiOrgDep, db: DbDep):
    row = (await db.execute(
        select(CallLog, Lead, Agent, Campaign)
        .outerjoin(Lead, Lead.id == CallLog.lead_id)
        .outerjoin(Agent, Agent.id == CallLog.agent_id)
        .outerjoin(Campaign, Campaign.id == CallLog.campaign_id)
        .where(CallLog.org_id == org.id, CallLog.id == call_id)
    )).first()
    if not row:
        raise HTTPException(status_code=404, detail="Call not found")
    return call_to_dict(*row, full=True)
