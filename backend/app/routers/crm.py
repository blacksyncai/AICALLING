"""
CRM & app integrations: connect (API key or OAuth through Nango), settings,
import contacts, speed to lead and the activity log.
"""

from __future__ import annotations

import datetime as dt
import time
import uuid

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import settings
from app.models.agent import Agent
from app.models.crm import CrmConnection, CrmSyncLog
from app.services import secret_store
from app.services.auth import DbDep, ManagerDep
from app.services.crm import sync
from app.services.crm.http import CrmError, nango
from app.services.crm.providers import PROVIDERS, Provider

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/integrations/crm", tags=["integrations"])

_nango_cache: dict = {"at": 0.0, "items": []}


async def nango_integrations() -> list[dict]:
    """Integrations set up in the Nango environment (cached for a minute)."""
    if not settings.nango_secret_key:
        return []
    if time.monotonic() - _nango_cache["at"] < 60:
        return _nango_cache["items"]
    try:
        items = (await nango("GET", "/integrations")).get("data") or []
    except CrmError as exc:
        log.warning("nango_integrations_failed", error=str(exc))
        items = []
    _nango_cache.update(at=time.monotonic(), items=items)
    return items


async def _nango_key_for(p: Provider) -> str | None:
    for it in await nango_integrations():
        if it.get("provider") in p.nango_providers:
            return it.get("unique_key")
    return None


def _provider(key: str) -> Provider:
    p = PROVIDERS.get(key)
    if not p:
        raise HTTPException(status_code=404, detail="Unknown integration")
    return p


def _iso(d: dt.datetime | None) -> str | None:
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).isoformat()


def conn_to_dict(c: CrmConnection) -> dict:
    s = sync.conn_settings(c)
    cfg = c.config or {}
    return {
        "provider": c.provider, "method": c.method, "account_label": c.account_label, "status": c.status,
        "last_error": c.last_error, "last_synced_at": _iso(c.last_synced_at), "created_at": _iso(c.created_at),
        "settings": {k: s[k] for k in ("log_calls", "create_contacts", "only_connected", "speed_to_lead_agent_id")},
        "pending_calls": len(s.get("pending") or []),
        "pipeline": ({"id": s["pipeline"]["id"], "name": (s["pipeline"].get("snapshot") or {}).get("name", ""),
                      "mapped": len(s["pipeline"].get("map") or {})} if s.get("pipeline") else None),
        # Non-secret details only.
        "config": {k: v for k, v in cfg.items() if k in ("location_id", "spreadsheet")},
    }


async def _get_conn(db, org_id, key: str) -> CrmConnection | None:
    return (await db.execute(select(CrmConnection).where(
        CrmConnection.org_id == org_id, CrmConnection.provider == key))).scalar_one_or_none()


async def _require_conn(db, org_id, key: str) -> CrmConnection:
    conn = await _get_conn(db, org_id, key)
    if not conn:
        raise HTTPException(status_code=404, detail="That integration isn't connected.")
    return conn


@router.get("")
async def overview(ctx: ManagerDep, db: DbDep):
    conns = (await db.execute(select(CrmConnection).where(CrmConnection.org_id == ctx.org.id))).scalars().all()
    nango_items = await nango_integrations()
    nango_providers = {it.get("provider") for it in nango_items}
    providers = [{
        "key": p.key, "name": p.name, "category": p.category, "description": p.description,
        "native": p.native, "oauth": any(n in nango_providers for n in p.nango_providers),
        "can_import": p.can_import, "can_new_leads": p.can_new_leads, "docs_url": p.docs_url,
        "pipeline_noun": p.pipeline_noun,
        "fields": [{"name": f.name, "label": f.label, "secret": f.secret, "placeholder": f.placeholder, "help": f.help}
                   for f in p.auth_fields],
    } for p in PROVIDERS.values()]
    return {"providers": providers, "connections": [conn_to_dict(c) for c in conns],
            "nango_enabled": bool(settings.nango_secret_key)}


class ConnectIn(BaseModel):
    fields: dict[str, str] = Field(default_factory=dict)


