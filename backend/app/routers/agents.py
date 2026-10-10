"""
Agents router — create/configure voice agents and test them
(text playground, browser voice call, phone call).
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runtime import agent_to_runtime
from app.agent.templates import TEMPLATES, get_template
from app.agent.voices import DEFAULT_VOICE_ID
from app.database import get_db
from app.models.agent import Agent
from app.models.call_log import CallLog

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/agents", tags=["agents"])

_EDITABLE = (
    "name", "description", "status", "system_prompt", "first_message", "knowledge_base",
    "language", "llm_model", "temperature", "voice_id", "voice_speed", "background_audio",
    "enable_booking", "calcom_event_type_id", "transfer_number", "max_duration_seconds",
    "extraction_fields", "success_criteria",
)


# ── Schemas ───────────────────────────────────────────────────────────────────


class ExtractionField(BaseModel):
    name: str
    description: str = ""


class AgentCreate(BaseModel):
    template: str = "blank"
    name: str | None = None


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    system_prompt: str | None = None
    first_message: str | None = None
    knowledge_base: str | None = None
    language: str | None = None
    llm_model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    voice_id: str | None = None
    voice_speed: float | None = Field(default=None, ge=0.5, le=2)
    background_audio: bool | None = None
    enable_booking: bool | None = None
    calcom_event_type_id: str | None = None
    transfer_number: str | None = None
    max_duration_seconds: int | None = Field(default=None, ge=30, le=3600)
    extraction_fields: list[ExtractionField] | None = None
    success_criteria: str | None = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = []
    variables: dict = {}
    state: dict = {}


class WebCallRequest(BaseModel):
    variables: dict = {}


class PhoneCallRequest(BaseModel):
    to_phone: str
    name: str = ""


def agent_to_dict(a: Agent, stats: dict | None = None) -> dict:
    d = {
        "id": str(a.id),
        "template": a.template,
        **{k: getattr(a, k) for k in _EDITABLE},
        "extraction_fields": a.extraction_fields or [],
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }
    if stats is not None:
        d["stats"] = stats
    return d


async def _get_agent(db: AsyncSession, agent_id: uuid.UUID) -> Agent:
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def new_agent_from_template(key: str, name: str | None = None) -> Agent:
    t = get_template(key)
    return Agent(
        id=uuid.uuid4(),
        template=t["template"],
        name=name or t["name"],
        description=t["description"],
        system_prompt=t["system_prompt"],
        first_message=t["first_message"],
        knowledge_base=t["knowledge_base"],
        extraction_fields=t["extraction_fields"],
        success_criteria=t["success_criteria"],
        enable_booking=t["enable_booking"],
        llm_model=t.get("llm_model", "gpt-4.1-mini"),
        voice_id=DEFAULT_VOICE_ID,
    )


async def seed_default_agent(db: AsyncSession) -> None:
    """First boot: create one ready-to-test agent so the dashboard isn't empty."""
    count = (await db.execute(select(func.count()).select_from(Agent))).scalar_one()
    if count == 0:
        db.add(new_agent_from_template("sales_sdr"))
        await db.commit()
        log.info("seeded_default_agent")


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/templates/list")
async def list_templates():
    return [{k: t[k] for k in ("template", "name", "description", "enable_booking")} for t in TEMPLATES]


@router.get("/")
async def list_agents(db: Annotated[AsyncSession, Depends(get_db)]):
    agents = (await db.execute(select(Agent).order_by(Agent.created_at.desc()))).scalars().all()
    rows = await db.execute(
        select(CallLog.agent_id, func.count(), func.coalesce(func.sum(CallLog.duration_seconds), 0))
        .where(CallLog.agent_id.isnot(None))
        .group_by(CallLog.agent_id)
    )
    stats = {r[0]: {"calls": r[1], "seconds": int(r[2] or 0)} for r in rows}
    return [agent_to_dict(a, stats.get(a.id, {"calls": 0, "seconds": 0})) for a in agents]


@router.post("/", status_code=201)
async def create_agent(body: AgentCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    agent = new_agent_from_template(body.template, body.name)
    db.add(agent)
    await db.commit()
    log.info("agent_created", agent_id=str(agent.id), template=body.template)
    return agent_to_dict(agent)


@router.get("/{agent_id}")
async def get_agent(agent_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    return agent_to_dict(await _get_agent(db, agent_id))


@router.get("/{agent_id}/runtime")
async def get_agent_runtime(agent_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    """Config consumed by the voice worker when it isn't inlined in room metadata."""
    return agent_to_runtime(await _get_agent(db, agent_id))


@router.patch("/{agent_id}")
async def update_agent(agent_id: uuid.UUID, body: AgentUpdate, db: Annotated[AsyncSession, Depends(get_db)]):
    agent = await _get_agent(db, agent_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        setattr(agent, key, value)
    await db.commit()
    await db.refresh(agent)
    return agent_to_dict(agent)


@router.post("/{agent_id}/duplicate", status_code=201)
async def duplicate_agent(agent_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    src = await _get_agent(db, agent_id)
    copy = Agent(id=uuid.uuid4(), template=src.template, **{k: getattr(src, k) for k in _EDITABLE})
    copy.name = f"{src.name} (copy)"
    db.add(copy)
    await db.commit()
    return agent_to_dict(copy)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    agent = await _get_agent(db, agent_id)
    await db.delete(agent)
    await db.commit()


@router.post("/{agent_id}/chat")
async def chat_with_agent(agent_id: uuid.UUID, body: ChatRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    """Text playground — same prompt, knowledge and tools as the voice agent."""
    from app.services.llm import LLMNotConfigured, playground_reply

    agent = await _get_agent(db, agent_id)
    try:
        return await playground_reply(
            agent_to_runtime(agent),
            {"name": "there", **body.variables},
            [m.model_dump() for m in body.messages],
            body.state,
        )
    except LLMNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.warning("playground_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/{agent_id}/web-call")
async def start_web_call(agent_id: uuid.UUID, body: WebCallRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    """Browser voice test — returns a LiveKit URL + token for livekit-client."""
    from app.services.outbound_call import CallSetupError, call_service

    agent = await _get_agent(db, agent_id)
    try:
        return await call_service.start_web_call(agent, db, body.variables)
    except CallSetupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("web_call_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Could not start web call: {exc}")


@router.post("/{agent_id}/phone-call")
async def start_phone_call(agent_id: uuid.UUID, body: PhoneCallRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    """Have the agent call a phone number right now (e.g. your own mobile)."""
    from app.services.outbound_call import CallSetupError, call_service

    agent = await _get_agent(db, agent_id)
    try:
        call = await call_service.dispatch_call(None, db, agent=agent, to_phone=body.to_phone)
    except (CallSetupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("phone_call_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Could not place call: {exc}")
    return {"call_id": str(call.id), "room": call.livekit_room_name, "status": call.status}
