"""Radar: scan a connected CRM for people to call now, then queue a play or turn it into a campaign."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.models.agent import Agent
from app.models.campaign import Campaign
from app.models.crm import CrmConnection, CrmScan
from app.models.lead import Lead
from app.services import entitlements
from app.services.auth import DbDep, ManagerDep
from app.services.contacts import normalize_phone
from app.services.crm import radar, sync
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
                    "last_scan": _scan_out(last, c.provider) if last else None})
    return {"crms": out}


async def _conn(db, org_id, key: str) -> CrmConnection:
    conn = (await db.execute(select(CrmConnection).where(CrmConnection.org_id == org_id,
                                                         CrmConnection.provider == key))).scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="That CRM isn't connected.")
    return conn


@router.post("/{key}/scan")
async def scan(key: str, ctx: ManagerDep, db: DbDep, quick: bool = False):
    await _require_radar(ctx, db)
    conn = await _conn(db, ctx.org.id, key)
    p = PROVIDERS[key]
    if not p.can_scan:
        raise HTTPException(status_code=400, detail=f"Radar doesn't support {p.name} yet.")
    try:
        _, http = sync.http_for(conn)
        signals = await p.scan_signals(http, conn.config or {}, quick=quick)
    except CrmError as exc:
        raise HTTPException(status_code=400, detail=f"Couldn't scan {p.name}: {exc}") from exc
    # Skip anyone already on BlackSync's do-not-call list.
    dnc = {normalize_phone(x) for x in (await db.execute(select(Lead.phone).where(
        Lead.org_id == ctx.org.id, Lead.do_not_call.is_(True)))).scalars()}
    for s in signals:
        if normalize_phone(s.phone) in dnc:
            s.dnc = True
    result = {**radar.build_plays(signals), "quick": quick}
    row = CrmScan(org_id=ctx.org.id, connection_id=conn.id, result=result)
    db.add(row)
    total = sum(pl["count"] for pl in result["plays"])
    await sync.add_log(db, conn, "import", "ok", f"Radar scanned {result['scanned']} contacts: {total} worth calling now.")
    await db.commit()
    await db.refresh(row)
    return _scan_out(row, key)


class LaunchIn(BaseModel):
    play: str
    agent_id: uuid.UUID
    mode: str = Field(pattern="^(pipeline|campaign)$")
    external_ids: list[str] | None = None  # a subset; default = the whole play
    campaign_name: str = Field(default="", max_length=120)


@router.post("/scans/{scan_id}/launch")
async def launch(scan_id: uuid.UUID, body: LaunchIn, ctx: ManagerDep, db: DbDep):
    await _require_radar(ctx, db)
    row = await db.get(CrmScan, scan_id)
    if not row or row.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Scan not found")
    conn = await db.get(CrmConnection, row.connection_id)
    agent = await db.get(Agent, body.agent_id)
    if not conn or not agent or agent.org_id != ctx.org.id:
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

    # Campaign: contacts (with CRM context on dial) in a new draft campaign for this agent.
    campaign = Campaign(id=uuid.uuid4(), org_id=ctx.org.id, agent_id=agent.id, status="draft",
                        name=(body.campaign_name or f"{play['title']} · {p.name}")[:120],
                        description=f"From Radar: {play['why']}")
    db.add(campaign)
    contacts = [Contact(i["name"], i["phone"], i.get("email") or "", i.get("company") or "", i["external_id"]) for i in items]
    created, _ = await sync.save_contacts(db, conn, contacts, f"Radar: {play['title']}")
    phones = {normalize_phone(c.phone) for c in contacts}
    leads = (await db.execute(select(Lead).where(Lead.org_id == ctx.org.id))).scalars().all()
    n = 0
    for lead in leads:
        if normalize_phone(lead.phone) in phones and not lead.do_not_call:
            lead.campaign_id = campaign.id
            lead.status = "new" if lead.status in (None, "", "completed") else lead.status
            n += 1
    await sync.add_log(db, conn, "import", "ok", f"Radar made a campaign of {n} from “{play['title']}”.")
    await db.commit()
    return {"campaign_id": str(campaign.id), "contacts": n}
