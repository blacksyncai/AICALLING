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
    # create_contacts is off by default: a test call to your own number shouldn't add a "lead" to the CRM.
    return {"log_calls": True, "create_contacts": False, "only_connected": False,
            "speed_to_lead_agent_id": None, "speed_to_lead_since": None, "activity_agent_id": None}


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
        moved = await _move_installed_deal(db, conn, p, http, lead, call.outcome) or \
            await _move_stage(db, conn, p, http, ref, call, c)
        if lead and (lead.crm_refs or {}).get(conn.provider) != ref:
            lead.crm_refs = {**(lead.crm_refs or {}), conn.provider: ref}
        await add_log(db, conn, "call", "ok", f"Logged {call.outcome_label.lower()} call with {c.name or c.phone}."
                      + (f" {moved}." if moved else ""),
                      call_id=uuid.UUID(call.call_id) if call.call_id else None, external_id=ref)
    except (CrmError, KeyError, ValueError, TypeError) as exc:
        log.warning("crm_push_failed", provider=conn.provider, error=str(exc))
        await add_log(db, conn, "call", "error", f"Couldn't log the call with {c.name or c.phone}: {exc}",
                      call_id=uuid.UUID(call.call_id) if call.call_id else None)


async def _move_stage(db, conn: CrmConnection, p: Provider, http, ref: str, call: CallInfo, c: Contact) -> str | None:
    """Pipeline sync: move the contact's deal to the stage mapped to this call's result."""
    sync_cfg = (conn.settings or {}).get("pipeline") or {}
    pipeline = sync_cfg.get("snapshot")
    stage_id = (sync_cfg.get("map") or {}).get(call.outcome or "")
    if not p.pipeline_noun or not pipeline or not stage_id:
        return None
    try:
        return await p.set_stage(http, conn.config or {}, ref, pipeline, stage_id,
                                 create=bool(sync_cfg.get("create", True)),
                                 forward_only=bool(sync_cfg.get("forward_only", True)), name=c.name or c.phone)
    except CrmError as exc:
        log.warning("crm_stage_move_failed", provider=conn.provider, error=str(exc))
        return f"Couldn't move the {p.pipeline_noun}: {exc}"


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


# ── BlackSync pipeline inside the CRM (drag a card into the queue → the agent calls) ──

BLACKSYNC_STAGES = [
    {"key": "queued", "label": "Queued for AI call", "kind": "active"},
    {"key": "calling", "label": "AI calling", "kind": "active"},
    {"key": "no_answer", "label": "No answer (AI will retry)", "kind": "active"},
    {"key": "voicemail", "label": "Voicemail left", "kind": "active"},
    {"key": "follow_up", "label": "Talked - needs follow-up", "kind": "active"},
    {"key": "booked", "label": "Meeting booked by AI", "kind": "active"},
    {"key": "not_interested", "label": "Not interested", "kind": "lost"},
    {"key": "dnc", "label": "Do not call", "kind": "lost"},
]
OUTCOME_TO_KEY = {
    "meeting_booked": "booked", "interested": "follow_up", "qualified": "follow_up", "callback": "follow_up",
    "completed": "follow_up", "transferred": "follow_up", "voicemail": "voicemail", "no_answer": "no_answer",
    "failed": "no_answer", "not_interested": "not_interested", "not_qualified": "not_interested",
    "wrong_number": "not_interested", "do_not_call": "dnc",
}
QUEUE_BATCH = 5
MAX_TRIES = 3
RETRY_AFTER = dt.timedelta(hours=4)


def _installs(conn: CrmConnection) -> list[dict]:
    return list((conn.settings or {}).get("installs") or [])


def _stage(install: dict, key: str) -> str | None:
    return next((st["id"] for st in install["pipeline"]["stages"] if st.get("key") == key), None)


async def install_pipeline(db, conn: CrmConnection, agent: Agent) -> dict:
    p, http = http_for(conn)
    if not p.can_install:
        raise CrmError(f"{p.name} doesn't support a BlackSync pipeline yet.")
    pipe = await p.install_pipeline(http, conn.config or {}, f"BlackSync AI · {agent.name}"[:60], BLACKSYNC_STAGES)
    installs = [i for i in _installs(conn) if i.get("agent_id") != str(agent.id)]
    installs.append({"agent_id": str(agent.id), "agent_name": agent.name, "pipeline": pipe})
    conn.settings = {**(conn.settings or {}), "installs": installs}
    await add_log(db, conn, "test", "ok", f"Created the “{pipe['name']}” pipeline in {p.name}. Drag a card into "
                  f"“Queued for AI call” and {agent.name} calls them.")
    return pipe


async def remove_install(db, conn: CrmConnection, agent_id: str) -> None:
    conn.settings = {**(conn.settings or {}), "installs": [i for i in _installs(conn) if i.get("agent_id") != agent_id]}


