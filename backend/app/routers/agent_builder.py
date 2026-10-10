"""
Agent builder — catalog, resumable wizard drafts, AI generation of a real agent,
and editor helpers (improve with AI, regenerate a section, launch readiness).
Contract: docs/agent-builder.md. Everything is scoped to the caller's organization.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent import catalog, generator, pipeline
from app.agent.voices import DEFAULT_VOICE_ID
from app.models.agent import Agent
from app.models.builder import AgentDraft
from app.services.auth import Context, CtxDep, DbDep

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/agent-builder", tags=["agent_builder"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class DraftCreate(BaseModel):
    data: dict[str, Any] | None = None
    step: int = Field(default=1, ge=1, le=8)


class DraftUpdate(BaseModel):
    data: dict[str, Any] | None = None
    step: int | None = Field(default=None, ge=1, le=8)


class GenerateRequest(BaseModel):
    draft_id: uuid.UUID


class AssistRequest(BaseModel):
    draft_id: uuid.UUID


class ImproveRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)


class RegenerateRequest(BaseModel):
    section: str
    instruction: str = Field(default="", max_length=2000)


# ── Helpers ───────────────────────────────────────────────────────────────────


def draft_to_dict(d: AgentDraft) -> dict:
    return {
        "id": str(d.id),
        "step": d.step,
        "data": d.data or {},
        "agent_id": str(d.agent_id) if d.agent_id else None,
        "generation": generation_to_dict(d),
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


async def _get_draft(db, ctx: Context, draft_id: uuid.UUID) -> AgentDraft:
    draft = await db.get(AgentDraft, draft_id)
    if not draft or draft.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


async def _get_agent(db, ctx: Context, agent_id: uuid.UUID) -> Agent:
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def _run_llm(coro):
    """Map LLM failures to plain HTTP errors."""
    from app.services.llm import LLMNotConfigured

    try:
        return await coro
    except LLMNotConfigured:
        raise HTTPException(status_code=400, detail=generator.NOT_CONFIGURED)
    except generator.GenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("agent_builder_llm_failed", error=str(exc))
        raise HTTPException(status_code=502, detail="The AI service didn't respond. Please try again in a moment.")


# ── Catalog ───────────────────────────────────────────────────────────────────


@router.get("/catalog")
async def get_catalog(_: CtxDep):
    return catalog.catalog()


# ── Drafts ────────────────────────────────────────────────────────────────────


@router.get("/drafts")
async def list_drafts(ctx: CtxDep, db: DbDep):
    drafts = (await db.execute(
        select(AgentDraft).where(AgentDraft.org_id == ctx.org.id).order_by(AgentDraft.updated_at.desc())
    )).scalars().all()
    drafts = sorted(drafts, key=lambda d: d.agent_id is not None)  # stable: unfinished first, newest first
    return {"drafts": [draft_to_dict(d) for d in drafts]}


@router.post("/drafts", status_code=201)
async def create_draft(body: DraftCreate, ctx: CtxDep, db: DbDep):
    draft = AgentDraft(org_id=ctx.org.id, step=body.step, data=body.data or {}, created_by=ctx.user.id)
    db.add(draft)
    await db.commit()
    await db.refresh(draft)
    return draft_to_dict(draft)


@router.get("/drafts/{draft_id}")
async def get_draft(draft_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    return draft_to_dict(await _get_draft(db, ctx, draft_id))


@router.patch("/drafts/{draft_id}")
async def update_draft(draft_id: uuid.UUID, body: DraftUpdate, ctx: CtxDep, db: DbDep):
    draft = await _get_draft(db, ctx, draft_id)
    if body.data is not None:
        draft.data = body.data
    if body.step is not None:
        draft.step = body.step
    await db.commit()
    await db.refresh(draft)
    return draft_to_dict(draft)


@router.delete("/drafts/{draft_id}", status_code=204)
async def delete_draft(draft_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    draft = await _get_draft(db, ctx, draft_id)
    await db.delete(draft)
    await db.commit()


# ── Generate ──────────────────────────────────────────────────────────────────


@router.post("/assist")
async def assist(body: AssistRequest, ctx: CtxDep, db: DbDep):
    """Reads the saved draft's goal (presets, own words, extra instructions, Q&A so far) and returns a short
    "Got it…" summary plus 0–3 follow-up questions. Read-only: the client stores the conversation in the draft."""
    draft = await _get_draft(db, ctx, body.draft_id)
    try:
        generator.draft_brief(draft.data or {}, require_business=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await _run_llm(generator.assist(draft.data or {}))


GEN_TIMEOUT = timedelta(minutes=10)


def generation_to_dict(d: AgentDraft) -> dict:
    status = d.gen_status
    error = d.gen_error
    if status == "running" and d.gen_started_at:
        started = d.gen_started_at if d.gen_started_at.tzinfo else d.gen_started_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - started > GEN_TIMEOUT:
            status, error = "failed", "Generation was interrupted. Please try again."
    return {
        "status": status or "idle",
        "stage": d.gen_stage,
        "stages": [{"key": k, "label": label} for k, label in pipeline.STAGES],
        "error": error,
        "agent_id": str(d.agent_id) if d.agent_id else None,
    }


@router.post("/generate", status_code=202)
async def generate(body: GenerateRequest, background: BackgroundTasks, ctx: CtxDep, db: DbDep):
    """Start generating the agent in the background; poll GET /drafts/{id}/generation for progress."""
    draft = await _get_draft(db, ctx, body.draft_id)
    if draft.agent_id:
        return generation_to_dict(draft)
    try:
        generator.validate_draft(draft.data or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    from app.config import settings

    if not settings.openai_api_key:
        raise HTTPException(status_code=400, detail=generator.NOT_CONFIGURED)
    if generation_to_dict(draft)["status"] == "running":
        return generation_to_dict(draft)
    draft.gen_status, draft.gen_stage, draft.gen_error = "running", "context", None
    draft.gen_started_at = datetime.now(timezone.utc)
    await db.commit()
    background.add_task(run_generation, draft.id, ctx.org.id, ctx.user.id)
    return generation_to_dict(draft)


@router.get("/drafts/{draft_id}/generation")
async def generation_status(draft_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    return generation_to_dict(await _get_draft(db, ctx, draft_id))


async def run_generation(draft_id: uuid.UUID, org_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    """The generation job: context → spec → compose → quality gate → saved agent. Never raises."""
    from app.database import AsyncSessionLocal
    from app.models.account import Organization
    from app.services.agent_versions import snapshot
    from app.services.llm import LLMNotConfigured

    async with AsyncSessionLocal() as db:
        draft = await db.get(AgentDraft, draft_id)
        org = await db.get(Organization, org_id)
        if not draft or not org or draft.org_id != org.id:
            return

        async def stage(key: str) -> None:
            draft.gen_stage = key
            await db.commit()

        try:
            data = draft.data or {}
            ctx = await pipeline.assemble_context(db, org, data, draft.id)
            result = await pipeline.run(ctx, stage)
            await stage("save")
            agent = _agent_from_result(org.id, draft, data, ctx, result,
                                       await generator.knowledge_for(db, org.id))
            db.add(agent)
            await db.flush()
            await snapshot(db, agent, "generated", user_id, note="Built with AI")
            draft.agent_id = agent.id
            draft.gen_status, draft.gen_stage = "done", "save"
            await db.commit()
            log.info("agent_generated", agent_id=str(agent.id), words=result["report"]["words"],
                     repairs=result["report"].get("repairs"), playbooks=[p["slug"] for p in ctx["playbooks"]])
        except Exception as exc:  # report every failure on the draft so the wizard can show it
            await db.rollback()
            if isinstance(exc, LLMNotConfigured):
                msg = generator.NOT_CONFIGURED
            elif isinstance(exc, (generator.GenerationError, ValueError)):
                msg = str(exc)
            else:
                log.warning("agent_generation_failed", error=str(exc))
                msg = "The AI service didn't respond. Please try again in a moment."
            draft = await db.get(AgentDraft, draft_id)
            if draft:
                draft.gen_status, draft.gen_error = "failed", msg
                await db.commit()


def _agent_from_result(org_id, draft: AgentDraft, data: dict, ctx: dict, result: dict, knowledge: str) -> Agent:
    from app.agent.composer import SECTIONS_V2

    spec, composed, report = result["spec"], result["composed"], result["report"]
    strategy, flags, brief = spec["strategy"], ctx["flags"], ctx["brief"]
    business_name = ctx["business"]["name"]
    presets = brief["presets"]
    use_case_keys = [u["key"] for u in presets] + ([catalog.CUSTOM_KEY] if brief["custom_mode"] else [])
    if len(presets) == 1 and not brief["custom_mode"]:
        label = presets[0]["label"]
    elif presets:
        label = presets[0]["label"] + (f" + {len(presets) - 1} more" if len(presets) > 1 else " (customized)")
    else:
        label = strategy["title"]
    fields = [{"name": f["name"], "description": f["description"] + (f" One of: {', '.join(f['values'])}." if f["values"] else "")}
              for f in strategy["outcomes"]["extraction_fields"]]
    std = [f for f in generator.STANDARD_FIELDS if f["name"] not in {x["name"] for x in fields}]
    behavior = data.get("behavior") or {}
    model = behavior.get("llm_model") if isinstance(behavior.get("llm_model"), str) and behavior.get("llm_model") else generator.GEN_MODEL
    obj = strategy["objectives"]
    plan = {
        "title": strategy["title"],
        "primary_objective": obj["primary"],
        "target_audience": strategy["audience"],
        "qualification_questions": [q["ask"] for q in strategy["qualification"]["questions"]],
        "desired_outcomes": obj["success_criteria"],
        "transfer_rules": flags["transfer_when"] if flags["transfer"] else "",
        "booking_rules": "Books with the connected calendar." if flags["booking"] else "",
        "follow_up_logic": strategy["outcomes"]["callback_rules"],
        "use_cases": use_case_keys,
        "request": {**brief["custom"], "extra_instructions": brief["extra"]},
        "assistant": [{"question": it["question"], "answer": it["answer"], "delegated": it["delegated"]}
                      for it in brief["assistant"] if it["answer"] or it["delegated"]],
        "recommended_settings": flags["recommended"],
    }
    return Agent(
        id=uuid.uuid4(),
        org_id=org_id,
        template="ai_builder",
        name=f"{strategy['agent_name']} – {label}"[:255],
        description=f"{label} for {business_name}"[:500],
        system_prompt=composed["system_prompt"],
        first_message=composed["first_message"],
        knowledge_base=knowledge,
        extraction_fields=std + fields,
        success_criteria=" ".join(obj["success_criteria"])[:2000],
        enable_booking=flags["booking"],
        transfer_number=flags["transfer_number"][:50],
        voice_id=flags["voice_id"] or DEFAULT_VOICE_ID,
        language=flags["language"][:16],
        llm_model=model[:64],
        temperature=0.5,
        ai_disclosure=flags["ai_disclosure"],
        builder={
            "schema": "v2",
            "section_order": [list(x) for x in SECTIONS_V2],
            "industry": ctx["business"]["industry"],
            "use_case": brief["primary"]["key"],
            "use_cases": use_case_keys,
            "direction": ctx["direction"],
            "style": flags["style"] or "friendly",
            "draft_id": str(draft.id),
            "business_name": business_name,
            "persona": strategy["agent_name"],
            "transfer_enabled": flags["transfer"],
            "transfer_requested": generator.transfer_requested(data) and not flags["transfer"],
            "transfer_when": flags["transfer_when"],
            "booking_requested": flags["booking_requested"] and not flags["booking"],
            "callback": flags["callback"],
            "representation": flags["representation"],
            "integrations": list(((data.get("integrations") or {}).get("selected")) or []),
            "sections": composed["sections"],
            "plan": plan,
            "spec": spec,
            "quality": {"words": report["words"], "repairs": report.get("repairs", 0),
                        "checks": [{k: c[k] for k in ("key", "label", "status", "detail")} for c in report["checks"]]},
            "generation": {"model": generator.GEN_MODEL, "references": [r["name"] for r in ctx["references"]],
                           "patterns": [f"{p['slug']}@v{p['version']}" for p in ctx["playbooks"]]},
        },
    )


# ── Customer reference material (organization-scoped) ────────────────────────


class ReferenceCreate(BaseModel):
    name: str = Field(default="", max_length=255)
    # A file, base64-encoded (PDF, DOCX or TXT) …
    filename: str | None = Field(default=None, max_length=255)
    content_base64: str | None = Field(default=None, max_length=7_500_000)
    # … or pasted text.
    text: str | None = Field(default=None, max_length=60000)


def reference_to_dict(r) -> dict:
    return {"id": str(r.id), "name": r.name, "kind": r.kind, "chars": len(r.text or ""),
            "preview": (r.text or "")[:280], "created_at": r.created_at.isoformat() if r.created_at else None}


@router.get("/drafts/{draft_id}/references")
async def list_references(draft_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    from app.models.playbook import ReferenceDocument

    draft = await _get_draft(db, ctx, draft_id)
    rows = (await db.execute(select(ReferenceDocument).where(
        ReferenceDocument.org_id == ctx.org.id, ReferenceDocument.draft_id == draft.id)
        .order_by(ReferenceDocument.created_at))).scalars().all()
    return {"references": [reference_to_dict(r) for r in rows]}


@router.post("/drafts/{draft_id}/references", status_code=201)
async def add_reference(draft_id: uuid.UUID, body: ReferenceCreate, ctx: CtxDep, db: DbDep):
    from sqlalchemy import func

    from app.models.playbook import ReferenceDocument
    from app.services import references

    draft = await _get_draft(db, ctx, draft_id)
    count = (await db.execute(select(func.count()).select_from(ReferenceDocument).where(
        ReferenceDocument.org_id == ctx.org.id, ReferenceDocument.draft_id == draft.id))).scalar_one()
    if count >= 5:
        raise HTTPException(status_code=400, detail="You can add up to 5 references per agent.")
    try:
        if body.content_base64:
            kind, text = references.extract(body.filename or "", body.content_base64)
            name = body.name.strip() or (body.filename or "Uploaded file")
        else:
            kind, text = "paste", references.clean_pasted(body.text or "")
            name = body.name.strip() or "Pasted script"
    except references.ReferenceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    doc = ReferenceDocument(org_id=ctx.org.id, draft_id=draft.id, name=name[:255], kind=kind, text=text,
                            created_by=ctx.user.id)
    db.add(doc)
    await db.commit()
    return reference_to_dict(doc)


@router.delete("/references/{reference_id}", status_code=204)
async def delete_reference(reference_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    from app.models.playbook import ReferenceDocument

    doc = await db.get(ReferenceDocument, reference_id)
    if not doc or doc.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Reference not found")
    await db.delete(doc)
    await db.commit()


# ── Editor helpers ────────────────────────────────────────────────────────────


@router.post("/agents/{agent_id}/improve")
async def improve(agent_id: uuid.UUID, body: ImproveRequest, ctx: CtxDep, db: DbDep):
    agent = await _get_agent(db, ctx, agent_id)
    if not body.instruction.strip():
        raise HTTPException(status_code=400, detail="Tell the AI what you'd like to change.")
    knowledge = await generator.knowledge_for(db, ctx.org.id)
    return await _run_llm(generator.improve_agent(agent, body.instruction, knowledge))


@router.post("/agents/{agent_id}/regenerate")
async def regenerate(agent_id: uuid.UUID, body: RegenerateRequest, ctx: CtxDep, db: DbDep):
    agent = await _get_agent(db, ctx, agent_id)
    keys = [k for k, _ in generator.section_order(agent)]
    if body.section not in keys:
        raise HTTPException(status_code=400, detail="That isn't a section of the agent's instructions.")
    knowledge = await generator.knowledge_for(db, ctx.org.id)
    if (agent.builder or {}).get("schema") == "v2":
        extra = await _regen_context(db, ctx, agent)
        text = await _run_llm(pipeline.regenerate_section(agent, body.section, body.instruction, knowledge, extra))
        return {"section": body.section, "text": text}
    return await _run_llm(generator.regenerate_section(agent, body.section, body.instruction, knowledge))


async def _regen_context(db, ctx: Context, agent: Agent) -> dict:
    """Real tools/fields and leak terms for rewriting one section of a v2 agent."""
    import json

    from app.agent import spec as S
    from app.services import playbooks

    tools = [S.TOOL_END_CALL] + ([S.TOOL_CHECK, S.TOOL_BOOK] if agent.enable_booking else []) + \
        ([S.TOOL_TRANSFER] if agent.transfer_number else [])
    b = agent.builder or {}
    customer_text = "\n".join([agent.knowledge_base or "", json.dumps(b.get("plan") or {}, ensure_ascii=False),
                               b.get("business_name") or "", b.get("persona") or "", agent.system_prompt or ""])
    return {"tools": tools, "variables": list(S.BASE_VARIABLES) + await pipeline._custom_field_keys(db, ctx.org.id),
            "private_terms": await playbooks.private_terms(db), "customer_text": customer_text}


@router.get("/agents/{agent_id}/readiness")
async def get_readiness(agent_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    agent = await _get_agent(db, ctx, agent_id)
    return generator.readiness(agent, ctx.org)
