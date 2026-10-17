"""
CRM & app integrations: connect (API key or OAuth through Nango), settings,
import contacts, speed to lead and the activity log.
"""

from __future__ import annotations

import datetime as dt
import time
import uuid

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import settings
from app.models.agent import Agent
from app.models.crm import CrmConnection, CrmSyncLog
from app.services import entitlements, secret_store
from app.services.auth import DbDep, ManagerDep
from app.services.crm import sync
from app.services.crm.http import CrmError, nango
from app.services.crm import salesforce_oauth as sf_oauth
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
        "settings": {k: s.get(k) for k in ("log_calls", "create_contacts", "csv_create_fields", "only_connected", "speed_to_lead_agent_id",
                                             "activity_agent_id", "min_seconds", "skip_outcomes", "only_outcomes",
                                             "only_sentiments", "note_summary",
                                             "note_details", "note_link", "note_transcript")},
        "auto_imports": [{k: r.get(k) for k in ("id", "name", "filters", "skip_contacted", "campaign_id", "list_tag",
                                                 "every_minutes", "enabled", "last_run_at", "last_result", "runs", "summary")}
                         for r in s.get("auto_imports") or []],
        "pending_calls": len(s.get("pending") or []),
        "installs": [{"agent_id": i["agent_id"], "agent_name": i.get("agent_name", ""), "pipeline_id": i["pipeline"]["id"],
                      "pipeline_name": i["pipeline"]["name"], "stages": [st["label"] for st in i["pipeline"]["stages"]],
                      "retry": i.get("retry") or {"max_tries": 3, "after_hours": 4, "voicemail": True}}
                     for i in s.get("installs") or []],
        "pipeline": ({"id": s["pipeline"]["id"], "name": (s["pipeline"].get("snapshot") or {}).get("name", ""),
                      "mapped": len(s["pipeline"].get("map") or {})} if s.get("pipeline") else None),
        # Non-secret details only.
        "config": {k: v for k, v in cfg.items() if k in ("location_id", "spreadsheet", "username", "instance_url", "site_uuid", "verification_lead_id")},
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
        "native": p.native, "setup_required_reason": getattr(p, "setup_required_reason", ""), "oauth": any(n in nango_providers for n in p.nango_providers),
        # Our own OAuth sign-in (no Nango): "Connect with …" sends the browser to the CRM's login page.
        "oauth_native": p.key == "salesforce" and sf_oauth.enabled(),
        "can_import": p.can_import, "can_new_leads": p.can_new_leads, "docs_url": p.docs_url,
        "pipeline_noun": p.pipeline_noun, "can_install": p.can_install, "install_style": p.install_style,
        "can_activity": p.can_activity, "can_map_fields": p.can_map_fields,
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
    await entitlements.check_crm(db, ctx.org, key)
    if getattr(p, "setup_required_reason", ""):
        raise HTTPException(status_code=503, detail=p.setup_required_reason)
    if not p.native:
        raise HTTPException(status_code=400, detail=f"{p.name} connects with OAuth. Use Connect with {p.name}.")
    secret = body.fields.get("api_key") or ""
    if key not in ("oracle_sales", "realgeeks"):
        secret = secret.strip()
    config = {f.name: (body.fields.get(f.name) or "").strip() for f in p.auth_fields if not f.secret}
    existing = await _get_conn(db, ctx.org.id, key)
    if not secret and existing and existing.method == "api_key" and existing.secret_enc:
        secret = secret_store.decrypt_value(existing.secret_enc)  # updating non-secret fields only
    if not secret:
        raise HTTPException(status_code=400, detail=f"Paste your {p.auth_fields[0].label if p.auth_fields else 'API key'}.")
    if not secret_store.available():
        raise HTTPException(status_code=503, detail="We couldn't save this connection right now — please try again in a moment.")
    try:
        label = await p.verify(p.native_http(secret, config), config)
    except CrmError as exc:
        raise HTTPException(status_code=400, detail=f"Couldn't connect to {p.name}: {exc}") from exc
    return conn_to_dict(await _save(db, ctx, p, "api_key", secret, config, label or p.name))


class NativeOAuthIn(BaseModel):
    sandbox: bool = False


