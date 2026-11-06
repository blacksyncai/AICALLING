"""
Smart Callback Recognition: someone a campaign called rings back.

When an inbound call arrives on one of an account's numbers, `find_match` looks (only inside that account) for the
outbound call the caller is returning: first a call placed from the very number they dialed, else the most recent
call to them from any of the account's numbers. The inbound agent then gets the contact's variables and a short
callback brief (see runtime.callback_brief), and the call is logged with `callback_of` pointing at that outbound call.

Redials: while a callback is being handled the contact's pending retries are held back, and once the caller has
actually spoken, every redial-waiting record for that phone number in the account is closed out, so no campaign
calls them again about something they already called back about.

Caller ID is a matching signal, not proof of identity: the brief tells the agent to confirm who it's talking to
before mentioning anything specific.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.call_log import CallLog
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.services.contacts import normalize_phone

log = structlog.get_logger(__name__)

DEFAULTS: dict = {
    "enabled": True,
    "window_days": 30,          # 7, 30 or 90
    "use_variables": True,      # give the agent the contact's original campaign variables
    "use_summary": True,        # give the agent the last conversation's summary
    "route_original": True,     # answer with the agent that made the outbound call
    "fallback_agent_id": None,  # answers when the original agent can't (and unknown callers on outbound numbers)
    "crm_updates": True,        # callback outcomes sync to the CRM like any other call
}
WINDOWS = (7, 30, 90)
# Contact statuses that mean "waiting on a redial" (campaigns.RETRY_STATUSES) plus not-yet-called.
REDIAL_STATUSES = ("no_answer", "voicemail", "screened", "failed", "new", "calling")
HOLD_MINUTES = 30  # pending retries wait at least this long once a callback starts


def settings_for(org) -> dict:
    raw = dict(getattr(org, "callback_settings", None) or {})
    out = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}
    if out["window_days"] not in WINDOWS:
        out["window_days"] = DEFAULTS["window_days"]
    return out


def clean_settings(body: dict, current: dict | None = None) -> dict:
    """Validate a settings update (unknown keys dropped)."""
    out = {**DEFAULTS, **(current or {})}
    for key in ("enabled", "use_variables", "use_summary", "route_original", "crm_updates"):
        if key in body:
            out[key] = bool(body[key])
    if "window_days" in body:
        try:
            days = int(body["window_days"])
        except (TypeError, ValueError):
            days = 0
        if days not in WINDOWS:
            raise ValueError("The recognition window must be 7, 30 or 90 days.")
        out["window_days"] = days
    if "fallback_agent_id" in body:
        raw = body["fallback_agent_id"]
        if raw in (None, ""):
            out["fallback_agent_id"] = None
        else:
            try:
                out["fallback_agent_id"] = str(uuid.UUID(str(raw)))
            except ValueError:
                raise ValueError("Pick one of your agents as the fallback.") from None
    return out


def _variants(phone: str) -> list[str]:
    """Stored spellings of one number (E.164, and US numbers without the +1 / +)."""
    n = normalize_phone(phone)
    if not n:
        return []
    out = {n, n.lstrip("+")}
    if n.startswith("+1") and len(n) == 12:
        out.add(n[2:])
    return sorted(out)


@dataclass
class Match:
    confidence: str                 # dialed_number | recent_call | ambiguous
    call: CallLog | None            # the outbound call being returned
    lead: Lead | None               # None when ambiguous
    campaign: Campaign | None
    candidates: int = 1


async def find_match(db: AsyncSession, org_id: uuid.UUID, caller: str, dialed: str, window_days: int) -> Match | None:
    """The outbound call this caller is most likely returning, inside one account only."""
    numbers = _variants(caller)
    if not numbers or len(normalize_phone(caller)) < 8:
        return None  # no usable caller ID (restricted, anonymous, junk)
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    rows = (await db.execute(
        select(CallLog).where(CallLog.org_id == org_id, CallLog.call_type == "outbound",
                              CallLog.to_phone.in_(numbers), CallLog.started_at >= since)
        .order_by(CallLog.started_at.desc()).limit(25))).scalars().all()
    if not rows:
        return None
    dialed_n = normalize_phone(dialed)
    from_dialed = [r for r in rows if r.from_phone and normalize_phone(r.from_phone) == dialed_n]
    best, confidence = (from_dialed[0], "dialed_number") if from_dialed else (rows[0], "recent_call")
    pool = from_dialed or rows
    # Different contacts behind the same number (shared or reused line): only trust it when the best match is
    # from the dialed number and that number reached a single contact; otherwise ask who's calling.
    leads = {r.lead_id for r in pool if r.lead_id}
    if len(leads) > 1:
        names = set()
        for lid in leads:
            lead = await db.get(Lead, lid)
            if lead and lead.org_id == org_id:
                names.add((lead.name or "").strip().lower())
        if len(names) > 1:
            return Match("ambiguous", best, None, None, candidates=len(names))
    lead = await db.get(Lead, best.lead_id) if best.lead_id else None
    if lead is not None and lead.org_id != org_id:
        lead = None
    campaign = await db.get(Campaign, best.campaign_id) if best.campaign_id else None
    if campaign is not None and campaign.org_id != org_id:
        campaign = None
    return Match(confidence, best, lead, campaign)


async def contact_leads(db: AsyncSession, org_id: uuid.UUID, caller: str) -> list[Lead]:
    """Every contact record in this account with this phone number (primary or one of its other numbers)."""
    numbers = _variants(caller)
    if not numbers:
        return []
    primary = (await db.execute(select(Lead).where(Lead.org_id == org_id, Lead.phone.in_(numbers)))).scalars().all()
    n = normalize_phone(caller)
    others = (await db.execute(select(Lead).where(
        Lead.org_id == org_id, cast(Lead.phones, String).like(f'%"{n}"%')))).scalars().all()
    seen, out = set(), []
    for lead in [*primary, *others]:
        if lead.id not in seen:
            seen.add(lead.id)
            out.append(lead)
    return out


async def hold_redials(db: AsyncSession, org_id: uuid.UUID, caller: str) -> int:
    """While they're on the phone with us, nothing redials them (decided for good once the call ends)."""
    later = datetime.now(timezone.utc) + timedelta(minutes=HOLD_MINUTES)
    held = 0
    for lead in await contact_leads(db, org_id, caller):
        if lead.status in ("no_answer", "voicemail", "screened", "failed"):
            due = lead.next_attempt_at
            if due is not None and due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            if due is None or due < later:
                lead.next_attempt_at = later
                held += 1
    return held


