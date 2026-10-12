"""
Inbound calls: an account's own number answered by one of its agents.

Wiring (all in the platform's LiveKit project):
  Twilio number → Elastic SIP trunk origination → LiveKit inbound trunk (the number must be in its
  list) → dispatch rule (a room per call, with our agent dispatched into it) → the worker asks
  /internal/inbound-call which agent owns the dialed number.

A live inbound campaign sets PhoneNumber.inbound_agent_id / inbound_campaign_id; pausing clears them.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import structlog
from livekit import api
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.agent import Agent
from app.models.billing import PhoneNumber
from app.models.call_log import CallLog
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.services.contacts import normalize_phone

log = structlog.get_logger(__name__)


class InboundError(RuntimeError):
    pass


def _lk() -> api.LiveKitAPI:
    return api.LiveKitAPI(url=settings.livekit_http_url, api_key=settings.livekit_api_key,
                          api_secret=settings.livekit_api_secret)


async def _inbound_trunk(lk: api.LiveKitAPI):
    trunks = (await lk.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())).items
    if not trunks:
        raise InboundError("Inbound calling isn't set up on the platform yet (no LiveKit inbound trunk).")
    want = getattr(settings, "livekit_sip_inbound_trunk_id", "") or ""
    return next((t for t in trunks if t.sip_trunk_id == want), None) or trunks[0]


async def ensure_routing(number: str) -> None:
    """Make sure calls to `number` reach LiveKit and get our agent: number on the inbound trunk, agent on the rule."""
    if not settings.livekit_ready:
        raise InboundError("Voice isn't configured on the platform.")
    lk = _lk()
    try:
        trunk = await _inbound_trunk(lk)
        if trunk.numbers and number not in trunk.numbers:
            await lk.sip.update_inbound_trunk_fields(trunk.sip_trunk_id, numbers=api.ListUpdate(add=[number]))
        agent_name = settings.livekit_agent_name or "closer"
        rules = (await lk.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())).items
        rule = next((r for r in rules if not r.trunk_ids or trunk.sip_trunk_id in r.trunk_ids), None)
        meta = json.dumps({"call_type": "inbound"})
        if rule is None:
            await lk.sip.create_dispatch_rule(api.CreateSIPDispatchRuleRequest(
                rule=api.SIPDispatchRule(dispatch_rule_individual=api.SIPDispatchRuleIndividual(room_prefix="call-")),
                trunk_ids=[trunk.sip_trunk_id], name="BlackSync inbound",
                room_config=api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=agent_name, metadata=meta)])))
        elif not any(a.agent_name == agent_name for a in rule.room_config.agents):
            info = api.SIPDispatchRuleInfo()
            info.CopyFrom(rule)
            info.room_config.agents.append(api.RoomAgentDispatch(agent_name=agent_name, metadata=meta))
            await lk.sip.update_dispatch_rule(rule.sip_dispatch_rule_id, info)
            log.info("inbound_dispatch_agent_added", rule=rule.sip_dispatch_rule_id)
    finally:
        await lk.aclose()


async def campaign_number(db: AsyncSession, campaign: Campaign) -> PhoneNumber | None:
    if not campaign.phone_number_id:
        return None
    row = await db.get(PhoneNumber, campaign.phone_number_id)
    return row if row and row.org_id == campaign.org_id and row.status == "active" else None


async def activate(db: AsyncSession, campaign: Campaign) -> PhoneNumber:
    """Point the campaign's number at its agent (another live campaign on the number is paused)."""
    row = await campaign_number(db, campaign)
    if not row:
        raise InboundError("Pick one of your phone numbers for this inbound campaign.")
    if not campaign.agent_id:
        raise InboundError("Pick the agent that answers.")
    if row.inbound_campaign_id and row.inbound_campaign_id != campaign.id:
        other = await db.get(Campaign, row.inbound_campaign_id)
        if other and other.status == "running":
            other.status = "paused"
    await ensure_routing(row.number)
    row.inbound_agent_id, row.inbound_campaign_id = campaign.agent_id, campaign.id
    return row


async def deactivate(db: AsyncSession, campaign: Campaign) -> None:
    row = await campaign_number(db, campaign)
    if row and row.inbound_campaign_id == campaign.id:
        row.inbound_agent_id = row.inbound_campaign_id = None


async def route_call(db: AsyncSession, to_number: str, from_number: str, room: str) -> dict | None:
    """The agent config + a new call log for an inbound call, or None when nobody answers this number."""
    from app.agent.runtime import agent_to_runtime, lead_variables

    to_n = "+" + normalize_phone(to_number).lstrip("+") if to_number else ""
    row = (await db.execute(select(PhoneNumber).where(PhoneNumber.number == to_n, PhoneNumber.status == "active"))).scalar_one_or_none()
    if not row or not row.inbound_agent_id:
        return None
    agent = await db.get(Agent, row.inbound_agent_id)
    if not agent or agent.org_id != row.org_id:
        return None
    from app.models.account import Organization
    from app.services.accounts import InsufficientCredits, ensure_can_call
    from app.services.billing.credits import reserve_for_call

    org = await db.get(Organization, row.org_id)
    if org is None:
        return None
    try:
        ensure_can_call(org)
        max_seconds, rate, reserved = await reserve_for_call(db, org, agent, agent.max_duration_seconds or 600)
    except InsufficientCredits:
        log.warning("inbound_call_no_credits", to=row.number)
        return None
    caller = normalize_phone(from_number or "")
    lead = None
    if caller:
        lead = (await db.execute(select(Lead).where(Lead.org_id == row.org_id, Lead.phone == caller).limit(1))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    call = CallLog(id=uuid.uuid4(), org_id=row.org_id, agent_id=agent.id, lead_id=lead.id if lead else None,
                   campaign_id=row.inbound_campaign_id, call_type="inbound", livekit_room_name=room,
                   to_phone=row.number, from_phone=caller or from_number, status="connected", started_at=now, answered_at=now,
                   credits_reserved=reserved, credit_rate=rate)
    db.add(call)
    await db.commit()
    variables = lead_variables(lead) if lead else {"phone": caller}
    log.info("inbound_call_routed", to=row.number, agent=agent.name, call_log_id=str(call.id), known_caller=bool(lead))
    cfg = agent_to_runtime(agent, secrets=True)
    cfg["max_duration_seconds"] = min(cfg.get("max_duration_seconds") or 600, max_seconds)
    return {"agent": cfg, "agent_id": str(agent.id), "call_type": "inbound",
            "call_log_id": str(call.id), "variables": variables}
