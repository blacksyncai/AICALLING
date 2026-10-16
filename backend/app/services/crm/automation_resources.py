"""CRM resources exposed to Radar. No writes occur during catalog reads or drafting."""
import uuid
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.models.radar_automation import RadarPond
from app.services.crm import sync
from app.services.crm.http import CrmError
from app.services.crm.providers import PROVIDERS


async def fub_collection(http, resource: str) -> list[dict]:
    # Follow only this endpoint's continuation cursor, never a provider-supplied arbitrary URL.
    from urllib.parse import parse_qsl, urlparse
    path = f"/v1/{resource}"
    params, rows, seen = {"limit": 100}, [], set()
    for _ in range(30):
        page = await http.request("GET", path, params=params)
        rows.extend(x for x in page.get(resource, []) if isinstance(x, dict))
        link = (page.get("_metadata") or {}).get("nextLink")
        if not link:
            return rows
        parsed = urlparse(link)
        if parsed.path != path or link in seen:
            raise CrmError("The CRM returned an invalid resource continuation.")
        seen.add(link)
        params = dict(parse_qsl(parsed.query))
    raise CrmError("Too many CRM resources to load safely. Narrow the CRM resource list.")


async def resources(db, conn) -> dict:
    p, http = sync.http_for(conn)
    internal = (await db.execute(select(RadarPond).where(RadarPond.org_id == conn.org_id).order_by(RadarPond.name))).scalars()
    out = {"provider": conn.provider, "provider_name": p.name,
           "blacksync_ponds": [{"id": str(x.id), "name": x.name} for x in internal],
           "crm_ponds": [], "pipelines": [], "deal_pipelines": [], "warnings": [],
           "capabilities": {"create_blacksync_pond": True, "route_pond": False, "route_stage": bool(p.pipeline_noun),
                            "tag": conn.provider == "followupboss", "create_pond": False,
                            "create_stage": False, "create_pipeline": False}}
    if p.pipeline_noun:
        try:
            out["pipelines"] = await p.pipelines(http, conn.config or {})
            out["capabilities"]["create_stage"] = conn.provider == "followupboss"
        except CrmError as exc:
            out["warnings"].append(f"Couldn't load stages: {exc}")
    if conn.provider == "followupboss":
        try:
            ponds = await fub_collection(http, "ponds")
            out["crm_ponds"] = [{"id": str(x["id"]), "name": x.get("name") or str(x["id"])} for x in ponds if x.get("id")]
            out["capabilities"].update(route_pond=True, create_pond=True)
        except CrmError as exc:
            out["warnings"].append(f"Couldn't load ponds: {exc}")
        try:
            from app.services.crm.fub_pipelines import catalog
            out["deal_pipelines"] = [catalog(x) for x in await fub_collection(http, "pipelines") if x.get("id")]
            out["capabilities"]["create_pipeline"] = True
        except CrmError as exc:
            out["warnings"].append(f"Couldn't load deal pipelines: {exc}")
    if p.can_install and p.install_style == "pipeline":
        out["capabilities"]["create_pipeline"] = True
        out["deal_pipelines"] = [{"id": str(x["id"]), "name": x["name"]} for x in out["pipelines"]]
    from app.services.crm.assistant import capabilities
    out["assistant_tools"] = capabilities(conn.provider)
    return out