async def _save(db, ctx, p: Provider, method: str, secret: str, config: dict, label: str) -> CrmConnection:
    conn = await _get_conn(db, ctx.org.id, p.key)
    if conn is None:
        conn = CrmConnection(org_id=ctx.org.id, provider=p.key, settings=sync.defaults())
        db.add(conn)
    conn.method, conn.config, conn.account_label = method, config, label[:255]
    conn.secret_enc = secret_store.encrypt_value(secret) if secret else None
    conn.status, conn.last_error = "connected", None
    await db.flush()
    await sync.add_log(db, conn, "test", "ok", f"Connected to {p.name}" + (f" as {label}" if label else "") + ".")
    await db.commit()
    await db.refresh(conn)
    return conn


@router.post("/{key}/connect")
async def connect(key: str, body: ConnectIn, ctx: ManagerDep, db: DbDep):
    """Connect with an API key (verified against the CRM before it's saved)."""
    p = _provider(key)
    if not p.native:
        raise HTTPException(status_code=400, detail=f"{p.name} connects with OAuth. Use Connect with {p.name}.")
    secret = (body.fields.get("api_key") or "").strip()
    config = {f.name: (body.fields.get(f.name) or "").strip() for f in p.auth_fields if not f.secret}
    existing = await _get_conn(db, ctx.org.id, key)
    if not secret and existing and existing.method == "api_key" and existing.secret_enc:
        secret = secret_store.decrypt_value(existing.secret_enc)  # updating non-secret fields only
    if not secret:
        raise HTTPException(status_code=400, detail=f"Paste your {p.auth_fields[0].label if p.auth_fields else 'API key'}.")
    if not secret_store.available():
        raise HTTPException(status_code=503, detail="Secret storage isn't configured on the server.")
    try:
        label = await p.verify(p.native_http(secret, config), config)
    except CrmError as exc:
        raise HTTPException(status_code=400, detail=f"Couldn't connect to {p.name}: {exc}") from exc
    return conn_to_dict(await _save(db, ctx, p, "api_key", secret, config, label or p.name))


@router.post("/{key}/oauth/session")
async def oauth_session(key: str, ctx: ManagerDep):
    """A short-lived Nango Connect session for the OAuth popup."""
    p = _provider(key)
    integration = await _nango_key_for(p)
    if not integration:
        raise HTTPException(status_code=400, detail=f"{p.name} OAuth isn't enabled yet.")
    try:
        res = await nango("POST", "/connect/sessions", json={
            "end_user": {"id": str(ctx.user.id), "email": ctx.user.email or None, "display_name": (f"{ctx.user.first_name} {ctx.user.last_name}".strip() or None)},
            "organization": {"id": str(ctx.org.id), "display_name": ctx.org.name},
            "allowed_integrations": [integration],
        })
    except CrmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"token": (res.get("data") or {}).get("token"), "integration": integration}


class OAuthDoneIn(BaseModel):
    connection_id: str = Field(min_length=1, max_length=200)
    fields: dict[str, str] = Field(default_factory=dict)


@router.post("/{key}/oauth/complete")
async def oauth_complete(key: str, body: OAuthDoneIn, ctx: ManagerDep, db: DbDep):
    """Save a Nango connection once the popup finishes (checked against Nango first)."""
    p = _provider(key)
    integration = await _nango_key_for(p)
    if not integration:
        raise HTTPException(status_code=400, detail=f"{p.name} OAuth isn't enabled.")
    try:
        conn_info = await nango("GET", f"/connection/{body.connection_id}", params={"provider_config_key": integration})
    except CrmError as exc:
        raise HTTPException(status_code=400, detail=f"Couldn't find that {p.name} connection: {exc}") from exc
    owner = ((conn_info.get("end_user") or {}).get("id")) or ""
    org_tag = ((conn_info.get("end_user") or {}).get("organization_id")
               or (conn_info.get("organization") or {}).get("id") or "")
    if owner and owner != str(ctx.user.id) and org_tag != str(ctx.org.id):
        raise HTTPException(status_code=403, detail="That connection belongs to someone else.")
    config = {f.name: (body.fields.get(f.name) or "").strip() for f in p.auth_fields if not f.secret}
    config.update(nango_connection_id=body.connection_id, nango_integration=integration)
    try:
        label = await p.verify(p.http("", config), config)
    except CrmError as exc:
        label = ""
        log.warning("oauth_verify_failed", provider=key, error=str(exc))
    return conn_to_dict(await _save(db, ctx, p, "nango", "", config, label or p.name))


