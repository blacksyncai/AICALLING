"""
Agents router — create/configure voice agents and test them
(text playground, browser voice call, phone call).
"""

from __future__ import annotations

import uuid
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from app.agent.models import RUNTIME_DEFAULT_MODEL
from app.agent.runtime import agent_to_runtime
from app.agent.templates import TEMPLATES, get_template
from app.agent.voices import DEFAULT_VOICE_ID
from app.models.agent import Agent
from app.models.call_log import CallLog
from app.services.accounts import InsufficientCredits
from app.services.auth import Context, CtxDep, DbDep
from app.services.entitlements import PlanLimit

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/agents", tags=["agents"])

_EDITABLE = (
    "name", "description", "status", "system_prompt", "first_message", "knowledge_base",
    "language", "llm_model", "temperature", "voice_id", "voice_speed", "voice_tuning", "background_audio",
    "enable_booking", "calcom_event_type_id", "calendar_timezone", "transfer_number", "max_duration_seconds",
    "voicemail_action", "voicemail_message",
    "extraction_fields", "success_criteria", "builder", "ai_disclosure", "caller_number", "record_calls",
)


# ── Schemas ───────────────────────────────────────────────────────────────────


class ExtractionField(BaseModel):
    name: str
    description: str = ""


class Pronunciation(BaseModel):
    word: str = Field(max_length=60)
    say: str = Field(max_length=120)


class VoiceTuning(BaseModel):
    volume: float = Field(default=1.0, ge=0.5, le=2)
    # 0–1. Defaults reproduce the worker's standard turn-taking.
    responsiveness: float = Field(default=0.75, ge=0, le=1)
    interruption: float = Field(default=0.75, ge=0, le=1)
    pronunciations: list[Pronunciation] = Field(default_factory=list, max_length=50)

    @field_validator("pronunciations")
    @classmethod
    def _drop_blank(cls, v: list[Pronunciation]) -> list[Pronunciation]:
        return [p for p in v if p.word.strip() and p.say.strip()]


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
    voice_tuning: VoiceTuning | None = None
    background_audio: bool | None = None
    enable_booking: bool | None = None
    calcom_event_type_id: str | None = Field(default=None, max_length=64)
    # Write-only: "" removes the saved key.
    calcom_api_key: str | None = Field(default=None, max_length=200)
    calendar_timezone: str | None = Field(default=None, max_length=64)
    transfer_number: str | None = None
    voicemail_action: str | None = Field(default=None, pattern="^(hang_up|leave_message|ignore)$")
    voicemail_message: str | None = Field(default=None, max_length=1000)
    max_duration_seconds: int | None = Field(default=None, ge=30, le=3600)
    extraction_fields: list[ExtractionField] | None = None
    success_criteria: str | None = None
    builder: dict | None = None
    ai_disclosure: bool | None = None
    caller_number: str | None = None
    record_calls: bool | None = None
    specialty: str | None = Field(default=None, max_length=60)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = []
    variables: dict = {}
    state: dict = {}


class WebCallRequest(BaseModel):
    variables: dict = {}
    # Browser tests aren't recorded unless the tester ticks "Record this call".
    record: bool = False


class PhoneCallRequest(BaseModel):
    to_phone: str
    name: str = ""
    # One of the account's numbers to call from; empty = the agent's caller ID (or the account default).
    from_number: str = ""


def catalog_specialty(a: Agent) -> str | None:
    from app.agent.catalog import specialty_label

    return specialty_label(a)


def agent_to_dict(a: Agent, stats: dict | None = None) -> dict:
    d = {
        "id": str(a.id),
        "template": a.template,
        **{k: getattr(a, k) for k in _EDITABLE},
        "extraction_fields": a.extraction_fields or [],
        "voice_tuning": a.voice_tuning or {},
        "calendar_timezone": a.calendar_timezone or "",
        "voicemail_action": a.voicemail_action or "hang_up",
        "voicemail_message": a.voicemail_message or "",
        "calcom_key_set": bool(a.calcom_api_key_enc),
        "ai_disclosure": a.ai_disclosure is not False,
        "caller_number": a.caller_number or "",
        "specialty": catalog_specialty(a) or "",
        "specialty_custom": bool(a.specialty_custom),
        "record_calls": a.record_calls is not False,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }
    if stats is not None:
        d["stats"] = stats
    return d


async def _get_agent(db, ctx: Context, agent_id: uuid.UUID) -> Agent:
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != ctx.org.id:
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
        llm_model=t.get("llm_model", RUNTIME_DEFAULT_MODEL),
        voice_id=t.get("voice_id", DEFAULT_VOICE_ID),
        **({"max_duration_seconds": t["max_duration_seconds"]} if t.get("max_duration_seconds") else {}),
    )


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/templates/list")
async def list_templates(_: CtxDep):
    return [{k: t[k] for k in ("template", "name", "description", "enable_booking")} for t in TEMPLATES if not t.get("hidden")]