async def create_resource(db, conn, kind: str, name: str, stages=None) -> dict:
    name = name.strip()
    if not name or len(name) > 120:
        raise CrmError("Use a resource name between 1 and 120 characters.")
    if kind == "blacksync_pond":
        # The caller locks the connection for creation. The DB also enforces org/name uniqueness.
        row = (await db.execute(select(RadarPond).where(RadarPond.org_id == conn.org_id,
                                                       RadarPond.name == name))).scalar_one_or_none()
        if row is None:
            try:
                async with db.begin_nested():
                    row = RadarPond(org_id=conn.org_id, name=name)
                    db.add(row)
                    await db.flush()
            except IntegrityError:
                row = (await db.execute(select(RadarPond).where(
                    RadarPond.org_id == conn.org_id, RadarPond.name == name))).scalar_one()
        return {"id": str(row.id), "name": row.name, "kind": kind, "location": "BlackSync"}
    p = PROVIDERS[conn.provider]
    if kind == "crm_pipeline" and p.can_install and p.install_style == "pipeline":
        if not stages:
            raise CrmError("Specify the pipeline stages before creating it.")
        _, http = sync.http_for(conn)
        result = await p.install_pipeline(http, conn.config or {}, name, [
            {"key": f"stage_{i}", "label": stage.label, "kind": stage.kind} for i, stage in enumerate(stages)])
        if not result.get("id"): raise CrmError("The CRM did not confirm the pipeline result.")
        return {"id": str(result["id"]), "name": result.get("name") or name, "kind": kind, "location": p.name}
    if conn.provider != "followupboss" or kind not in ("crm_pond", "crm_stage", "crm_pipeline"):
        raise CrmError("This CRM does not expose that resource-creation action in Radar.")
    if kind == "crm_pipeline":
        from app.services.crm.fub_pipelines import ensure_pipeline
        _, http = sync.http_for(conn)
        result = await ensure_pipeline(http, name, stages or [])
        await sync.add_log(db, conn, "radar", "ok", f"Radar pipeline ready: {name}.")
        return {**result, "kind": kind, "location": "Follow Up Boss"}
    if stages: raise CrmError("Only deal pipelines accept embedded deal stages.")
    resource = {"crm_pond": "ponds", "crm_stage": "stages", "crm_pipeline": "pipelines"}[kind]
    _, http = sync.http_for(conn)
    existing = await fub_collection(http, resource)
    row = next((x for x in existing if (x.get("name") or "").casefold() == name.casefold()), None)
    if row is None:
        row = await http.request("POST", f"/v1/{resource}", json={"name": name})
        row = row.get(resource[:-1], row)
    if not row.get("id"):
        raise CrmError("The CRM did not confirm creation. Refresh the resource list before retrying.")
    await sync.add_log(db, conn, "radar", "ok", f"Radar resource ready: {name} ({resource}).")
    return {"id": str(row["id"]), "name": row.get("name") or name, "kind": kind, "location": "Follow Up Boss"}


async def validate_spec(db, conn, spec, *, catalog=None):
    from app.models.agent import Agent
    from app.models.campaign import Campaign
    for model, key in ((Agent, spec.source.agent_id), (Campaign, spec.source.campaign_id)):
        if key:
            obj = await db.get(model, key)
            if obj is None or obj.org_id != conn.org_id:
                raise CrmError("The source agent or campaign is not in this workspace.")
    data = catalog if catalog is not None else await resources(db, conn)
    ponds = {r["id"] for r in data["crm_ponds"]}
    if spec.source.pond_id and spec.source.pond_id not in ponds:
        raise CrmError("Choose a source pond from this CRM connection.")
    for action in spec.actions:
        if action.kind == "blacksync_pond":
            try:
                row = await db.get(RadarPond, uuid.UUID(action.target_id))
            except ValueError:
                row = None
            if not row or row.org_id != conn.org_id:
                raise CrmError("Choose a BlackSync pond in this workspace.")
        elif action.kind == "crm_pond":
            if not data["capabilities"]["route_pond"] or action.target_id not in ponds:
                raise CrmError("Choose an available CRM pond.")
        elif action.kind == "crm_stage":
            pipe = next((p for p in data["pipelines"] if p["id"] == action.pipeline_id), None)
            if not pipe or action.target_id not in {s["id"] for s in pipe.get("stages", [])}:
                raise CrmError("Choose a stage from this CRM connection.")
        elif not data["capabilities"]["tag"]:
            raise CrmError("This CRM does not support Radar tag actions.")
    return data
