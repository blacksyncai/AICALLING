"""Radar: scan a connected CRM for people to call now, then queue a play or turn it into a campaign."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
import structlog

from app.models.agent import Agent
from app.models.call_log import CallLog
from app.models.campaign import Campaign
from app.models.crm import CrmConnection, CrmScan
from app.models.lead import Lead
from app.services import entitlements
from app.services.auth import DbDep, ManagerDep
from app.services.contacts import normalize_phone
from app.services.crm import radar, sync

log = structlog.get_logger(__name__)
from app.services.crm.http import CrmError
from app.services.crm.providers import PROVIDERS, Contact

router = APIRouter(prefix="/api/radar", tags=["radar"])


async def _require_radar(ctx, db) -> None:
    """Radar is a plan feature (Growth, Teams, Managed by default — see entitlements). Everyone else gets
    the in-app demo, which never calls these endpoints."""
    await entitlements.require(db, ctx.org, "radar", "Radar is included from the Growth plan.")


def _scan_out(scan: CrmScan, provider: str) -> dict:
    return {"id": str(scan.id), "provider": provider, "created_at": scan.created_at.isoformat() if scan.created_at else None,
            **scan.result}


_LIVE = {"meeting_booked", "qualified", "not_qualified", "interested", "not_interested", "callback", "transferred",
         "completed", "do_not_call"}


async def _blacksync_status(db, org_id, provider: str) -> dict[str, dict]:
    """What BlackSync already did with each CRM contact: campaign, calls, voicemails, verified (a live talk)."""
    leads = (await db.execute(select(Lead.id, Lead.crm_refs, Lead.campaign_id, Lead.do_not_call, Lead.name, Lead.phone).where(
        Lead.org_id == org_id, Lead.crm_refs.is_not(None)))).all()
    by_lead = {}
    for lead_id, refs, campaign_id, dnc, name, phone in leads:
        ref = (refs or {}).get(provider)
        if ref:
            by_lead[lead_id] = {"ext": str(ref), "campaign_id": campaign_id, "dnc": bool(dnc), "name": name, "phone": phone}
    if not by_lead:
        return {}
    names = dict((await db.execute(select(Campaign.id, Campaign.name).where(Campaign.org_id == org_id))).all())
    calls = (await db.execute(select(CallLog.lead_id, CallLog.outcome, CallLog.status, CallLog.started_at, CallLog.transcript, CallLog.to_phone, CallLog.call_type, CallLog.id).where(
        CallLog.org_id == org_id, CallLog.lead_id.in_(list(by_lead))).order_by(CallLog.started_at))).all()
    out: dict[str, dict] = {}
    for lead_id, info in by_lead.items():
        cid = info["campaign_id"]
        out[info["ext"]] = {"campaign": names.get(cid) if cid else None, "campaign_id": str(cid) if cid in names else None,
                            "calls": 0, "voicemails": 0, "verified": False, "wrong_number": False,
                            "last_outcome": None, "dnc": info["dnc"], "verification_status": "unverified", "verification_evidence": [], "verification_call_id": None}
    for lead_id, outcome, status, _, transcript, to_phone, call_type, call_id in calls:
        st = out[by_lead[lead_id]["ext"]]
        st["calls"] += 1
        st["voicemails"] += outcome == "voicemail"
        from app.services.crm.verification import classify
        info = by_lead[lead_id]
        if call_type in ("outbound", "inbound") and normalize_phone(to_phone or info["phone"]) == normalize_phone(info["phone"]):
            evidence = classify(transcript, info["name"], outcome or "")
            if evidence["status"] in ("name_confirmed", "wrong_number") or (evidence["status"] == "named_voicemail" and not st["verified"]):
                st["verification_status"], st["verification_evidence"] = evidence["status"], evidence["evidence"]
                st["verification_call_id"] = str(call_id)
                st["verified"] = evidence["status"] == "name_confirmed"
                st["wrong_number"] = evidence["status"] == "wrong_number"
            if outcome == "wrong_number":
                st["verified"], st["wrong_number"], st["verification_status"] = False, True, "wrong_number"
        st["last_outcome"] = outcome or status
    return out


async def _scan_view(db, org_id, scan: CrmScan, provider: str) -> dict:
    """The scan with each contact's BlackSync status, so already-handled people can be hidden or tagged."""
    out = _scan_out(scan, provider)
    status = await _blacksync_status(db, org_id, provider)
    plays = []
    for pl in out.get("plays") or []:
        items = [{**i, "bs": status.get(str(i["external_id"]))} for i in pl["items"]]
        plays.append({**pl, "items": items})
    out["plays"] = plays
    return out


