"""
Agent builder — catalog, resumable wizard drafts, AI generation of a real agent,
and editor helpers (improve with AI, regenerate a section, launch readiness).
Contract: docs/agent-builder.md. Everything is scoped to the caller's organization.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent import catalog, generator
from app.agent.voices import DEFAULT_VOICE_ID
from app.models.agent import Agent
from app.models.builder import AgentDraft
from app.services.auth import Context, CtxDep, DbDep

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/agent-builder", tags=["agent_builder"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class DraftCreate(BaseModel):
    data: dict[str, Any] | None = None
    step: int = Field(default=1, ge=1, le=6)


class DraftUpdate(BaseModel):
    data: dict[str, Any] | None = None
    step: int | None = Field(default=None, ge=1, le=6)


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


@router.post("/generate")
async def generate(body: GenerateRequest, ctx: CtxDep, db: DbDep):
    draft = await _get_draft(db, ctx, body.draft_id)
    data = draft.data or {}
    try:
        generator.validate_draft(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    knowledge = await generator.knowledge_for(db, ctx.org.id)
    spec = await _run_llm(generator.generate_agent_spec(data, knowledge))

    flags, use_case, business, brief = spec["flags"], spec["use_case"], spec["business"], spec["brief"]
    business_name = business["name"].strip()
    use_case_keys = [u["key"] for u in spec["use_cases"]] + ([catalog.CUSTOM_KEY] if spec["custom_mode"] else [])
    plan = {
        **spec["plan"],
        "use_cases": use_case_keys,
        "request": {**brief["custom"], "extra_instructions": brief["extra"]},
        "assistant": [{"question": it["question"], "answer": it["answer"], "delegated": it["delegated"]}
                      for it in brief["assistant"] if it["answer"] or it["delegated"]],
        "recommended_settings": flags["recommended"],
    }
    agent = Agent(
        id=uuid.uuid4(),
        org_id=ctx.org.id,
        template="ai_builder",
        name=f"{spec['agent_name']} – {spec['label']}"[:255],
        description=f"{spec['label']} for {business_name}"[:500],
        system_prompt=generator.assemble_prompt(spec["sections"]),
        first_message=spec["first_message"],
        knowledge_base=knowledge,
        extraction_fields=generator.STANDARD_FIELDS + spec["extraction_fields"],
        success_criteria=spec["success_criteria"],
        enable_booking=flags["booking"],
        transfer_number=flags["transfer_number"][:50],
        voice_id=flags["voice_id"] or DEFAULT_VOICE_ID,
        language=flags["language"][:16],
        llm_model=generator.GEN_MODEL,
        temperature=0.5,
        ai_disclosure=flags["ai_disclosure"],
        builder={
            "industry": spec["industry"],
            "use_case": use_case["key"],
            "use_cases": use_case_keys,
            "direction": spec["direction"],
            "style": spec["style"],
            "draft_id": str(draft.id),
            "business_name": business_name,
            "persona": spec["agent_name"],
            "transfer_enabled": flags["transfer"],
            "transfer_requested": generator.transfer_requested(data) and not flags["transfer"],
            "transfer_when": flags["transfer_when"],
            "callback": flags["callback"],
            "integrations": list(((data.get("integrations") or {}).get("selected")) or []),
            "sections": spec["sections"],
            "plan": plan,
        },
    )
    db.add(agent)
    await db.flush()
    draft.agent_id = agent.id
    await db.commit()
    log.info("agent_generated", agent_id=str(agent.id), industry=spec["industry"], use_cases=use_case_keys)
    return {"agent_id": str(agent.id)}


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
    if body.section not in generator.SECTION_KEYS:
        raise HTTPException(status_code=400, detail="That isn't a section of the agent's instructions.")
    knowledge = await generator.knowledge_for(db, ctx.org.id)
    return await _run_llm(generator.regenerate_section(agent, body.section, body.instruction, knowledge))


@router.get("/agents/{agent_id}/readiness")
async def get_readiness(agent_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    agent = await _get_agent(db, ctx, agent_id)
    return generator.readiness(agent, ctx.org)