async def refresh_context(db, conn: CrmConnection, lead: Lead) -> None:
    """Pull the CRM's notes/last touches for a contact into {{crm_context}} for the agent."""
    ref = (lead.crm_refs or {}).get(conn.provider)
    if not ref:
        return
    p, http = http_for(conn)
    text = await p.context(http, conn.config or {}, ref)
    if text:
        lead.custom_fields = {**(lead.custom_fields or {}), "crm_context": text,
                              "crm_context_at": dt.datetime.now(UTC).isoformat()}


async def ensure_context(db, lead: Lead, max_age: dt.timedelta = dt.timedelta(hours=12)) -> None:
    """Before a call: refresh {{crm_context}} for a CRM-linked contact if it's missing or stale."""
    refs = lead.crm_refs or {}
    if not refs or not lead.org_id:
        return
    at = (lead.custom_fields or {}).get("crm_context_at")
    if at:
        try:
            if dt.datetime.now(UTC) - dt.datetime.fromisoformat(at) < max_age:
                return
        except ValueError:
            pass
    conns = (await db.execute(select(CrmConnection).where(CrmConnection.org_id == lead.org_id,
                                                         CrmConnection.provider.in_(list(refs))))).scalars().all()
    for conn in conns:
        try:
            await asyncio.wait_for(refresh_context(db, conn, lead), timeout=4)
        except (CrmError, asyncio.TimeoutError) as exc:
            log.info("crm_context_skipped", provider=conn.provider, error=str(exc))


async def process_queue(db, conn: CrmConnection, now: dt.datetime | None = None) -> int:
    """Dial cards waiting in each BlackSync pipeline's queue stage. Returns calls started."""
    now = now or dt.datetime.now(UTC)
    installs = _installs(conn)
    if not installs:
        return 0
    org = await db.get(Organization, conn.org_id)
    if not _in_hours(org, now):
        return 0
    p, http = http_for(conn)
    started = 0
    skipped = set((conn.settings or {}).get("queue_skipped") or [])
    for inst in installs:
        agent = await db.get(Agent, uuid.UUID(inst["agent_id"]))
        queue_id, calling_id = _stage(inst, "queued"), _stage(inst, "calling")
        if not agent or agent.org_id != conn.org_id or not queue_id:
            continue
        # Retry no-answers: back into the queue after RETRY_AFTER, up to MAX_TRIES calls in total.
        no_answer_id = _stage(inst, "no_answer")
        if no_answer_id:
            try:
                for it in await p.queued(http, conn.config or {}, no_answer_id, limit=25):
                    c0 = it.get("contact")
                    if not c0:
                        continue
                    lead0 = (await db.execute(select(Lead).where(Lead.org_id == conn.org_id,
                                                                 Lead.phone == normalize_phone(c0.phone)))).scalars().first()
                    tries = int(((lead0.custom_fields or {}) if lead0 else {}).get("bs_tries") or 0)
                    last = lead0.last_called_at if lead0 else None
                    if last and last.tzinfo is None:
                        last = last.replace(tzinfo=UTC)
                    if lead0 and tries < MAX_TRIES and (not last or now - last >= RETRY_AFTER):
                        await p.move_deal(http, conn.config or {}, it["deal_id"], queue_id)
            except CrmError as exc:
                log.warning("blacksync_retry_failed", error=str(exc))
        try:
            items = await p.queued(http, conn.config or {}, queue_id, limit=QUEUE_BATCH + len(skipped))
        except CrmError as exc:
            await add_log(db, conn, "new_lead", "error", f"Couldn't read the {inst['pipeline']['name']} queue: {exc}")
            continue
        for it in items:
            if it["deal_id"] in skipped or started >= QUEUE_BATCH:
                continue
            c: Contact | None = it.get("contact")
            if not c or len(normalize_phone(c.phone)) < 8:
                skipped.add(it["deal_id"])
                await add_log(db, conn, "new_lead", "error", f"Skipped a queued card in {inst['pipeline']['name']}: no phone number.")
                continue
            created, _ = await save_contacts(db, conn, [c], "BlackSync pipeline")
            lead = created[0] if created else (await db.execute(select(Lead).where(
                Lead.org_id == conn.org_id, Lead.phone == normalize_phone(c.phone)))).scalars().first()
            if lead is None:
                continue
            tries = int((lead.custom_fields or {}).get("bs_tries") or 0) if (lead.custom_fields or {}).get("bs_deal") == it["deal_id"] else 0
            lead.custom_fields = {**(lead.custom_fields or {}), "bs_deal": it["deal_id"], "bs_install": inst["pipeline"]["id"],
                                  "bs_tries": tries + 1}
            if lead.do_not_call:
                await p.move_deal(http, conn.config or {}, it["deal_id"], _stage(inst, "dnc"))
                await add_log(db, conn, "new_lead", "ok", f"{lead.name} is on the do-not-call list — moved to Do not call.")
                continue
            try:
                await refresh_context(db, conn, lead)
            except CrmError:
                pass
            await db.flush()
            try:
                await _call_lead(db, conn, agent, lead)
            except Exception as exc:  # credits, phone setup… leave it queued and say why once
                skipped.add(it["deal_id"])
                await add_log(db, conn, "new_lead", "error", f"Couldn't call {lead.name} from the queue: {exc}")
                continue
            if calling_id:
                await p.move_deal(http, conn.config or {}, it["deal_id"], calling_id)
            started += 1
            await add_log(db, conn, "new_lead", "ok", f"{agent.name} is calling {lead.name} (queued in {inst['pipeline']['name']}).",
                          external_id=it["deal_id"])
    conn.settings = {**(conn.settings or {}), "queue_skipped": list(skipped)[-200:]}
    return started