@router.post("/salesforce/oauth/start")
async def salesforce_oauth_start(body: NativeOAuthIn, request: Request, ctx: ManagerDep, db: DbDep):
    """The Salesforce login URL for this account (our own Connected App, no third party in between)."""
    await entitlements.check_crm(db, ctx.org, "salesforce")
    if not sf_oauth.enabled():
        raise HTTPException(status_code=400, detail="Salesforce sign-in isn't switched on yet.")
    if not secret_store.available():
        raise HTTPException(status_code=503, detail="We couldn't save this connection right now — please try again in a moment.")
    return {"url": sf_oauth.start(ctx.org.id, ctx.user.id, str(request.base_url), sandbox=body.sandbox)}


@router.get("/salesforce/oauth/callback")
async def salesforce_oauth_callback(db: DbDep, state: str = "", code: str = "", error: str = "",
                                    error_description: str = ""):
    """Salesforce sends the browser back here after login. The one-time state ties it to who started it."""
    import json as _json

    done = "/integrations/salesforce"
    pending = sf_oauth.take(state)
    if error or not code or pending is None:
        log.info("salesforce_oauth_declined", error=error, description=error_description[:200], known=bool(pending))
        return RedirectResponse(f"{done}?error=" + ("cancelled" if error == "access_denied" else "failed"), status_code=303)
    p = PROVIDERS["salesforce"]
    try:
        tokens = await sf_oauth.finish(pending, code)
        config = {"sf_native": True, "instance_url": tokens["instance_url"], "login_host": tokens["login_host"]}
        secret = _json.dumps({"refresh_token": tokens["refresh_token"], "access_token": tokens["access_token"]})
        label = await p.verify(p.http(secret, config), config)
    except CrmError as exc:
        log.warning("salesforce_oauth_failed", error=str(exc)[:300])
        return RedirectResponse(f"{done}?error=failed", status_code=303)
    conn = await _get_conn(db, pending["org_id"], "salesforce")
    if conn is None:
        conn = CrmConnection(org_id=pending["org_id"], provider="salesforce", settings=sync.defaults())
        db.add(conn)
    conn.method, conn.config, conn.account_label = "oauth", config, (label or "Salesforce")[:255]
    conn.secret_enc = secret_store.encrypt_value(secret)
    conn.status, conn.last_error = "connected", None
    await db.flush()
    await sync.add_log(db, conn, "test", "ok", f"Connected to Salesforce as {label}.")
    await db.commit()
    log.info("salesforce_connected", org_id=str(pending["org_id"]))
    return RedirectResponse(f"{done}?connected=1", status_code=303)


@router.post("/{key}/oauth/session")
async def oauth_session(key: str, ctx: ManagerDep, db: DbDep):
    """A short-lived Nango Connect session for the OAuth popup."""
    p = _provider(key)
    await entitlements.check_crm(db, ctx.org, key)
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
    await entitlements.check_crm(db, ctx.org, key)
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
    if body.pipeline_id:
        await entitlements.require(db, ctx.org, "workflows", "Pipeline stage sync is included from the Growth plan.")
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


class InstallIn(BaseModel):
    agent_id: uuid.UUID
    name: str = Field(default="", max_length=60)
    labels: dict[str, str] = Field(default_factory=dict)  # stage key → custom label
    max_tries: int = Field(default=3, ge=1, le=6)
    retry_hours: float = Field(default=4, ge=0.5, le=72)
    retry_voicemail: bool = True


@router.get("/{key}/install/preview")
async def install_preview(key: str, ctx: ManagerDep, db: DbDep):
    """What "Create the AI calling pipeline" will make, before the user allows it."""
    p = _provider(key)
    await _require_conn(db, ctx.org.id, key)
    what = {"queued": "Move anyone here and the agent calls them within a minute (8 AM – 9 PM).",
            "calling": "The agent is on the phone with them.",
            "no_answer": "Didn't pick up — goes back to the queue after your wait, until the tries run out.",
            "voicemail": "Reached voicemail (left your message or hung up, per the agent's setting).",
            "follow_up": "They talked — interested, callback or questions. Your team takes it from here.",
            "booked": "The agent booked a meeting on your calendar.",
            "not_interested": "Said no, wrong number or not a fit.",
            "dnc": "Asked not to be called again — never dialed again."}
    return {"supported": p.can_install, "style": p.install_style, "noun": p.pipeline_noun or "pipeline",
            "stages": [{"key": st["key"], "label": st["label"], "kind": st["kind"], "what": what.get(st["key"], "")}
                       for st in sync.BLACKSYNC_STAGES]}