@router.get("/")
async def list_agents(ctx: CtxDep, db: DbDep):
    agents = (await db.execute(
        select(Agent).where(Agent.org_id == ctx.org.id).order_by(Agent.created_at.desc())
    )).scalars().all()
    rows = await db.execute(
        select(CallLog.agent_id, func.count(), func.coalesce(func.sum(CallLog.duration_seconds), 0))
        .where(CallLog.org_id == ctx.org.id, CallLog.agent_id.isnot(None))
        .group_by(CallLog.agent_id)
    )
    stats = {r[0]: {"calls": r[1], "seconds": int(r[2] or 0)} for r in rows}
    return [agent_to_dict(a, stats.get(a.id, {"calls": 0, "seconds": 0})) for a in agents]


@router.post("/", status_code=201)
async def create_agent(body: AgentCreate, ctx: CtxDep, db: DbDep):
    from app.services import entitlements

    agent = new_agent_from_template(body.template, body.name)
    if (agent.status or "active") == "active" and agent.template not in entitlements.EXEMPT_TEMPLATES:
        await entitlements.check_agent_activation(db, ctx.org)
    agent.org_id = ctx.org.id
    db.add(agent)
    await db.commit()
    log.info("agent_created", agent_id=str(agent.id), template=body.template)
    return agent_to_dict(agent)