async def _move_installed_deal(db, conn: CrmConnection, p: Provider, http, lead: Lead | None, outcome: str) -> str | None:
    """After a call from a BlackSync pipeline, move its card to the stage for the result."""
    cf = (lead.custom_fields or {}) if lead else {}
    inst = next((i for i in _installs(conn) if i["pipeline"]["id"] == cf.get("bs_install")), None)
    if not inst or not cf.get("bs_deal"):
        return None
    key = OUTCOME_TO_KEY.get(outcome or "", "follow_up")
    target = _stage(inst, key)
    current = await p.deal_stage(http, conn.config or {}, cf["bs_deal"])
    ids = {st["id"] for st in inst["pipeline"]["stages"]}
    if not target or current not in ids or current == target:
        return None  # someone moved it out of the BlackSync pipeline — leave it alone
    await p.move_deal(http, conn.config or {}, cf["bs_deal"], target)
    return f"Card moved to {next(st['label'] for st in inst['pipeline']['stages'] if st['id'] == target)}"


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


async def check_activity(db, conn: CrmConnection, now: dt.datetime | None = None) -> int:
    """Call people who just showed interest (viewed/saved a listing, inquired, registered). Returns calls started."""
    now = now or dt.datetime.now(UTC)
    cfg = conn_settings(conn)
    agent_id = cfg.get("activity_agent_id")
    p = provider_of(conn)
    if not agent_id or not p.can_activity:
        return 0
    agent = await db.get(Agent, uuid.UUID(agent_id))
    if not agent or agent.org_id != conn.org_id:
        conn.settings = {**cfg, "activity_agent_id": None}
        return 0
    since = dt.datetime.fromisoformat(cfg["activity_since"]) if cfg.get("activity_since") else now
    pending: list[str] = list(cfg.get("activity_pending") or [])
    try:
        _, http = http_for(conn)
        hits = await p.recent_activity(http, conn.config or {}, since)
    except CrmError as exc:
        await add_log(db, conn, "new_lead", "error", f"Couldn't check {p.name} activity: {exc}")
        return 0
    newest = max([h["at"] for h in hits if h.get("at")] + [since])
    for h in hits:
        c: Contact = h["contact"]
        created, _ = await save_contacts(db, conn, [c], "Showed interest")
        lead = created[0] if created else (await db.execute(select(Lead).where(
            Lead.org_id == conn.org_id, Lead.phone == normalize_phone(c.phone)))).scalars().first()
        if not lead or lead.do_not_call or c.dnc:
            continue
        last = lead.last_called_at
        if last and last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if last and now - last < dt.timedelta(hours=24):
            continue  # called in the last day — don't pile on
        lead.custom_fields = {**(lead.custom_fields or {}), "crm_trigger": f"{h['kind']} ({h['at']:%b %-d, %-I:%M %p} UTC)"}
        await add_log(db, conn, "new_lead", "ok", f"{lead.name}: {h['kind']}.", external_id=c.external_id)
        if str(lead.id) not in pending:
            pending.append(str(lead.id))
    started = 0
    org = await db.get(Organization, conn.org_id)
    if pending and _in_hours(org, now):
        for lid in pending[:5]:
            pending.remove(lid)
            lead = await db.get(Lead, uuid.UUID(lid))
            if not lead or lead.do_not_call:
                continue
            try:
                await refresh_context(db, conn, lead)
            except CrmError:
                pass
            trigger = (lead.custom_fields or {}).get("crm_trigger")
            if trigger:
                lead.custom_fields = {**(lead.custom_fields or {}), "crm_context":
                                      f"Why we're calling now: {trigger}.\n" + (lead.custom_fields or {}).get("crm_context", "")}
            try:
                await _call_lead(db, conn, agent, lead)
                started += 1
                await add_log(db, conn, "new_lead", "ok", f"{agent.name} is calling {lead.name} — {trigger or 'showed interest'}.")
            except Exception as exc:
                await add_log(db, conn, "new_lead", "error", f"Couldn't call {lead.name}: {exc}")
    conn.settings = {**cfg, "activity_since": newest.isoformat(), "activity_pending": pending[-200:]}
    return started


async def poll_once() -> None:
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        conns = (await db.execute(select(CrmConnection))).scalars().all()
        ids = [c.id for c in conns if any((c.settings or {}).get(k) for k in ("speed_to_lead_agent_id", "installs", "activity_agent_id"))]
    for cid in ids:
        async with AsyncSessionLocal() as db:
            conn = await db.get(CrmConnection, cid)
            if conn:
                try:
                    await check_new_leads(db, conn)
                    await check_activity(db, conn)
                    await process_queue(db, conn)
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