@router.post("/{key}/install")
async def install(key: str, body: InstallIn, ctx: ManagerDep, db: DbDep):
    """Create a "BlackSync AI · <agent>" pipeline in the CRM. Cards dragged into its queue stage get called."""
    conn = await _require_conn(db, ctx.org.id, key)
    await entitlements.require(db, ctx.org, "workflows", "The AI calling pipeline is included from the Growth plan.")
    agent = await db.get(Agent, body.agent_id)
    if not agent or agent.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        await sync.install_pipeline(db, conn, agent, name=body.name, labels=body.labels, max_tries=body.max_tries,
                                    retry_hours=body.retry_hours, retry_voicemail=body.retry_voicemail)
    except CrmError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"Couldn't create the pipeline: {exc}") from exc
    await db.commit()
    await db.refresh(conn)
    return conn_to_dict(conn)


@router.delete("/{key}/install/{agent_id}")
async def uninstall(key: str, agent_id: str, ctx: ManagerDep, db: DbDep):
    """Stop watching that pipeline (it stays in the CRM so nothing is lost)."""
    conn = await _require_conn(db, ctx.org.id, key)
    await sync.remove_install(db, conn, agent_id)
    await db.commit()
    await db.refresh(conn)
    return conn_to_dict(conn)


class SettingsIn(BaseModel):
    log_calls: bool | None = None
    create_contacts: bool | None = None
    csv_create_fields: bool | None = None
    only_connected: bool | None = None
    min_seconds: int | None = Field(default=None, ge=0, le=3600)
    skip_outcomes: list[str] | None = None
    only_outcomes: list[str] | None = None
    only_sentiments: list[str] | None = None
    note_summary: bool | None = None
    note_details: bool | None = None
    note_link: bool | None = None
    note_transcript: bool | None = None
    speed_to_lead_agent_id: str | None = None  # "" turns it off
    activity_agent_id: str | None = None  # "" turns it off
    location_id: str | None = Field(default=None, max_length=100)
    spreadsheet: str | None = Field(default=None, max_length=500)


@router.patch("/{key}")
async def update_settings(key: str, body: SettingsIn, ctx: ManagerDep, db: DbDep):
    p = _provider(key)
    conn = await _require_conn(db, ctx.org.id, key)
    s = sync.conn_settings(conn)
    data = body.model_dump(exclude_unset=True)
    for k in ("log_calls", "create_contacts", "csv_create_fields", "only_connected", "note_summary", "note_details", "note_link", "note_transcript", "min_seconds"):
        if data.get(k) is not None:
            s[k] = data[k]
    if data.get("skip_outcomes") is not None:
        from app.models.call_log import CALL_OUTCOMES

        s["skip_outcomes"] = [o for o in dict.fromkeys(data["skip_outcomes"]) if o in CALL_OUTCOMES and o != "do_not_call"]
    if data.get("only_outcomes") is not None:
        from app.models.call_log import CALL_OUTCOMES

        s["only_outcomes"] = [o for o in dict.fromkeys(data["only_outcomes"]) if o in CALL_OUTCOMES]
    if data.get("only_sentiments") is not None:
        s["only_sentiments"] = [x for x in dict.fromkeys(data["only_sentiments"]) if x in ("positive", "neutral", "negative")]
    if (data.get("speed_to_lead_agent_id") or "").strip() or (data.get("activity_agent_id") or "").strip():
        await entitlements.require(db, ctx.org, "workflows", "Workflow triggers (call new leads automatically) are "
                                   "included from the Growth plan.")
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
    if "activity_agent_id" in data:
        aid = (data["activity_agent_id"] or "").strip()
        if aid:
            if not p.can_activity:
                raise HTTPException(status_code=400, detail=f"{p.name} doesn't send activity yet.")
            try:
                a = await db.get(Agent, uuid.UUID(aid))
            except ValueError:
                a = None
            if not a or a.org_id != ctx.org.id:
                raise HTTPException(status_code=404, detail="Agent not found")
            if s.get("activity_agent_id") != aid:
                s["activity_since"] = dt.datetime.now(dt.timezone.utc).isoformat()
                s["activity_pending"] = []
            s["activity_agent_id"] = aid
        else:
            s["activity_agent_id"], s["activity_pending"] = None, []
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
    campaign_id: str | None = Field(default=None, max_length=64)


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
                                            skip_contacted=body.skip_contacted, list_tag=body.list_tag,
                                            campaign_id=await _campaign_id(db, ctx, body.campaign_id))
    except CrmError as exc:
        await sync.add_log(db, conn, "import", "error", f"Import failed: {exc}")
        await db.commit()
        raise HTTPException(status_code=400, detail=f"Import failed: {exc}") from exc
    await db.commit()
    sync.wake_campaigns()
    return result


