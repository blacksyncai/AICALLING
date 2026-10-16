"""Shared CRM tools backed by existing adapters. Writes require an explicit command confirmation."""
import hashlib
import json
from sqlalchemy import select, update
from app.models.crm_command import CrmCommand
from app.models.radar_automation import now
from app.services.crm import sync
from app.services.crm.http import CrmError
from app.services.crm.providers import Contact, PROVIDERS, Provider
from app.services.crm.assistant_schema import CommandSpec, READS

NOTES = {"close", "followupboss", "highlevel", "attio", "zoho", "sierra"}

def capabilities(provider):
    p = PROVIDERS[provider]
    tools = ["list_contacts", "find_contact", "create_contact"] if p.category == "crm" else []
    if p.pipeline_noun: tools += ["list_pipelines", "move_stage"]
    if p.can_install and p.install_style == "pipeline": tools += ["create_pipeline", "add_stages"]
    if p.can_map_fields: tools += ["field_catalog", "contact_fields"]
    if provider in NOTES: tools += ["add_note"]
    if type(p).mark_dnc is not Provider.mark_dnc: tools += ["mark_dnc"]
    if provider == "followupboss": tools += ["create_task", "create_pond", "create_stage", "create_pipeline", "add_stages"]
    return [{"action": t, "writes": t not in READS} for t in tools]


def command_out(row, provider):
    return {"id": str(row.id), "provider": provider, "provider_name": PROVIDERS[provider].name,
            "account_label": row.account_label, "spec": row.spec,
            "writes": row.spec["action"] not in READS, "status": row.status,
            "result": row.result, "error": row.error, "created_at": row.created_at.isoformat()}


def fingerprint(conn):
    snapshot = {"provider": conn.provider, "secret": getattr(conn, "secret_enc", None),
                "method": getattr(conn, "method", ""), "config": conn.config or {},
                "account": getattr(conn, "account_label", "")}
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()


def check_supported(conn, spec):
    if spec.external_id and conn.provider in {"followupboss", "pipedrive", "lofty"} and (not spec.external_id.isascii() or not spec.external_id.isdigit() or int(spec.external_id) < 1):
        raise CrmError("Choose a valid numeric contact ID from this CRM.")
    if spec.action == "create_pipeline":
        if conn.provider != "followupboss" and not spec.stages:
            raise CrmError("Specify the pipeline stages for review before creating it.")
    if spec.action not in {t["action"] for t in capabilities(conn.provider)}:
        raise CrmError(f"{PROVIDERS[conn.provider].name} does not expose {spec.action} in BlackSync yet.")


async def checked_pipeline(conn, spec):
    p, http = sync.http_for(conn)
    if conn.provider == "followupboss" and spec.action == "add_stages":
        from app.services.crm.fub_pipelines import get_pipeline, catalog
        return catalog(await get_pipeline(http, spec.pipeline_id))
    pipelines = await p.pipelines(http, conn.config or {})
    selected = next((x for x in pipelines if str(x["id"]) == spec.pipeline_id), None)
    if selected is None: raise CrmError("Choose an existing pipeline in this CRM account.")
    if spec.action == "move_stage" and spec.stage_id not in {str(s["id"]) for s in selected.get("stages", [])}:
        raise CrmError("Choose a stage from the selected pipeline.")
    if spec.action == "add_stages" and sum(x["name"].casefold() == selected["name"].casefold() for x in pipelines) != 1:
        raise CrmError("Pipeline names are ambiguous; rename them in the CRM before adding stages.")
    return selected


async def prepare(db, conn, user_id, spec):
    check_supported(conn, spec)
    if spec.action in ("add_stages", "move_stage"): await checked_pipeline(conn, spec)
    snapshot = spec.model_dump(mode="json", exclude_defaults=True)
    if spec.stages: snapshot["stages"] = [stage.model_dump() for stage in spec.stages]
    if spec.action == "list_contacts": snapshot["limit"] = spec.limit
    if spec.action == "add_note": snapshot["name"] = spec.name or "BlackSync assistant note"
    row = CrmCommand(org_id=conn.org_id, connection_id=conn.id, created_by=user_id,
                     account_label=conn.account_label, connection_fingerprint=fingerprint(conn), spec=snapshot)
    db.add(row); await db.flush()
    return row