@router.get("/{key}/pipelines")
async def pipelines(key: str, ctx: ManagerDep, db: DbDep):
    """The CRM's pipelines and stages, a suggested result → stage map for each, and the saved setup."""
    from app.services.crm.providers import MAPPABLE_OUTCOMES, suggest_mapping

    p = _provider(key)
    conn = await _require_conn(db, ctx.org.id, key)
    if not p.pipeline_noun:
        return {"supported": False}
    try:
        _, http = sync.http_for(conn)
        pipes = await p.pipelines(http, conn.config or {})
    except CrmError as exc:
        raise HTTPException(status_code=400, detail=f"Couldn't read {p.name} pipelines: {exc}") from exc
    saved = (conn.settings or {}).get("pipeline") or {}
    return {"supported": True, "noun": p.pipeline_noun, "pipelines": pipes,
            "suggested": {pl["id"]: suggest_mapping(pl) for pl in pipes},
            "outcomes": [{"key": k, "label": label} for k, label in MAPPABLE_OUTCOMES],
            "current": {k: saved.get(k) for k in ("id", "map", "create", "forward_only")} if saved else None}


class PipelineSyncIn(BaseModel):
    pipeline_id: str = Field(default="", max_length=100)  # "" turns pipeline sync off
    map: dict[str, str] = Field(default_factory=dict)
    create: bool = True
    forward_only: bool = True


@router.put("/{key}/pipelines")
async def save_pipeline_sync(key: str, body: PipelineSyncIn, ctx: ManagerDep, db: DbDep):
    from app.services.crm.providers import MAPPABLE_OUTCOMES

    p = _provider(key)
    conn = await _require_conn(db, ctx.org.id, key)
    s = dict(conn.settings or {})
    if not body.pipeline_id:
        s.pop("pipeline", None)
    else:
        try:
            _, http = sync.http_for(conn)
            pipes = await p.pipelines(http, conn.config or {})
        except CrmError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        pipe = next((pl for pl in pipes if pl["id"] == body.pipeline_id), None)
        if not pipe:
            raise HTTPException(status_code=404, detail="That pipeline wasn't found.")
        stage_ids = {st["id"] for st in pipe["stages"]}
        allowed = {k for k, _ in MAPPABLE_OUTCOMES}
        mapping = {k: v for k, v in body.map.items() if k in allowed and v in stage_ids}
        s["pipeline"] = {"id": pipe["id"], "map": mapping, "create": body.create, "forward_only": body.forward_only,
                         "snapshot": pipe}
        await sync.add_log(db, conn, "test", "ok", f"Pipeline sync set to {pipe['name']} ({len(mapping)} results mapped).")
    conn.settings = s
    await db.commit()
    await db.refresh(conn)
    return conn_to_dict(conn)


class SettingsIn(BaseModel):
    log_calls: bool | None = None
    create_contacts: bool | None = None
    only_connected: bool | None = None
    speed_to_lead_agent_id: str | None = None  # "" turns it off
    location_id: str | None = Field(default=None, max_length=100)
    spreadsheet: str | None = Field(default=None, max_length=500)


@router.patch("/{key}")
async def update_settings(key: str, body: SettingsIn, ctx: ManagerDep, db: DbDep):
    p = _provider(key)
    conn = await _require_conn(db, ctx.org.id, key)
    s = sync.conn_settings(conn)
    data = body.model_dump(exclude_unset=True)
    for k in ("log_calls", "create_contacts", "only_connected"):
        if data.get(k) is not None:
            s[k] = data[k]
    if "speed_to_lead_agent_id" in data:
        agent_id = (data["speed_to_lead_agent_id"] or "").strip()
        if agent_id:
            if not p.can_new_leads:
                raise HTTPException(status_code=400, detail=f"{p.name} can't send new leads.")
            try:
                agent = await db.get(Agent, uuid.UUID(agent_id))
            except ValueError:
                agent = None
            if not agent or agent.org_id != ctx.org.id:
                raise HTTPException(status_code=404, detail="Agent not found")
            if s.get("speed_to_lead_agent_id") != agent_id:
                s["speed_to_lead_since"] = dt.datetime.now(dt.timezone.utc).isoformat()  # only leads from now on
                s["pending"] = []
            s["speed_to_lead_agent_id"] = agent_id
        else:
            s["speed_to_lead_agent_id"], s["pending"] = None, []
    cfg = dict(conn.config or {})
    for k in ("location_id", "spreadsheet"):
        if data.get(k) is not None:
            cfg[k] = data[k].strip()
    conn.settings, conn.config = s, cfg
    await db.commit()
    await db.refresh(conn)
    return conn_to_dict(conn)