def caller_spoke(transcript: list[dict] | None) -> bool:
    return any(t.get("role") == "user" and str(t.get("content") or t.get("text") or "").strip()
               for t in (transcript or []) if isinstance(t, dict))


async def stop_redials(db: AsyncSession, org_id: uuid.UUID, caller: str, outcome: str | None,
                       skip: uuid.UUID | None = None) -> int:
    """The caller called back and talked to us: no campaign redials them. Records waiting on a retry move to the
    callback's result (or "completed"); records with a real result keep it."""
    from app.services.contacts import NO_CONVERSATION, next_status

    stopped = 0
    for lead in await contact_leads(db, org_id, caller):
        if lead.id == skip or lead.status not in REDIAL_STATUSES:
            continue
        after = None if outcome in NO_CONVERSATION else next_status(lead.status, outcome)
        lead.status = after or "completed"
        lead.next_attempt_at = None
        lead.updated_at = datetime.now(timezone.utc)
        stopped += 1
    if stopped:
        log.info("callback_redials_stopped", org_id=str(org_id), contacts=stopped)
    return stopped


def _ago(when: datetime | None, now: datetime | None = None) -> str:
    if when is None:
        return "recently"
    now = now or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    days = (now.date() - when.date()).days
    if days <= 0:
        return "earlier today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 14:
        return "last week"
    return f"about {days // 7} weeks ago"


_SPOKE = ("meeting_booked", "qualified", "interested", "not_interested", "callback", "information_requested",
          "potential_follow_up", "transferred", "not_qualified", "completed", "hung_up", "no_decision",
          "do_not_call", "wrong_number", "language_barrier", "insufficient_conversation")


def _safe(text: str | None, limit: int) -> str:
    """Stored text going into the prompt: one line, bounded, no prompt-section markers."""
    t = " ".join(str(text or "").split())
    t = t.replace("#", "").replace('"""', "'").replace("```", "'")
    return t[:limit]