def contact_out(c):
    return {"id": c.external_id, "name": c.name, "phone": c.phone, "email": c.email,
            "company": c.company, "stage": c.stage, "do_not_call": c.dnc}


async def add_note(p, http, cfg, external_id, text, title):
    # These are existing native note paths used by the platform's call-log adapters.
    if p.key == "close":
        return await http.request("POST", "/v1/activity/note/", json={"lead_id": external_id, "note": text})
    if p.key == "followupboss":
        return await http.request("POST", "/v1/notes", json={"personId": int(external_id), "subject": title, "body": text})
    if p.key == "highlevel":
        return await http.request("POST", f"/contacts/{external_id}/notes", json={"body": text})
    if p.key == "attio":
        return await http.request("POST", "/v2/notes", json={"data": {"parent_object": "people", "parent_record_id": external_id, "title": title, "format": "plaintext", "content": text}})
    if p.key == "zoho":
        return await http.request("POST", f"/crm/v6/Leads/{external_id}/Notes", json={"data": [{"Note_Title": title, "Note_Content": text}]})
    if p.key == "sierra":
        return await p._call(http, "POST", f"/leads/{external_id}/note", json={"message": title + "\n\n" + text, "shouldNotify": False})
    raise CrmError("Native notes are not enabled for this CRM.")


async def perform(db, conn, spec):
    check_supported(conn, spec)
    p, http = sync.http_for(conn); cfg = conn.config or {}
    action = spec.action
    if action == "list_contacts":
        contacts = await p.list_contacts(http, cfg, limit=spec.limit)
        contacts = contacts[:spec.limit]
        query = spec.query.casefold()
        rows = [contact_out(c) for c in contacts if not query or query in " ".join((c.name,c.phone,c.email,c.company)).casefold()]
        return {"contacts": rows, "scanned": len(contacts), "limit": spec.limit,
                "scope": "Filtered within this bounded page; this is not an exhaustive CRM-wide search."}
    if action in ("find_contact", "create_contact"):
        c = Contact(name=spec.name, phone=spec.phone, email=spec.email, company=spec.company)
        external_id = await p.find_or_create(http, cfg, c, create=action == "create_contact")
        if not external_id: return {"found": False, "message": "No exact match returned by the provider."}
        return {"id": str(external_id), "found": True, "message": "Contact found or created" if action == "create_contact" else "Contact found"}
    if action == "list_pipelines":
        if conn.provider == "followupboss":
            from app.services.crm.fub_pipelines import catalog
            from app.services.crm.automation_resources import fub_collection
            return {"pipelines": [catalog(row) for row in (await fub_collection(http, "pipelines"))[:100]],
                    "person_stages": await p.pipelines(http, cfg), "limit": 100}
        return {"pipelines": (await p.pipelines(http, cfg))[:100], "limit": 100}
    if action in ("create_pipeline", "add_stages") and conn.provider == "followupboss":
        from app.services.crm.fub_pipelines import ensure_pipeline, add_stages
        result = await ensure_pipeline(http, spec.name, spec.stages) if action == "create_pipeline" else await add_stages(http, spec.pipeline_id, spec.stages)
        return {"pipeline": result, "message": "Follow Up Boss confirmed the pipeline and requested stages."}
    if action in ("create_pipeline", "add_stages"):
        name = spec.name if action == "create_pipeline" else (await checked_pipeline(conn, spec))["name"]
        stages = [{"key": f"stage_{i}", "label": s.label, "kind": s.kind} for i,s in enumerate(spec.stages)]
        result = await p.install_pipeline(http, cfg, name, stages)
        if not result.get("id"): raise CrmError("The CRM did not confirm the pipeline result.")
        return {"pipeline": result, "message": "Pipeline and requested stages are ready; existing records were preserved."}
    if action == "move_stage":
        pipe = await checked_pipeline(conn, spec)
        result = await p.set_stage(http, cfg, spec.external_id, pipe, spec.stage_id, create=False, forward_only=True)
        return {"message": result or "No change: record absent, already in this stage, or protected by forward-only rules."}
    if action == "field_catalog": return {"fields": (await p.field_catalog(http, cfg))[:100]}
    if action == "contact_fields": return {"id": spec.external_id, "fields": await p.person_fields(http, cfg, spec.external_id)}
    if action == "add_note":
        response = await add_note(p, http, cfg, spec.external_id, spec.text, spec.name or "BlackSync assistant note")
        if isinstance(response, dict):
            if response.get("success") is False or response.get("status") == "error":
                raise CrmError("The CRM rejected the note request.")
            if any(x.get("status") == "error" for x in response.get("data") or [] if isinstance(x, dict)):
                raise CrmError("The CRM rejected the note request.")
        return {"message": "The CRM accepted the note request.", "id": spec.external_id}
    if action == "mark_dnc":
        await p.mark_dnc(http, cfg, spec.external_id)
        # Keep imported local records suppressed too, without changing unrelated contacts.
        from app.models.lead import Lead
        await db.execute(update(Lead).where(Lead.org_id == conn.org_id,
            Lead.crm_refs[conn.provider].as_string() == spec.external_id).values(do_not_call=True))
        return {"message": "Do-not-call applied in the CRM and linked BlackSync contacts.", "id": spec.external_id}
    if action == "create_task":
        result = await http.request("POST", "/v1/tasks", json={"personId": int(spec.external_id), "name": spec.name, "type": "Follow Up", "dueDate": spec.due_date.isoformat()})
        if not result.get("id"): raise CrmError("The CRM did not confirm task creation; check the CRM before retrying.")
        return {"id": str(result["id"]), "message": "Follow-up task created."}
    if action in ("create_pond", "create_stage"):
        from app.services.crm.automation_resources import create_resource
        return await create_resource(db, conn, "crm_pond" if action == "create_pond" else "crm_stage", spec.name)
    raise CrmError("Unsupported action")


