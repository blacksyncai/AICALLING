"""Follow Up Boss deal pipelines carry embedded stages; /stages is for people.

Payload shape: PipelineInput.stages[{id?, name, orderWeight?, closedStage?, ...}].
Cross-checked against @bara-agency/fub-sdk 0.1.1 PipelineInput/PipelineStage.
"""
from app.services.crm.http import CrmError
from app.services.crm.automation_resources import fub_collection


def catalog(row):
    return {"id": str(row["id"]), "name": row.get("name") or str(row["id"]),
            "stages": [{"id": str(s["id"]), "label": s.get("name") or str(s["id"]),
                        "kind": "closed" if s.get("closedStage") else "active"}
                       for s in row.get("stages") or [] if s.get("id")]}


def unpack(response):
    row = response.get("pipeline", response) if isinstance(response, dict) else None
    if not row or not row.get("id"): raise CrmError("Follow Up Boss did not confirm a pipeline ID. Check the CRM before retrying.")
    return row


async def get_pipeline(http, pipeline_id):
    if not str(pipeline_id).isascii() or not str(pipeline_id).isdigit() or int(pipeline_id) < 1:
        raise CrmError("Choose a numeric Follow Up Boss deal-pipeline ID.")
    row = unpack(await http.request("GET", f"/v1/pipelines/{int(pipeline_id)}"))
    if str(row["id"]) != str(pipeline_id): raise CrmError("Follow Up Boss returned a different pipeline than requested.")
    return row


def check_requested(row, stages):
    by_name = {}
    for stage in row.get("stages") or []:
        key = (stage.get("name") or "").strip().casefold()
        if key in by_name: raise CrmError("This pipeline has ambiguous stage names. Resolve them in the CRM first.")
        by_name[key] = stage
    for requested in stages:
        have = by_name.get(requested.label.casefold())
        if have and bool(have.get("closedStage")) != (requested.kind != "active"):
            raise CrmError(f"Stage '{requested.label}' already exists with a different open/closed setting; existing stages were not changed.")
    return by_name


def verify(row, stages, preserved_ids=()):
    existing = check_requested(row, stages)
    if any(s.label.casefold() not in existing or not existing[s.label.casefold()].get("id") for s in stages):
        raise CrmError("Follow Up Boss has not confirmed all requested stages. Check the pipeline before retrying.")
    if not set(preserved_ids).issubset({str(s.get("id")) for s in row.get("stages") or []}):
        raise CrmError("The CRM response did not preserve all existing stage IDs. Check the pipeline before making further changes.")
    return catalog(row)


async def add_stages(http, pipeline_id, stages):
    row = await get_pipeline(http, pipeline_id)
    have = check_requested(row, stages)
    missing = [s for s in stages if s.label.casefold() not in have]
    if not missing: return verify(row, stages)
    old = row.get("stages") or []
    if any(not s.get("id") for s in old): raise CrmError("Cannot safely extend a pipeline with missing stage IDs.")
    old_ids = [str(s["id"]) for s in old]
    allowed = {"id", "name", "description", "orderWeight", "color", "closedStage"}
    payload = [{k: v for k, v in s.items() if k in allowed} for s in old]
    order = max([float(s.get("orderWeight") or 0) for s in old] or [0])
    payload += [{"name": s.label, "closedStage": s.kind != "active", "orderWeight": order + (i + 1) * 10}
                for i, s in enumerate(missing)]
    await http.request("PUT", f"/v1/pipelines/{int(pipeline_id)}", json={"stages": payload})
    # Read back the persisted stages, never infer success from a 2xx alone.
    result = await get_pipeline(http, pipeline_id)
    return verify(result, stages, old_ids)


async def ensure_pipeline(http, name, stages):
    matches = [p for p in await fub_collection(http, "pipelines")
               if (p.get("name") or "").strip().casefold() == name.strip().casefold()]
    if len(matches) > 1: raise CrmError("More than one Follow Up Boss pipeline has this name. Select its ID explicitly.")
    if matches:
        return await add_stages(http, matches[0]["id"], stages)
    body = {"name": name}
    if stages:
        body["stages"] = [{"name": s.label, "closedStage": s.kind != "active", "orderWeight": (i + 1) * 10}
                          for i, s in enumerate(stages)]
    row = unpack(await http.request("POST", "/v1/pipelines", json=body))
    result = await get_pipeline(http, row["id"])
    if (result.get("name") or "").strip().casefold() != name.strip().casefold():
        raise CrmError("The CRM did not confirm the requested pipeline name.")
    return verify(result, stages)