@router.get("")
async def overview(ctx: ManagerDep, db: DbDep):
    await _require_radar(ctx, db)
    conns = (await db.execute(select(CrmConnection).where(CrmConnection.org_id == ctx.org.id))).scalars().all()
    out = []
    for c in conns:
        p = PROVIDERS.get(c.provider)
        if not p or not p.can_scan:
            continue
        last = (await db.execute(select(CrmScan).where(CrmScan.connection_id == c.id)
                                 .order_by(CrmScan.created_at.desc()).limit(1))).scalar_one_or_none()
        out.append({"provider": c.provider, "name": p.name, "account_label": c.account_label,
                    "installs": [{"agent_id": i["agent_id"], "agent_name": i.get("agent_name", ""),
                                  "pipeline_name": i["pipeline"]["name"]} for i in (c.settings or {}).get("installs") or []],
                    "last_scan": await _scan_view(db, ctx.org.id, last, c.provider) if last else None})
    return {"crms": out}


async def _conn(db, org_id, key: str) -> CrmConnection:
    conn = (await db.execute(select(CrmConnection).where(CrmConnection.org_id == org_id,
                                                         CrmConnection.provider == key))).scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="That CRM isn't connected.")
    return conn


@router.post("/{key}/scan")
async def scan(key: str, ctx: ManagerDep, db: DbDep, quick: bool = False, depth: str = "",
               continue_from: uuid.UUID | None = None):
    """Scan the CRM. depth: quick (newest) · recent (recent activity) · old (oldest first, to dig up old leads).
    continue_from: an earlier scan to extend with the next batch (same depth), so big CRMs are read in small,
    rate-limit-friendly steps instead of one huge pull."""
    await _require_radar(ctx, db)
    conn = await _conn(db, ctx.org.id, key)
    p = PROVIDERS[key]
    if not p.can_scan:
        raise HTTPException(status_code=400, detail=f"Radar doesn't support {p.name} yet.")
    previous = None
    if continue_from:
        previous = await db.get(CrmScan, continue_from)
        if not previous or previous.org_id != ctx.org.id or previous.connection_id != conn.id:
            raise HTTPException(status_code=404, detail="Scan not found")
        if not previous.result.get("next"):
            raise HTTPException(status_code=400, detail="That scan already reached the end of your CRM.")
        depth = previous.result.get("depth") or depth
    depth = depth if depth in ("quick", "recent", "old") else ("quick" if quick else "recent")
    state: dict = {}
    try:
        _, http = sync.http_for(conn)
        signals = await p.scan_signals(http, conn.config or {}, quick=depth == "quick", depth=depth,
                                       cursor=previous.result.get("next") if previous else None, state=state)
    except CrmError as exc:
        raise HTTPException(status_code=400, detail=f"Couldn't scan {p.name}: {exc}") from exc
    # Skip anyone already on BlackSync's do-not-call list.
    dnc = {normalize_phone(x) for x in (await db.execute(select(Lead.phone).where(
        Lead.org_id == ctx.org.id, Lead.do_not_call.is_(True)))).scalars()}
    for s in signals:
        if normalize_phone(s.phone) in dnc:
            s.dnc = True
    batch = radar.build_plays(signals)
    result = radar.merge(previous.result, batch) if previous else batch
    result.update(quick=depth == "quick", depth=depth, next=state.get("next"),
                  batches=(previous.result.get("batches", 1) + 1) if previous else 1)
    row = CrmScan(org_id=ctx.org.id, connection_id=conn.id, result=result)
    db.add(row)
    found = sum(pl["count"] for pl in batch["plays"])
    log.info("radar_scan", provider=key, depth=depth, quick=depth == "quick", scanned=batch["scanned"],
             worth_calling=found, signals=len(signals), batches=(previous.result.get("batches", 1) + 1) if previous else 1)
    await sync.add_log(db, conn, "import", "ok", f"Radar {depth} scan: {batch['scanned']} contacts scanned, {found} worth calling now.")
    await db.commit()
    await db.refresh(row)
    return await _scan_view(db, ctx.org.id, row, key)