async def execute(db, row, conn, org):
    """Claim once. An interrupted write is never silently retried."""
    from datetime import timedelta, timezone
    if row.status == "succeeded": return row
    if row.status != "draft": raise CrmError("This command was already attempted. Check the CRM and activity before preparing another.")
    stamp = row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else row.created_at
    if now() - stamp > timedelta(minutes=30): raise CrmError("This proposal expired. Ask the assistant for a fresh preview.")
    if not org or org.status != "active": raise CrmError("This workspace is suspended or unavailable.")
    if row.org_id != conn.org_id or row.connection_id != conn.id: raise CrmError("Connection does not belong to this command.")
    if row.connection_fingerprint != fingerprint(conn):
        raise CrmError("This CRM connection changed. Prepare a fresh preview for the current account.")
    if conn.status != "connected": raise CrmError("Reconnect this CRM before applying changes.")
    spec = CommandSpec.model_validate(row.spec)
    check_supported(conn, spec)
    claimed = await db.execute(update(CrmCommand).where(CrmCommand.id == row.id, CrmCommand.status == "draft").values(status="running", updated_at=now()))
    await db.commit()
    if claimed.rowcount != 1: raise CrmError("This command is already running or completed.")
    try:
        result = await perform(db, conn, spec)
        row.result, row.status, row.error = result, "succeeded", ""
        await sync.add_log(db, conn, "assistant", "ok", f"CRM assistant: {spec.action}")
        await db.commit()
    except Exception as exc:
        await db.rollback()
        await db.refresh(row)
        # A response may be lost after the remote write. Never promise a safe blind retry.
        row.status = "failed" if spec.action in READS else "uncertain"
        row.error = (str(exc)[:400] + (" Check the CRM before preparing another write." if spec.action not in READS else ""))
        row.updated_at = now()
        await db.commit()
    return row