async def _campaign_id(db, ctx, raw: str | None) -> str | None:
    if not raw:
        return None
    from app.models.campaign import Campaign

    try:
        campaign = await db.get(Campaign, uuid.UUID(raw))
    except ValueError:
        campaign = None
    if not campaign or campaign.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return str(campaign.id)


# ── Auto-sync rules: re-run a saved import on a schedule ──────────────────────


class AutoRuleIn(BaseModel):
    name: str = Field(default="", max_length=80)
    filters: dict[str, list[str] | str | bool] = Field(default_factory=dict)
    skip_contacted: bool = False
    list_tag: str = Field(default="", max_length=60)
    campaign_id: str | None = Field(default=None, max_length=64)
    every_minutes: int = 60
    enabled: bool = True
    summary: str = Field(default="", max_length=300)  # human description of the filters, for the list


async def _rule_from(body: AutoRuleIn, ctx, db, p: Provider) -> dict:
    if body.every_minutes not in sync.AUTO_EVERY:
        raise HTTPException(status_code=400, detail="Pick how often to check: 15 min, 1 hour, 4 hours or daily.")
    imp = ImportIn(filters=body.filters, skip_contacted=body.skip_contacted)
    return {"name": body.name.strip() or f"{p.name} auto-sync", "filters": _filters(imp),
            "skip_contacted": body.skip_contacted, "list_tag": body.list_tag.strip(),
            "campaign_id": await _campaign_id(db, ctx, body.campaign_id), "every_minutes": body.every_minutes,
            "enabled": body.enabled, "summary": body.summary.strip()}


@router.post("/{key}/auto-imports", status_code=201)
async def create_auto_rule(key: str, body: AutoRuleIn, ctx: ManagerDep, db: DbDep):
    p = _provider(key)
    conn = await _require_conn(db, ctx.org.id, key)
    if not p.can_import:
        raise HTTPException(status_code=400, detail=f"{p.name} doesn't have contacts to sync.")
    await entitlements.require(db, ctx.org, "workflows", "Scheduled CRM imports are included from the Growth plan.")
    rules = sync.auto_rules(conn)
    if len(rules) >= 10:
        raise HTTPException(status_code=400, detail="You can have up to 10 auto-sync rules per integration.")
    rule = {"id": uuid.uuid4().hex[:12], **await _rule_from(body, ctx, db, p), "runs": 0}
    conn.settings = {**(conn.settings or {}), "auto_imports": [*rules, rule]}
    await sync.add_log(db, conn, "test", "ok", f"Auto-sync “{rule['name']}” created — checks every "
                       f"{_every_label(rule['every_minutes'])}.")
    await db.commit()
    await db.refresh(conn)
    return conn_to_dict(conn)


def _every_label(m: int) -> str:
    return {15: "15 minutes", 60: "hour", 240: "4 hours", 1440: "day"}.get(m, f"{m} minutes")


@router.put("/{key}/auto-imports/{rule_id}")
async def update_auto_rule(key: str, rule_id: str, body: AutoRuleIn, ctx: ManagerDep, db: DbDep):
    p = _provider(key)
    conn = await _require_conn(db, ctx.org.id, key)
    rules = sync.auto_rules(conn)
    rule = next((r for r in rules if r.get("id") == rule_id), None)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.update(await _rule_from(body, ctx, db, p))
    conn.settings = {**(conn.settings or {}), "auto_imports": rules}
    await db.commit()
    await db.refresh(conn)
    return conn_to_dict(conn)