@router.get("/{key}/segments")
async def segments(key: str, ctx: ManagerDep, db: DbDep):
    """The CRM's own lists Radar can open whole: ponds, lead sources, stages."""
    await _require_radar(ctx, db)
    conn = await _conn(db, ctx.org.id, key)
    p = PROVIDERS[key]
    if not getattr(p, "can_segment", False):
        return {"pond": [], "source": [], "stage": [], "deal": []}
    _, http = sync.http_for(conn)
    try:
        return await p.segment_options(http, conn.config or {})
    except CrmError as exc:
        raise HTTPException(status_code=400, detail=f"Couldn't read {p.name}: {exc}") from exc


class SegmentIn(BaseModel):
    kind: str = Field(pattern="^(pond|source|stage|deal)$")
    value: str = Field(min_length=1, max_length=200)
    label: str = Field(default="", max_length=200)


@router.post("/{key}/segment")
async def open_segment(key: str, body: SegmentIn, ctx: ManagerDep, db: DbDep):
    """Everyone in one pond / lead source / stage, as a list to pick from and launch like any Radar play."""
    await _require_radar(ctx, db)
    conn = await _conn(db, ctx.org.id, key)
    p = PROVIDERS[key]
    if not getattr(p, "can_segment", False):
        raise HTTPException(status_code=400, detail=f"Opening lists isn't supported for {p.name} yet.")
    try:
        _, http = sync.http_for(conn)
        signals = await p.segment_signals(http, conn.config or {}, body.kind, body.value)
    except CrmError as exc:
        raise HTTPException(status_code=400, detail=f"Couldn't read {p.name}: {exc}") from exc
    dnc = {normalize_phone(x) for x in (await db.execute(select(Lead.phone).where(
        Lead.org_id == ctx.org.id, Lead.do_not_call.is_(True)))).scalars()}
    label = body.label or body.value
    for s in signals:
        if normalize_phone(s.phone) in dnc:
            s.dnc = True
        if body.kind == "pond":
            s.pond = label
    noun = {"pond": "pond", "source": "lead source", "stage": "stage", "deal": "deal stage"}[body.kind]
    result = radar.build_segment(signals, f"{label} ({noun})", f"Everyone in the {noun} “{label}” in {p.name}.")
    result.update(depth="segment", segment={"kind": body.kind, "value": body.value, "label": label}, next=None)
    row = CrmScan(org_id=ctx.org.id, connection_id=conn.id, result=result)
    db.add(row)
    await sync.add_log(db, conn, "import", "ok", f"Radar opened the {noun} “{label}”: {result['plays'][0]['count']} contacts.")
    await db.commit()
    await db.refresh(row)
    return await _scan_view(db, ctx.org.id, row, key)


class LaunchIn(BaseModel):
    play: str
    agent_id: uuid.UUID
    mode: str = Field(pattern="^(pipeline|campaign)$")
    external_ids: list[str] | None = None  # a subset; default = the whole play
    campaign_name: str = Field(default="", max_length=120)
    campaign_id: uuid.UUID | None = None


