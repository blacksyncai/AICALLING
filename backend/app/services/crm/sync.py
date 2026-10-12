"""
Keeps connected CRMs in step with BlackSync:

- push_call: after every finished phone call, find/create the contact in each CRM
  and log the call (summary, outcome, duration, meeting, link to the recording).
- import_contacts: pull a CRM's contacts into BlackSync's contact list.
- speed-to-lead: every minute, look for leads created in a CRM since the last check
  and have the chosen agent call them (during 8 AM–9 PM in the account's time zone).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from sqlalchemy import delete, func, select

from app.config import settings as app_settings
from app.models.account import Organization
from app.models.agent import Agent
from app.models.crm import CrmConnection, CrmSyncLog
from app.models.lead import Lead
from app.services import secret_store
from app.services.contacts import normalize_phone
from app.services.crm.http import CrmError
from app.services.crm.providers import PROVIDERS, CallInfo, Contact, Provider

log = structlog.get_logger(__name__)
UTC = dt.timezone.utc
_BACKGROUND: set[asyncio.Task] = set()
POLL_SECONDS = 60
KEEP_LOGS = 200
CALL_HOURS = (8, 21)  # local time window for speed-to-lead calls


def defaults() -> dict:
    return {"log_calls": True, "create_contacts": True, "only_connected": False,
            "speed_to_lead_agent_id": None, "speed_to_lead_since": None}


def conn_settings(conn: CrmConnection) -> dict:
    return {**defaults(), **(conn.settings or {})}


def provider_of(conn: CrmConnection) -> Provider:
    p = PROVIDERS.get(conn.provider)
    if not p:
        raise CrmError(f"Unknown integration {conn.provider}.")
    return p


def http_for(conn: CrmConnection):
    p = provider_of(conn)
    secret = secret_store.decrypt_value(conn.secret_enc) if conn.secret_enc else ""
    if conn.method != "nango" and not secret:
        raise CrmError("The saved key can't be read. Reconnect this integration.")
    return p, p.http(secret, conn.config or {})


async def add_log(db, conn: CrmConnection, kind: str, status: str, message: str,
                  call_id: uuid.UUID | None = None, external_id: str | None = None) -> None:
    db.add(CrmSyncLog(org_id=conn.org_id, connection_id=conn.id, call_id=call_id, kind=kind, status=status,
                      message=message[:1000], external_id=(external_id or None) and str(external_id)[:128]))
    if status == "error":
        conn.status, conn.last_error = "error", message[:1000]
    else:
        conn.status, conn.last_error, conn.last_synced_at = "connected", None, dt.datetime.now(UTC)
    await db.flush()
    # Keep the activity list short.
    count = await db.scalar(select(func.count()).select_from(CrmSyncLog).where(CrmSyncLog.connection_id == conn.id))
    if count and count > KEEP_LOGS + 50:
        old = (await db.execute(select(CrmSyncLog.id).where(CrmSyncLog.connection_id == conn.id)
                                .order_by(CrmSyncLog.created_at.desc()).offset(KEEP_LOGS))).scalars().all()
        await db.execute(delete(CrmSyncLog).where(CrmSyncLog.id.in_(old)))


# ── Calls → CRM ───────────────────────────────────────────────────────────────


def call_info(data: dict) -> CallInfo:
    started = data.get("started_at")
    if isinstance(started, str):
        try:
            started = dt.datetime.fromisoformat(started.replace("Z", "+00:00"))
        except ValueError:
            started = None
    base = (app_settings.app_url or "").rstrip("/")
    return CallInfo(
        call_id=str(data.get("call_id") or ""), outcome=data.get("outcome") or "", summary=data.get("summary") or "",
        duration_seconds=int(data.get("duration_seconds") or 0), phone=data.get("to_phone") or "",
        agent_name=data.get("agent_name") or "", meeting_time=data.get("meeting_time") or "",
        meeting_link=data.get("meeting_link") or "", started_at=started,
        url=f"{base}/calls/{data.get('call_id')}" if base and data.get("call_id") else "",
        extracted=data.get("extracted_data") or {},
    )


async def push_call_to(db, conn: CrmConnection, data: dict) -> None:
    cfg = conn_settings(conn)
    call = call_info(data)
    if not cfg["log_calls"] or (cfg["only_connected"] and not call.connected):
        return
    contact = data.get("contact") or {}
    lead = await db.get(Lead, uuid.UUID(contact["id"])) if contact.get("id") else None
    c = Contact(name=contact.get("name") or "", phone=contact.get("phone") or call.phone,
                email=contact.get("email") or data.get("prospect_email") or "", company=contact.get("company") or "")
    try:
        p, http = http_for(conn)
        ref = ((lead.crm_refs or {}) if lead else {}).get(conn.provider)
        if not ref:
            ref = await p.find_or_create(http, conn.config or {}, c, create=cfg["create_contacts"])
        if not ref:
            await add_log(db, conn, "call", "ok", f"Skipped {c.phone}: not in {p.name} (creating contacts is off).",
                          call_id=uuid.UUID(call.call_id) if call.call_id else None)
            return
        await p.log_call(http, conn.config or {}, ref, call)
        if call.outcome == "do_not_call":
            try:
                await p.mark_dnc(http, conn.config or {}, ref)
            except CrmError as exc:
                log.warning("crm_mark_dnc_failed", provider=conn.provider, error=str(exc))
        if lead and (lead.crm_refs or {}).get(conn.provider) != ref:
            lead.crm_refs = {**(lead.crm_refs or {}), conn.provider: ref}
        await add_log(db, conn, "call", "ok", f"Logged {call.outcome_label.lower()} call with {c.name or c.phone}.",
                      call_id=uuid.UUID(call.call_id) if call.call_id else None, external_id=ref)
    except (CrmError, KeyError, ValueError, TypeError) as exc:
        log.warning("crm_push_failed", provider=conn.provider, error=str(exc))
        await add_log(db, conn, "call", "error", f"Couldn't log the call with {c.name or c.phone}: {exc}",
                      call_id=uuid.UUID(call.call_id) if call.call_id else None)


async def push_call(org_id: uuid.UUID, data: dict) -> None:
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        conns = (await db.execute(select(CrmConnection).where(CrmConnection.org_id == org_id))).scalars().all()
        for conn in conns:
            await push_call_to(db, conn, data)
        await db.commit()


def schedule_push(org_id: uuid.UUID | None, data: dict) -> None:
    if not org_id:
        return
    task = asyncio.create_task(push_call(org_id, data))
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


# ── CRM → contacts ────────────────────────────────────────────────────────────


async def save_contacts(db, conn: CrmConnection, contacts: list[Contact], tag: str,
                        extra_tags: list[str] | None = None) -> tuple[list[Lead], int]:
    """Create or update Leads for CRM contacts (matched by phone). Returns (new leads, updated count).

    CRM do-not-call contacts are saved with do_not_call set, so no agent ever dials them;
    the CRM's stage, tags and contacted flag land in custom fields ({{crm_stage}} etc.).
    """
    existing = {normalize_phone(l.phone): l for l in (await db.execute(
        select(Lead).where(Lead.org_id == conn.org_id))).scalars().all()}
    created, updated = [], 0
    p = provider_of(conn)
    for c in contacts:
        phone = normalize_phone(c.phone)
        if len(phone) < 8:
            continue
        crm_fields = {k: v for k, v in {
            "crm": p.name, "crm_stage": c.stage, "crm_tags": ", ".join(c.tags[:20]),
            "crm_contacted": None if c.contacted is None else ("yes" if c.contacted else "no"),
        }.items() if v not in (None, "")}
        lead = existing.get(phone)
        if lead:
            changed = False
            if (lead.crm_refs or {}).get(conn.provider) != c.external_id:
                lead.crm_refs = {**(lead.crm_refs or {}), conn.provider: c.external_id}
                changed = True
            if c.dnc and not lead.do_not_call:
                lead.do_not_call, changed = True, True
            lead.custom_fields = {**(lead.custom_fields or {}), **crm_fields}
            updated += changed
            continue
        tags = list(dict.fromkeys([p.name, tag, *(extra_tags or [])]))
        lead = Lead(org_id=conn.org_id, name=c.name or phone, phone=phone, email=c.email or "", company=c.company or "",
                    intent_source=p.key, crm_refs={conn.provider: c.external_id}, tags=[t for t in tags if t],
                    custom_fields=crm_fields or None, do_not_call=bool(c.dnc))
        db.add(lead)
        existing[phone] = lead
        created.append(lead)
    await db.flush()
    return created, updated


def _apply_skips(contacts: list[Contact], skip_contacted: bool) -> tuple[list[Contact], dict]:
    dnc = sum(1 for c in contacts if c.dnc)
    contacted = [c for c in contacts if c.contacted and not c.dnc]
    keep = [c for c in contacts if not (skip_contacted and c.contacted)]
    return keep, {"do_not_call": dnc, "contacted": len(contacted), "skipped_contacted": len(contacts) - len(keep)}


async def preview_import(db, conn: CrmConnection, filters: dict | None, skip_contacted: bool, limit: int = 500) -> dict:
    p, http = http_for(conn)
    contacts = await p.list_contacts(http, conn.config or {}, limit=limit, filters=filters or {})
    keep, counts = _apply_skips(contacts, skip_contacted)
    known = {normalize_phone(x) for x in (await db.execute(select(Lead.phone).where(Lead.org_id == conn.org_id))).scalars()}
    return {
        "found": len(contacts), "will_import": len([c for c in keep if normalize_phone(c.phone) not in known]),
        "already_in_blacksync": len([c for c in keep if normalize_phone(c.phone) in known]), **counts,
        "sample": [{"name": c.name, "phone": c.phone, "stage": c.stage, "tags": c.tags[:5], "dnc": c.dnc,
                    "contacted": c.contacted} for c in keep[:8]],
    }


async def import_contacts(db, conn: CrmConnection, limit: int = 500, filters: dict | None = None,
                          skip_contacted: bool = False, list_tag: str = "") -> dict:
    p, http = http_for(conn)
    contacts = await p.list_contacts(http, conn.config or {}, limit=limit, filters=filters or {})
    keep, counts = _apply_skips(contacts, skip_contacted)
    created, updated = await save_contacts(db, conn, keep, "Imported", [list_tag.strip()[:60]] if list_tag.strip() else None)
    dnc_new = sum(1 for l in created if l.do_not_call)
    msg = f"Imported {len(created)} new contact{'s' if len(created) != 1 else ''} from {p.name}" + (
        f", updated {updated} existing" if updated else "") + (
        f"; {counts['do_not_call']} marked do-not-call won't be dialed" if counts["do_not_call"] else "") + "."
    await add_log(db, conn, "import", "ok", msg)
    return {"found": len(contacts), "created": len(created), "linked": updated, "do_not_call": counts["do_not_call"],
            "do_not_call_new": dnc_new, "skipped_contacted": counts["skipped_contacted"]}


# ── Speed to lead ─────────────────────────────────────────────────────────────


def _in_hours(org: Organization | None, now: dt.datetime) -> bool:
    try:
        zone = ZoneInfo((org.timezone if org else None) or "America/New_York")
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("America/New_York")
    local = now.astimezone(zone)
    return CALL_HOURS[0] <= local.hour < CALL_HOURS[1]


async def _call_lead(db, conn: CrmConnection, agent: Agent, lead: Lead) -> str:
    from app.services.outbound_call import call_service

    call = await call_service.dispatch_call(lead, db, agent=agent)
    return str(call.id)


async def check_new_leads(db, conn: CrmConnection, now: dt.datetime | None = None) -> int:
    """Import leads created since the last check and call them. Returns calls started."""
    now = now or dt.datetime.now(UTC)
    cfg = conn_settings(conn)
    agent_id = cfg.get("speed_to_lead_agent_id")
    if not agent_id:
        return 0
    agent = await db.get(Agent, uuid.UUID(agent_id))
    if not agent or agent.org_id != conn.org_id:
        conn.settings = {**cfg, "speed_to_lead_agent_id": None}
        await add_log(db, conn, "new_lead", "error", "Speed to lead was turned off: its agent no longer exists.")
        return 0
    since = dt.datetime.fromisoformat(cfg["speed_to_lead_since"]) if cfg.get("speed_to_lead_since") else now
    pending: list[str] = list(cfg.get("pending") or [])
    try:
        p, http = http_for(conn)
        fresh = [c for c in await p.list_contacts(http, conn.config or {}, limit=50, since=since)
                 if not c.created_at or c.created_at > since]
    except CrmError as exc:
        await add_log(db, conn, "new_lead", "error", f"Couldn't check {conn.provider} for new leads: {exc}")
        return 0
    newest = max([c.created_at for c in fresh if c.created_at] + [since])
    created, _ = await save_contacts(db, conn, fresh, "Speed to lead")
    for lead in created:
        await add_log(db, conn, "new_lead", "ok", f"New lead {lead.name} ({lead.phone}).", external_id=(lead.crm_refs or {}).get(conn.provider))
    pending += [str(l.id) for l in created]
    started = 0
    org = await db.get(Organization, conn.org_id)
    if pending and _in_hours(org, now):
        for lid in pending[:10]:
            lead = await db.get(Lead, uuid.UUID(lid))
            pending.remove(lid)
            if not lead or lead.do_not_call:
                continue
            try:
                await _call_lead(db, conn, agent, lead)
                started += 1
                await add_log(db, conn, "new_lead", "ok", f"{agent.name} is calling {lead.name} now.")
            except Exception as exc:  # credits, phone setup, bad number…
                await add_log(db, conn, "new_lead", "error", f"Couldn't call {lead.name}: {exc}")
    conn.settings = {**cfg, "speed_to_lead_since": newest.isoformat(), "pending": pending[-200:]}
    return started


async def poll_once() -> None:
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        conns = (await db.execute(select(CrmConnection))).scalars().all()
        ids = [c.id for c in conns if (c.settings or {}).get("speed_to_lead_agent_id")]
    for cid in ids:
        async with AsyncSessionLocal() as db:
            conn = await db.get(CrmConnection, cid)
            if conn:
                try:
                    await check_new_leads(db, conn)
                    await db.commit()
                except Exception as exc:
                    await db.rollback()
                    log.warning("speed_to_lead_failed", connection=str(cid), error=str(exc))


async def _poll_loop() -> None:
    while True:
        await asyncio.sleep(POLL_SECONDS)
        try:
            await poll_once()
        except Exception as exc:
            log.warning("crm_poll_failed", error=str(exc))


def start_poll_loop() -> asyncio.Task:
    task = asyncio.create_task(_poll_loop())
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)
    return task