def brief(match: Match, org_name: str, cfg: dict) -> dict:
    """The callback context handed to the agent (runtime.callback_brief renders it)."""
    call, lead = match.call, match.lead
    spoke = bool(call and call.outcome in _SPOKE and (call.duration_seconds or 0) > 0)
    first = ""
    if lead is not None:
        first = _safe((lead.name or "").split(" ")[0], 40)
        if not any(ch.isalpha() for ch in first):
            first = ""
    out = {
        "recognized": match.confidence != "ambiguous",
        "confidence": match.confidence,
        "first_name": first if match.confidence != "ambiguous" else "",
        "business": _safe(org_name, 80),
        "campaign": _safe(match.campaign.name, 80) if match.campaign else "",
        "when": _ago(call.started_at if call else None),
        "previous_outcome": (call.outcome or "") if call else "",
        "spoke_before": spoke,
        "do_not_call": bool(lead and lead.do_not_call),
    }
    if spoke and cfg.get("use_summary") and call and call.summary and match.confidence != "ambiguous":
        out["summary"] = _safe(call.summary, 600)
    return out


def greeting(info: dict) -> str:
    """Opening line for a recognized callback (the agent's own first message is written for outbound calls)."""
    if info.get("recognized") and info.get("first_name"):
        return f"Hi, thanks for calling back! Is this {info['first_name']}?"
    return "Hi, thanks for calling back! Who do I have the pleasure of speaking with?"


async def original_agent(db: AsyncSession, org_id: uuid.UUID, match: Match | None, cfg: dict) -> Agent | None:
    """Who answers a callback on a number with no inbound campaign: the agent that made the call, else the
    account's fallback agent."""
    candidates = []
    if match and match.call and match.call.agent_id and cfg.get("route_original"):
        candidates.append(match.call.agent_id)
    if cfg.get("fallback_agent_id"):
        try:
            candidates.append(uuid.UUID(str(cfg["fallback_agent_id"])))
        except ValueError:
            pass
    for agent_id in candidates:
        agent = await db.get(Agent, agent_id)
        if agent and agent.org_id == org_id and getattr(agent, "status", "active") not in ("archived", "deleted"):
            return agent
    return None


async def record_missed(db: AsyncSession, org_id: uuid.UUID, match: Match | None, caller: str, dialed: str,
                        room: str, reason: str) -> CallLog:
    """A callback nobody could answer: log it on the contact and flag them for a human follow-up (no automatic
    redial)."""
    now = datetime.now(timezone.utc)
    lead = match.lead if match else None
    call = CallLog(id=uuid.uuid4(), org_id=org_id, lead_id=lead.id if lead else None,
                   campaign_id=match.campaign.id if match and match.campaign else None,
                   agent_id=match.call.agent_id if match and match.call else None,
                   call_type="inbound", livekit_room_name=room or f"missed-{uuid.uuid4().hex[:8]}",
                   to_phone=normalize_phone(dialed) or dialed, from_phone=normalize_phone(caller) or caller,
                   status="failed", outcome="missed_callback", started_at=now, ended_at=now, duration_seconds=0,
                   callback_of=match.call.id if match and match.call else None,
                   callback_match=match.confidence if match else None,
                   summary=f"Missed callback: {reason}")
    db.add(call)
    if lead is not None and lead.status in REDIAL_STATUSES:
        lead.status = "callback"  # a person should call them back; campaigns don't redial this status
        lead.next_attempt_at = None
    await db.commit()
    log.info("callback_missed", org_id=str(org_id), call_log_id=str(call.id), reason=reason)
    return call


async def after_call(db: AsyncSession, call: CallLog, outcome: str | None, transcript: list[dict] | None) -> None:
    """When an inbound call from a known number ends with the caller having spoken: stop that number's redials."""
    if call.call_type != "inbound" or not call.org_id or not call.from_phone or not caller_spoke(transcript):
        return
    from app.models.account import Organization

    org = await db.get(Organization, call.org_id)
    if org is None or not settings_for(org)["enabled"]:
        return
    await stop_redials(db, call.org_id, call.from_phone, outcome, skip=call.lead_id)


async def set_settings(db: AsyncSession, org, body: dict) -> dict:
    out = clean_settings(body, settings_for(org))
    if out["fallback_agent_id"]:
        agent = await db.get(Agent, uuid.UUID(out["fallback_agent_id"]))
        if agent is None or agent.org_id != org.id:
            raise ValueError("Pick one of your agents as the fallback.")
    org.callback_settings = out
    return out


__all__ = ["DEFAULTS", "Match", "after_call", "brief", "caller_spoke", "clean_settings", "contact_leads",
           "find_match", "greeting", "hold_redials", "original_agent", "record_missed", "set_settings",
           "settings_for", "stop_redials"]