@router.post("/scans/{scan_id}/launch")
async def launch(scan_id: uuid.UUID, body: LaunchIn, ctx: ManagerDep, db: DbDep):
    await _require_radar(ctx, db)
    row = await db.get(CrmScan, scan_id)
    if not row or row.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Scan not found")
    conn = await db.get(CrmConnection, row.connection_id)
    campaign = None
    if body.campaign_id:
        if body.mode != "campaign":
            raise HTTPException(400, "Choose campaign mode to add to an existing campaign.")
        campaign = await db.scalar(select(Campaign).where(
            Campaign.id == body.campaign_id, Campaign.org_id == ctx.org.id).with_for_update())
        if not campaign:
            raise HTTPException(404, "Campaign not found")
        if campaign.status not in ("draft", "paused", "running") or campaign.direction == "inbound":
            raise HTTPException(400, "Choose a draft, paused, or running outbound campaign.")
        if campaign.agent_id != body.agent_id:
            raise HTTPException(400, "Use the existing campaign's agent.")
    agent = await db.get(Agent, body.agent_id)
    if not conn or conn.org_id != ctx.org.id or not agent or agent.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Agent not found")
    play = next((pl for pl in row.result.get("plays") or [] if pl["key"] == body.play), None)
    if not play:
        raise HTTPException(status_code=404, detail="Play not found")
    items = play["items"]
    if body.external_ids is not None:
        want = set(body.external_ids)
        items = [i for i in items if i["external_id"] in want]
    if not items:
        raise HTTPException(status_code=400, detail="Nobody to call in that play.")
    p = PROVIDERS[conn.provider]

    if body.mode == "pipeline":
        inst = next((i for i in (conn.settings or {}).get("installs") or [] if i["agent_id"] == str(agent.id)), None)
        if not inst:
            raise HTTPException(status_code=400, detail=f"Create the BlackSync pipeline for {agent.name} first.")
        queue = next(st["id"] for st in inst["pipeline"]["stages"] if st.get("key") == "queued")
        _, http = sync.http_for(conn)
        done, failed = 0, 0
        for it in items:
            try:
                await p.enqueue(http, conn.config or {}, it["external_id"], inst["pipeline"], queue)
                done += 1
            except CrmError:
                failed += 1
        await sync.add_log(db, conn, "import", "ok" if not failed else "error",
                           f"Radar queued {done} from “{play['title']}” in {inst['pipeline']['name']}"
                           + (f"; {failed} couldn't be queued" if failed else "") + ".")
        await db.commit()
        return {"queued": done, "failed": failed, "pipeline": inst["pipeline"]["name"]}

    # Import selected contacts into a new draft or the explicitly chosen campaign.
    existing_campaign = campaign is not None
    if campaign is None:
        campaign = Campaign(id=uuid.uuid4(), org_id=ctx.org.id, agent_id=agent.id, status="draft",
                            name=(body.campaign_name or f"{play['title']} · {p.name}")[:120],
                            description=f"From Radar: {play['why']}")
        db.add(campaign)
    contacts = [Contact(i["name"], i["phone"], i.get("email") or "", i.get("company") or "", i["external_id"], dnc=bool(i.get("dnc"))) for i in items]
    created, _ = await sync.save_contacts(db, conn, contacts, f"Radar: {play['title']}")
    phones = {normalize_phone(c.phone) for c in contacts}
    leads = (await db.execute(select(Lead).where(Lead.org_id == ctx.org.id))).scalars().all()
    picked = []
    skipped = 0
    for lead in leads:
        if normalize_phone(lead.phone) in phones and not lead.do_not_call:
            if existing_campaign and lead.campaign_id is not None:
                skipped += 1
                continue
            lead.campaign_id = campaign.id
            lead.status = "new" if lead.status in (None, "", "completed") else lead.status
            picked.append(lead)
    n = len(picked)
    campaign.total_targets = (campaign.total_targets or 0) + n
    # The agent's {{variables}} (address, price, assigned agent…) straight from the CRM, visible on the contacts.
    await sync.prefill_fields(conn, agent, picked)
    await sync.add_log(db, conn, "import", "ok", f"Radar {'added' if existing_campaign else 'imported'} {n} contacts into campaign “{campaign.name}” from “{play['title']}”.")
    await db.commit()
    return {"campaign_id": str(campaign.id), "contacts": n, "skipped": skipped, "existing_campaign": existing_campaign}