@router.post("/{key}/test")
async def test(key: str, ctx: ManagerDep, db: DbDep):
    conn = await _require_conn(db, ctx.org.id, key)
    try:
        p, http = sync.http_for(conn)
        label = await p.verify(http, conn.config or {})
        conn.account_label = (label or conn.account_label)[:255]
        await sync.add_log(db, conn, "test", "ok", f"Connection works ({label}).")
    except CrmError as exc:
        await sync.add_log(db, conn, "test", "error", f"Connection test failed: {exc}")
    await db.commit()
    await db.refresh(conn)
    return conn_to_dict(conn)


class ImportIn(BaseModel):
    filters: dict[str, list[str] | str | bool] = Field(default_factory=dict)
    skip_contacted: bool = False
    list_tag: str = Field(default="", max_length=60)
    limit: int = Field(default=500, ge=1, le=2000)


def _filters(body: ImportIn) -> dict:
    out: dict = {}
    for k, v in body.filters.items():
        if isinstance(v, str):
            v = [v] if v else []
        if v:
            out[k] = v
    if body.skip_contacted:
        out["skip_contacted"] = True
    return out


@router.get("/{key}/import/options")
async def import_options(key: str, ctx: ManagerDep, db: DbDep):
    p = _provider(key)
    conn = await _require_conn(db, ctx.org.id, key)
    try:
        _, http = sync.http_for(conn)
        filters = await p.import_options(http, conn.config or {})
    except CrmError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"provider": p.key, "name": p.name, "filters": filters}


@router.post("/{key}/import/preview")
async def import_preview(key: str, body: ImportIn, ctx: ManagerDep, db: DbDep):
    conn = await _require_conn(db, ctx.org.id, key)
    try:
        return await sync.preview_import(db, conn, _filters(body), body.skip_contacted, body.limit)
    except CrmError as exc:
        raise HTTPException(status_code=400, detail=f"Couldn't read {_provider(key).name}: {exc}") from exc


@router.post("/{key}/import")
async def import_contacts(key: str, ctx: ManagerDep, db: DbDep, body: ImportIn | None = None):
    body = body or ImportIn()
    conn = await _require_conn(db, ctx.org.id, key)
    if not _provider(key).can_import:
        raise HTTPException(status_code=400, detail="This integration doesn't have contacts to import.")
    try:
        result = await sync.import_contacts(db, conn, limit=body.limit, filters=_filters(body),
                                            skip_contacted=body.skip_contacted, list_tag=body.list_tag)
    except CrmError as exc:
        await sync.add_log(db, conn, "import", "error", f"Import failed: {exc}")
        await db.commit()
        raise HTTPException(status_code=400, detail=f"Import failed: {exc}") from exc
    await db.commit()
    return result


@router.get("/{key}/activity")
async def activity(key: str, ctx: ManagerDep, db: DbDep):
    conn = await _require_conn(db, ctx.org.id, key)
    rows = (await db.execute(select(CrmSyncLog).where(CrmSyncLog.connection_id == conn.id)
                             .order_by(CrmSyncLog.created_at.desc()).limit(50))).scalars().all()
    return {"items": [{"id": str(r.id), "kind": r.kind, "status": r.status, "message": r.message,
                       "call_id": str(r.call_id) if r.call_id else None, "created_at": _iso(r.created_at)} for r in rows]}


@router.delete("/{key}")
async def disconnect(key: str, ctx: ManagerDep, db: DbDep):
    conn = await _require_conn(db, ctx.org.id, key)
    cfg = conn.config or {}
    if conn.method == "nango" and cfg.get("nango_connection_id"):
        try:
            await nango("DELETE", f"/connection/{cfg['nango_connection_id']}",
                        params={"provider_config_key": cfg.get("nango_integration")})
        except CrmError as exc:
            log.warning("nango_delete_failed", error=str(exc))
    await db.delete(conn)
    await db.commit()
    return {"ok": True}