@router.get("/{agent_id}")
async def get_agent(agent_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    return agent_to_dict(await _get_agent(db, ctx, agent_id))


def _prompt_state(agent) -> tuple:
    return (agent.system_prompt or "", agent.first_message or "", (agent.builder or {}).get("sections"))


@router.patch("/{agent_id}")
async def update_agent(agent_id: uuid.UUID, body: AgentUpdate, ctx: CtxDep, db: DbDep):
    from app.services.agent_versions import ensure_baseline, snapshot

    agent = await _get_agent(db, ctx, agent_id)
    before = _prompt_state(agent)
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "transfer_number" in changes:
        from app.services.outbound_call import validate_e164
        try:
            changes["transfer_number"] = validate_e164(changes["transfer_number"]) if changes["transfer_number"].strip() else ""
        except ValueError:
            raise HTTPException(status_code=422, detail="Enter a valid transfer phone number, for example +14155550123.") from None
    if {"voice_id", "voice_speed"} & changes.keys():
        from app.agent.elevenlabs_tts import is_elevenlabs_voice, provider_voice_id, voice_settings
        selected_voice = changes.get("voice_id", agent.voice_id)
        if is_elevenlabs_voice(selected_voice):
            try:
                provider_voice_id(selected_voice)
                voice_settings(changes.get("voice_speed", agent.voice_speed or 1.0))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
    if changes.get("status") == "active" and agent.status != "active":
        from app.services import entitlements

        if agent.template not in entitlements.EXEMPT_TEMPLATES:
            await entitlements.check_agent_activation(db, ctx.org, agent.id)
    if {"system_prompt", "first_message", "builder"} & changes.keys():
        await ensure_baseline(db, agent)
    if "builder" in changes and isinstance(agent.builder, dict):
        # Generator-owned metadata can't be dropped or rewritten from the editor.
        for key in ("schema", "spec", "quality", "generation"):
            if key in agent.builder:
                changes["builder"][key] = agent.builder[key]
    if "specialty" in body.model_dump(exclude_unset=True):
        # A person naming the specialty locks it; clearing it goes back to the inferred one.
        # Re-sending the current label (a normal editor save) changes nothing.
        label = (body.specialty or "").strip()[:60]
        if label != (catalog_specialty(agent) or ""):
            agent.specialty, agent.specialty_custom = (label, True) if label else (None, None)
        changes.pop("specialty", None)
    if "calcom_api_key" in changes:
        from app.services import secret_store

        key = changes.pop("calcom_api_key").strip()
        if key:
            try:
                agent.calcom_api_key_enc = secret_store.encrypt_value(key)
            except secret_store.SecretStoreError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        else:
            agent.calcom_api_key_enc = None
    if "calendar_timezone" in changes:
        from app.services.calendar import valid_timezone

        tz = changes["calendar_timezone"].strip()
        if tz and not valid_timezone(tz):
            raise HTTPException(status_code=400, detail="Unknown time zone. Use a name like America/New_York.")
        changes["calendar_timezone"] = tz or None
    if "calcom_event_type_id" in changes:
        changes["calcom_event_type_id"] = changes["calcom_event_type_id"].strip()
    if "caller_number" in changes:
        from app.services import telephony

        if changes["caller_number"]:
            owned = {n.number for n in await telephony.active_numbers(db, ctx.org.id)}
            if changes["caller_number"] not in owned:
                raise HTTPException(status_code=400, detail="That number isn't on this account.")
        else:
            changes["caller_number"] = None
    for key, value in changes.items():
        setattr(agent, key, value)
    if _prompt_state(agent) != before:
        await snapshot(db, agent, "edited", ctx.user.id)
    await db.commit()
    await db.refresh(agent)
    return agent_to_dict(agent)


@router.get("/{agent_id}/versions")
async def list_versions(agent_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    from app.models.playbook import AgentVersion
    from app.services.agent_versions import version_to_dict

    agent = await _get_agent(db, ctx, agent_id)
    rows = (await db.execute(select(AgentVersion).where(AgentVersion.agent_id == agent.id, AgentVersion.org_id == ctx.org.id)
                             .order_by(AgentVersion.version.desc()))).scalars().all()
    return {"versions": [version_to_dict(v) for v in rows]}


async def _get_version(db, ctx: Context, agent_id: uuid.UUID, version_id: uuid.UUID):
    from app.models.playbook import AgentVersion

    agent = await _get_agent(db, ctx, agent_id)
    v = await db.get(AgentVersion, version_id)
    if not v or v.agent_id != agent.id or v.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Version not found")
    return agent, v


@router.get("/{agent_id}/versions/{version_id}")
async def get_version(agent_id: uuid.UUID, version_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    from app.services.agent_versions import version_to_dict

    _, v = await _get_version(db, ctx, agent_id, version_id)
    return version_to_dict(v, full=True)


@router.post("/{agent_id}/versions/{version_id}/restore")
async def restore_version(agent_id: uuid.UUID, version_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    from app.services.agent_versions import snapshot

    agent, v = await _get_version(db, ctx, agent_id, version_id)
    agent.system_prompt = v.system_prompt
    agent.first_message = v.first_message
    if v.sections is not None:
        agent.builder = {**(agent.builder or {}), "sections": dict(v.sections)}
    await snapshot(db, agent, "restored", ctx.user.id, note=f"Restored version {v.version}")
    await db.commit()
    await db.refresh(agent)
    return agent_to_dict(agent)


@router.post("/{agent_id}/duplicate", status_code=201)
async def duplicate_agent(agent_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    from app.services import entitlements

    src = await _get_agent(db, ctx, agent_id)
    if (src.status or "active") == "active":
        await entitlements.check_agent_activation(db, ctx.org)
    copy = Agent(id=uuid.uuid4(), org_id=ctx.org.id, template=src.template,
                 **{k: getattr(src, k) for k in _EDITABLE}, calcom_api_key_enc=src.calcom_api_key_enc)
    copy.name = f"{src.name} (copy)"
    db.add(copy)
    await db.commit()
    return agent_to_dict(copy)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    agent = await _get_agent(db, ctx, agent_id)
    await db.delete(agent)
    await db.commit()


@router.post("/{agent_id}/chat")
async def chat_with_agent(agent_id: uuid.UUID, body: ChatRequest, ctx: CtxDep, db: DbDep):
    """Text playground — same prompt, knowledge and tools as the voice agent."""
    from app.services.llm import LLMNotConfigured, playground_reply

    agent = await _get_agent(db, ctx, agent_id)
    try:
        return await playground_reply(
            agent_to_runtime(agent, secrets=True),
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
async def start_web_call(agent_id: uuid.UUID, body: WebCallRequest, ctx: CtxDep, db: DbDep):
    """Browser voice test — returns a LiveKit URL + token for livekit-client."""
    from app.services.outbound_call import CallSetupError, call_service

    from app.services.billing.credits import ensure_can_test

    agent = await _get_agent(db, ctx, agent_id)
    try:
        await ensure_can_test(db, ctx.org)
        return await call_service.start_web_call(agent, db, body.variables, record=body.record)
    except InsufficientCredits as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    except CallSetupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("web_call_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Could not start web call: {exc}")


@router.post("/{agent_id}/phone-call")
async def start_phone_call(agent_id: uuid.UUID, body: PhoneCallRequest, ctx: CtxDep, db: DbDep):
    """Have the agent call a phone number right now (e.g. your own mobile)."""
    from app.services.outbound_call import CallSetupError, call_service

    agent = await _get_agent(db, ctx, agent_id)
    try:
        call = await call_service.dispatch_call(None, db, agent=agent, to_phone=body.to_phone,
                                                from_number=body.from_number.strip() or None)
    except PlanLimit as exc:
        raise exc.http()
    except InsufficientCredits as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    except (CallSetupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("phone_call_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Could not place call: {exc}")
    return {"call_id": str(call.id), "room": call.livekit_room_name, "status": call.status}