@router.delete("/{key}/auto-imports/{rule_id}")
async def delete_auto_rule(key: str, rule_id: str, ctx: ManagerDep, db: DbDep):
    conn = await _require_conn(db, ctx.org.id, key)
    conn.settings = {**(conn.settings or {}), "auto_imports": [r for r in sync.auto_rules(conn) if r.get("id") != rule_id]}
    await db.commit()
    await db.refresh(conn)
    return conn_to_dict(conn)


@router.post("/{key}/auto-imports/{rule_id}/run")
async def run_auto_rule_now(key: str, rule_id: str, ctx: ManagerDep, db: DbDep):
    conn = await _require_conn(db, ctx.org.id, key)
    try:
        result = await sync.run_auto_rule(db, conn, rule_id)
    except CrmError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await db.commit()
    sync.wake_campaigns()
    await db.refresh(conn)
    return {"result": result, "connection": conn_to_dict(conn)}


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


# ── Script variables: fill an agent's {{variables}} from CRM fields ─────────────


@router.get("/{key}/variables")
async def script_variables(key: str, agent_id: uuid.UUID, ctx: ManagerDep, db: DbDep):
    """The agent's {{variables}}, the CRM fields to fill them from, the saved choices and a sample contact."""
    from app.models.agent import Agent
    from app.models.lead import Lead
    from app.services.crm import variables as crm_vars

    conn = await _get_conn(db, ctx.org.id, key)
    agent = await db.get(Agent, agent_id)
    if not conn or not agent or agent.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Not found")
    p, http = sync.http_for(conn)
    try:
        catalog = await p.field_catalog(http, conn.config or {})
    except CrmError as exc:
        raise HTTPException(status_code=400, detail=f"Couldn't read {p.name}'s fields: {exc}") from exc
    keys = {f["key"] for f in catalog}
    mapping = ((conn.settings or {}).get("var_maps") or {}).get(str(agent.id)) or {}
    # A recent contact from this CRM, so each row can show a real value.
    sample: dict = {}
    for lead in (await db.execute(select(Lead).where(Lead.org_id == ctx.org.id).order_by(Lead.updated_at.desc())
                                  .limit(200))).scalars():
        got = ((lead.custom_fields or {}).get("crm_fields") or {}).get(key)
        if got:
            sample = {"name": lead.name, "fields": got}
            break
    if not sample:
        lead = (await db.execute(select(Lead).where(Lead.org_id == ctx.org.id, Lead.crm_refs.is_not(None))
                                 .order_by(Lead.updated_at.desc()).limit(50))).scalars().all()
        ref = next(((l, (l.crm_refs or {}).get(key)) for l in lead if (l.crm_refs or {}).get(key)), None)
        if ref:
            try:
                sample = {"name": ref[0].name, "fields": await p.person_fields(http, conn.config or {}, ref[1])}
            except CrmError:
                sample = {}
    rows = []
    for var in crm_vars.script_variables(agent):
        auto = crm_vars.auto_field(var, keys)
        chosen = mapping.get(var, "")
        field_key = None if chosen == "-" else (chosen or auto)
        rows.append({"name": var, "built_in": var in crm_vars.BUILT_IN, "mapped_to": chosen, "auto": auto,
                     "sample": (sample.get("fields") or {}).get(field_key or "", "")})
    return {"variables": rows, "fields": catalog, "sample_contact": sample.get("name")}


class VariablesIn(BaseModel):
    agent_id: uuid.UUID
    map: dict[str, str] = Field(default_factory=dict)  # var → field key, "" = automatic, "-" = don't fill


@router.put("/{key}/variables")
async def save_script_variables(key: str, body: VariablesIn, ctx: ManagerDep, db: DbDep):
    from app.models.agent import Agent

    conn = await _get_conn(db, ctx.org.id, key)
    agent = await db.get(Agent, body.agent_id)
    if not conn or not agent or agent.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Not found")
    clean = {k[:64]: v[:64] for k, v in body.map.items() if v}
    maps = {**((conn.settings or {}).get("var_maps") or {}), str(agent.id): clean}
    conn.settings = {**(conn.settings or {}), "var_maps": maps}
    await sync.add_log(db, conn, "test", "ok", f"Script variables saved for {agent.name}.")
    await db.commit()
    return {"saved": len(clean)}
