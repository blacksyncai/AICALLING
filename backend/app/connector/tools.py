"""
Tools the BlackSync connector exposes to AI assistants.

Every tool acts as the connected user in the account they picked when connecting, through the same functions the
web app uses (so the same checks, limits and plan rules apply). Tools that change something or place calls are
marked with MCP annotations so the assistant asks the user before running them.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import structlog
from fastapi import BackgroundTasks, HTTPException

from app.config import settings
from app.models.account import User
from app.services.auth import Context

log = structlog.get_logger(__name__)


class ToolError(Exception):
    """A problem to show the assistant (and the user) in plain words."""


@dataclass
class Session:
    user: User
    db: Any
    ctx: Context | None  # None until the user has an account

    def need_account(self) -> Context:
        if self.ctx is None:
            raise ToolError("You don't have a BlackSync account yet. Use create_account to set one up first "
                            "(ask for the company name and industry).")
        return self.ctx

    def need_manager(self) -> Context:
        ctx = self.need_account()
        if not ctx.can_manage:
            raise ToolError("Only account owners and admins can do that.")
        return ctx


@dataclass
class Tool:
    name: str
    title: str
    description: str
    schema: dict
    handler: Callable[[Session, dict], Awaitable[dict]]
    read_only: bool = True
    destructive: bool = False
    open_world: bool = False
    idempotent: bool = False

    def descriptor(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.schema,
            "annotations": {"title": self.title, "readOnlyHint": self.read_only, "destructiveHint": self.destructive,
                            "openWorldHint": self.open_world, "idempotentHint": self.idempotent or self.read_only},
            # ChatGPT reads the auth requirement per tool.
            "securitySchemes": [{"type": "oauth2", "scopes": ["blacksync"]}],
            "_meta": {"securitySchemes": [{"type": "oauth2", "scopes": ["blacksync"]}]},
        }


TOOLS: dict[str, Tool] = {}
_background: set[asyncio.Task] = set()


def tool(name: str, title: str, description: str, properties: dict | None = None, required: list[str] | None = None,
         **flags):
    def wrap(fn):
        schema = {"type": "object", "properties": properties or {}, "additionalProperties": False}
        if required:
            schema["required"] = required
        TOOLS[name] = Tool(name, title, description.strip(), schema, fn, **flags)
        return fn
    return wrap


def link(path: str) -> str:
    return f"{(settings.app_url or 'https://blacksync.si').rstrip('/')}{path}"


def _uuid(args: dict, key: str, required: bool = True) -> uuid.UUID | None:
    raw = args.get(key)
    if raw in (None, ""):
        if required:
            raise ToolError(f"{key} is required.")
        return None
    try:
        return uuid.UUID(str(raw).split(":")[-1])
    except ValueError:
        raise ToolError(f"{key} isn't a valid id: {raw}")


def _int(args: dict, key: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(args.get(key, default))))
    except (TypeError, ValueError):
        return default


def _run_later(coro) -> None:
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


async def _schedule(bg: BackgroundTasks) -> None:
    if bg.tasks:
        _run_later(bg())


STR = {"type": "string"}
ID = {"type": "string", "description": "The id (as returned by a list tool)."}
LIMIT = {"type": "integer", "minimum": 1, "maximum": 100, "description": "How many to return (default 20)."}


# ── Getting started ───────────────────────────────────────────────────────────


@tool("get_started", "Account overview and next steps",
      """Start here. Shows who is connected, their BlackSync account (plan, calling credits, agents, phone numbers,
contacts, campaigns, calls) and a setup checklist with the next recommended step. If the user has no account yet,
it says so and you should offer create_account.""")
async def get_started(s: Session, args: dict) -> dict:
    from sqlalchemy import func, select

    from app.models.agent import Agent
    from app.models.billing import PhoneNumber
    from app.models.builder import BusinessProfile
    from app.models.call_log import CallLog
    from app.models.campaign import Campaign
    from app.models.lead import Lead

    who = {"email": s.user.email, "name": " ".join(x for x in (s.user.first_name, s.user.last_name) if x)}
    if s.ctx is None:
        return {"user": who, "has_account": False,
                "next_step": "Create the account with create_account (company name and industry; list_industries "
                             "shows the choices). After that, build the first AI agent with build_agent."}
    org, db = s.ctx.org, s.db

    async def count(model, *where):
        return int((await db.execute(select(func.count()).select_from(model).where(model.org_id == org.id, *where)))
                   .scalar() or 0)

    agents = (await db.execute(select(Agent).where(Agent.org_id == org.id))).scalars().all()
    built = [a for a in agents if a.template != "welcome_demo"]
    numbers = await count(PhoneNumber, PhoneNumber.status == "active")
    contacts = await count(Lead)
    campaigns = await count(Campaign)
    calls = await count(CallLog)
    profile = (await db.execute(select(BusinessProfile).where(BusinessProfile.org_id == org.id))).scalar_one_or_none()
    from app.services.knowledge import counts, normalize_knowledge

    knowledge_items = counts(normalize_knowledge(profile.knowledge))[0] if profile else 0
    try:
        from app.routers.billing import overview as billing_overview

        billing = await billing_overview(s.ctx, db)
        credits = billing["credits"].get("balance")
        plan = (billing.get("plan") or {}).get("name") or (billing.get("plan") or {}).get("key")
    except Exception:
        credits, plan = None, None

    checklist = [
        {"step": "Business details and knowledge", "done": knowledge_items > 0,
         "how": "scan_website (fastest) or add_knowledge", "items": knowledge_items},
        {"step": "Build an AI agent", "done": bool(built), "how": "build_agent", "agents": len(built)},
        {"step": "Test the agent", "done": calls > 0, "how": "call_with_agent to the user's own phone, or the "
                                                              "browser test in the web app"},
        {"step": "Get a phone number", "done": numbers > 0, "how": f"In the web app: {link('/phone-numbers')}"},
        {"step": "Add contacts", "done": contacts > 0, "how": "add_contacts"},
        {"step": "Create and start a campaign", "done": campaigns > 0, "how": "create_campaign then start_campaign"},
    ]
    nxt = next((c for c in checklist if not c["done"]), None)
    return {
        "user": who, "has_account": True,
        "account": {"id": str(org.id), "name": org.name, "industry": org.industry, "role": s.ctx.role,
                    "timezone": org.timezone, "plan": plan, "calling_credits": credits},
        "totals": {"agents": len(built), "phone_numbers": numbers, "contacts": contacts, "campaigns": campaigns,
                   "calls": calls, "knowledge_items": knowledge_items},
        "checklist": checklist,
        "next_step": f"{nxt['step']} ({nxt['how']})" if nxt else "Everything is set up. Review calls with list_calls.",
        "app_url": link("/dashboard"),
    }


@tool("list_industries", "Industries and agent types",
      """Lists the industries BlackSync supports and, for each, the ready-made agent types ("specialties") with their
call direction. Use the keys with create_account (industry) and build_agent (specialty_key).""",
      {"industry": {"type": "string", "description": "Only this industry key (optional)."}})
async def list_industries(s: Session, args: dict) -> dict:
    from app.agent import catalog

    c = catalog.catalog()
    want = (args.get("industry") or "").strip()
    out = []
    for ind in c["industries"]:
        if want and ind["key"] != want:
            continue
        specs = [{"key": sp["key"], "label": sp["label"], "direction": sp.get("direction")}
                 for sp in c.get("specialties", {}).get(ind["key"], [])]
        out.append({"key": ind["key"], "label": ind["label"], "specialties": specs})
    return {"industries": out}


@tool("create_account", "Create a BlackSync account",
      """Creates the user's BlackSync workspace (free trial with welcome calling credits). Only for users who don't
have an account yet. Confirm the company name and industry with the user first.""",
      {"company": {"type": "string", "description": "Business name."},
       "industry": {"type": "string", "description": "Industry key from list_industries."},
       "goals": {"type": "array", "items": STR, "description": "Specialty keys they're interested in (optional)."},
       "website": {"type": "string", "description": "Business website (optional)."},
       "timezone": {"type": "string", "description": "IANA time zone, e.g. America/New_York (optional)."},
       "team_size": {"type": "string", "enum": ["just_me", "2_5", "6_20", "21_plus"]}},
      ["company", "industry"], read_only=False)
async def create_account(s: Session, args: dict) -> dict:
    from app.routers.onboarding import StartBody, start

    if s.ctx is not None:
        raise ToolError(f"This login already has an account ({s.ctx.org.name}).")
    try:
        body = StartBody(company=args.get("company", ""), industry=args.get("industry", ""),
                         goals=args.get("goals") or [], website=args.get("website") or "",
                         timezone=args.get("timezone") or "", team_size=args.get("team_size"))
    except ValueError as exc:
        raise ToolError(f"Check the details: {exc}")
    await start(body, s.user, s.db)
    return {"created": True, "company": body.company,
            "next_step": "Add business knowledge (scan_website if they have a site), then build_agent.",
            "app_url": link("/dashboard")}


# ── Business profile and knowledge ────────────────────────────────────────────


def _profile_out(p: dict) -> dict:
    sections = [{"key": sec["key"], "title": sec.get("title"),
                 "items": [{"id": i["id"], "text": i["text"]} for i in sec.get("items", [])]}
                for sec in (p.get("knowledge") or {}).get("sections", [])]
    return {"name": p["name"], "industry": p["industry"], "website": p["website"], "description": p["description"],
            "website_scan": {"status": p["status"], "progress": p.get("progress_label"), "error": p.get("error")},
            "knowledge": sections, "pending_changes": len(p.get("pending_changes") or []),
            "edit_url": link("/knowledge")}


@tool("get_business_profile", "Business profile and knowledge",
      """The business details and the knowledge base every agent uses on calls (overview, services, locations,
team, hours, pricing, FAQs, and the owner's custom instructions), plus the website scan status.""")
async def get_business_profile(s: Session, args: dict) -> dict:
    from app.routers.business_profile import get_business_profile as get_p

    return _profile_out(await get_p(s.need_account(), s.db))


@tool("update_business_profile", "Update business details",
      "Updates the business name, website or description.",
      {"name": STR, "website": STR, "description": {"type": "string", "description": "A few sentences about the business."}},
      read_only=False, idempotent=True)
async def update_business_profile(s: Session, args: dict) -> dict:
    from app.routers.business_profile import ProfilePatch, update_business_profile as upd

    fields = {k: args[k] for k in ("name", "website", "description") if isinstance(args.get(k), str)}
    if not fields:
        raise ToolError("Nothing to change.")
    return _profile_out(await upd(ProfilePatch(**fields), s.need_account(), s.db))


@tool("scan_website", "Learn the business from its website",
      """Reads the business website and fills the knowledge base automatically (takes a minute or two; check
progress with get_business_profile).""",
      {"website": {"type": "string", "description": "Website address (optional if one is saved)."}},
      read_only=False, open_world=True)
async def scan_website(s: Session, args: dict) -> dict:
    from app.routers.business_profile import AnalyzeIn, analyze

    p = await analyze(AnalyzeIn(website=args.get("website") or None), s.need_account(), s.db)
    return {"started": True, **_profile_out(p)}


@tool("add_knowledge", "Add to the knowledge base",
      """Adds facts to one section of the knowledge base, or replaces the section. Sections: overview, services,
locations, team, hours, pricing, faqs, custom (custom = instructions from the owner that every agent follows).
Each item is one short fact or instruction (under 500 characters).""",
      {"section": {"type": "string", "enum": ["overview", "services", "locations", "team", "hours", "pricing", "faqs",
                                               "custom"]},
       "items": {"type": "array", "items": STR, "minItems": 1, "maxItems": 50},
       "replace": {"type": "boolean", "description": "Replace the section's items instead of adding (default false)."}},
      ["section", "items"], read_only=False)
async def add_knowledge(s: Session, args: dict) -> dict:
    from app.routers.business_profile import KnowledgeIn, get_business_profile as get_p, save_knowledge

    ctx = s.need_account()
    current = (await get_p(ctx, s.db))["knowledge"]["sections"]
    key = args.get("section")
    if key not in {sec["key"] for sec in current}:
        raise ToolError("Unknown section.")
    new = [{"text": str(t)[:500]} for t in (args.get("items") or []) if str(t).strip()]
    sections = []
    for sec in current:
        items = [{"id": i["id"], "text": i["text"], "needs_review": i.get("needs_review", False)} for i in sec["items"]]
        if sec["key"] == key:
            items = new if args.get("replace") else items + new
        sections.append({"key": sec["key"], "items": items})
    return _profile_out(await save_knowledge(KnowledgeIn(sections=sections), ctx, s.db))


# ── Agents ────────────────────────────────────────────────────────────────────


def _agent_brief(a: dict) -> dict:
    return {"id": a["id"], "name": a["name"], "status": a.get("status"), "description": a.get("description"),
            "specialty": a.get("specialty"), "voice_id": a.get("voice_id"), "url": link(f"/agents/{a['id']}")}


@tool("list_agents", "List AI agents", "The account's AI calling agents with their status.")
async def list_agents(s: Session, args: dict) -> dict:
    from app.routers.agents import list_agents as la

    out = await la(s.need_account(), s.db)
    agents = out.get("agents", out) if isinstance(out, dict) else out
    return {"agents": [_agent_brief(a) for a in agents]}


@tool("get_agent", "Get an AI agent",
      """Full details of one agent: its call script/instructions, first message, voice, transfer number, voicemail
handling, booking and status.""", {"agent_id": ID}, ["agent_id"])
async def get_agent(s: Session, args: dict) -> dict:
    from app.routers.agents import get_agent as ga

    a = await ga(_uuid(args, "agent_id"), s.need_account(), s.db)
    keep = ("id", "name", "description", "status", "first_message", "system_prompt", "language", "voice_id",
            "voice_speed", "transfer_number", "enable_booking", "voicemail_action", "voicemail_message",
            "max_duration_seconds", "success_criteria", "ai_disclosure", "caller_number", "record_calls", "specialty")
    return {**{k: a.get(k) for k in keep}, "url": link(f"/agents/{a['id']}")}


@tool("list_voices", "List voices", "Voices an agent can use (pass the id to build_agent or update_agent).")
async def list_voices(s: Session, args: dict) -> dict:
    from app.routers.settings import list_voices as lv

    s.need_account()
    out = await lv()
    voices = out.get("voices", []) if isinstance(out, dict) else []
    keep = ("id", "name", "gender", "accent", "language", "description", "category")
    return {"voices": [{k: v.get(k) for k in keep if v.get(k) is not None} for v in voices[:60]]}


@tool("build_agent", "Build an AI agent",
      """Builds a complete AI calling agent from the user's description, the same way "Build with AI" does in the
web app: it writes the call script, opening, questions, objection handling and closing. Runs in the background
(about a minute): poll get_agent_build_status with the returned build_id. Before calling, make sure you know what
the agent should do (the mission), whether it makes or answers calls, and ideally who it talks to.""",
      {"mission": {"type": "string", "description": "What the agent should do on calls, in the user's words."},
       "direction": {"type": "string", "enum": ["outbound", "inbound"], "description": "Makes calls or answers them."},
       "specialty_key": {"type": "string", "description": "A specialty key from list_industries (optional)."},
       "agent_name": {"type": "string", "description": "The name the agent uses on calls (optional)."},
       "voice_id": {"type": "string", "description": "From list_voices (optional; a natural default is used)."},
       "audience": {"type": "string", "description": "Who it speaks with (optional)."},
       "tone": {"type": "string", "description": "How it should come across (optional)."},
       "qualification": {"type": "string", "description": "What makes a good lead (optional)."},
       "questions": {"type": "string", "description": "Questions it must ask (optional)."},
       "objections": {"type": "string", "description": "Objections to expect (optional)."},
       "transfer_number": {"type": "string", "description": "Number to transfer interested callers to (optional)."},
       "additional_instructions": {"type": "string", "description": "Anything else it must do or avoid (optional)."}},
      ["mission", "direction"], read_only=False)
async def build_agent(s: Session, args: dict) -> dict:
    from app.agent import catalog
    from app.routers.agent_builder import DraftCreate, GenerateRequest, create_draft, generate
    from app.routers.business_profile import get_business_profile as get_p

    ctx = s.need_account()
    mission = (args.get("mission") or "").strip()
    if len(mission) < 15:
        raise ToolError("Describe what the agent should do in a sentence or two.")
    profile = await get_p(ctx, s.db)
    industry = profile.get("industry") or ctx.org.industry or "other"
    if not catalog.industry_label(industry):
        industry = "other"
    specs = {sp["key"]: sp for sp in catalog.specialties_for(industry)}
    sp = specs.get(args.get("specialty_key") or "")
    specialty = ({"key": sp["key"], "use_cases": sp.get("use_cases", []), "label": sp["label"]} if sp
                 else {"key": "something_else", "use_cases": [], "description": mission[:300]})
    advanced = {k: str(args[k])[:300] for k in ("audience", "tone", "qualification", "questions", "objections")
                if args.get(k)}
    behavior: dict = {"decide_later": True}
    if args.get("agent_name"):
        behavior["agent_name"] = str(args["agent_name"])[:40]
    if args.get("voice_id"):
        behavior["voice_id"] = str(args["voice_id"])[:120]
    if args.get("transfer_number"):
        behavior.update(decide_later=False, transfer_number=str(args["transfer_number"])[:32])
    data = {
        "business": {"name": profile.get("name") or ctx.org.name, "industry": industry,
                     "website": profile.get("website") or "", "description": profile.get("description") or ""},
        "goal": {"specialty": specialty, "direction": args.get("direction") or "outbound", "direction_set": True,
                 "mission": mission[:1500], "mission_source": "user", "advanced": advanced,
                 "additional": str(args.get("additional_instructions") or "")[:2000]},
        "behavior": behavior,
        "source": "assistant",
    }
    draft = await create_draft(DraftCreate(data=data, step=1), ctx, s.db)
    bg = BackgroundTasks()
    status = await generate(GenerateRequest(draft_id=uuid.UUID(draft["id"])), bg, ctx, s.db)
    await _schedule(bg)
    return {"build_id": draft["id"], "status": status["status"], "stage": status.get("stage"),
            "next_step": "Call get_agent_build_status with this build_id in about 30 seconds."}


@tool("get_agent_build_status", "Agent build progress",
      "Progress of an agent started with build_agent. When done, returns the new agent's id.",
      {"build_id": ID}, ["build_id"])
async def get_agent_build_status(s: Session, args: dict) -> dict:
    from app.routers.agent_builder import generation_status

    g = await generation_status(_uuid(args, "build_id"), s.need_account(), s.db)
    labels = dict((x["key"], x["label"]) for x in g.get("stages", []))
    out = {"status": g["status"], "stage": labels.get(g.get("stage"), g.get("stage")), "error": g.get("error"),
           "agent_id": g.get("agent_id")}
    if g.get("agent_id"):
        out.update(url=link(f"/agents/{g['agent_id']}"),
                   next_step="Show the user the agent (get_agent), offer a test call (call_with_agent) and "
                             "launch_agent when they're happy.")
    return out


@tool("update_agent", "Edit an AI agent",
      """Changes an agent's settings. Only pass what should change. system_prompt replaces the whole call script, so
read it with get_agent first and keep everything that isn't meant to change.""",
      {"agent_id": ID, "name": STR, "first_message": {"type": "string", "description": "What it says first."},
       "system_prompt": {"type": "string", "description": "The full call script/instructions."},
       "voice_id": STR, "transfer_number": {"type": "string", "description": "\"\" removes it."},
       "voicemail_action": {"type": "string", "enum": ["hang_up", "leave_message", "ignore"]},
       "voicemail_message": STR,
       "max_duration_seconds": {"type": "integer", "minimum": 30, "maximum": 3600}},
      ["agent_id"], read_only=False, idempotent=True)
async def update_agent(s: Session, args: dict) -> dict:
    from app.routers.agents import AgentUpdate, update_agent as ua

    fields = {k: v for k, v in args.items() if k != "agent_id" and v is not None}
    if not fields:
        raise ToolError("Nothing to change.")
    try:
        body = AgentUpdate(**fields)
    except ValueError as exc:
        raise ToolError(f"Check the values: {exc}")
    a = await ua(_uuid(args, "agent_id"), body, s.need_account(), s.db)
    return {"updated": sorted(fields), **_agent_brief(a)}


@tool("launch_agent", "Turn an agent on",
      "Checks the agent is ready and makes it active so campaigns and inbound numbers can use it.",
      {"agent_id": ID}, ["agent_id"], read_only=False, idempotent=True)
async def launch_agent(s: Session, args: dict) -> dict:
    from app.routers.agent_builder import launch

    out = await launch(_uuid(args, "agent_id"), s.need_account(), s.db)
    warnings = [c["label"] for c in out["readiness"]["checks"] if c["status"] == "warning"]
    return {"status": out["status"], "warnings": warnings}


@tool("call_with_agent", "Have an agent call a number",
      """Places a real phone call right now: the agent calls the given number (for example the user's own phone to
test it). Uses calling credits. Always confirm the number with the user first.""",
      {"agent_id": ID, "to_phone": {"type": "string", "description": "Number to call, e.g. +14155550123."},
       "from_number": {"type": "string", "description": "One of the account's numbers to call from (optional)."}},
      ["agent_id", "to_phone"], read_only=False, destructive=True, open_world=True)
async def call_with_agent(s: Session, args: dict) -> dict:
    from app.routers.agents import PhoneCallRequest, start_phone_call

    out = await start_phone_call(_uuid(args, "agent_id"), PhoneCallRequest(
        to_phone=str(args.get("to_phone") or ""), from_number=str(args.get("from_number") or "")),
        s.need_account(), s.db)
    return {"call_id": out["call_id"], "status": out["status"],
            "next_step": "When the call ends, get_call shows the transcript and outcome."}


# ── Calls and results ─────────────────────────────────────────────────────────


def _call_brief(c: dict) -> dict:
    keep = ("id", "call_type", "status", "outcome", "sentiment", "summary", "duration_seconds", "to_phone",
            "contact_name", "contact_company", "agent_name", "campaign_name", "agreed_meeting_time", "started_at")
    return {**{k: c.get(k) for k in keep}, "url": link(f"/calls?call={c['id']}")}


@tool("list_calls", "List calls",
      "Recent calls with outcome and summary, newest first. Filter by agent, campaign, outcome or day.",
      {"agent_id": ID, "campaign_id": ID, "outcome": {"type": "string", "description": "e.g. meeting_booked, "
                                                                                      "interested, not_interested"},
       "date": {"type": "string", "description": "A day, YYYY-MM-DD (account time zone)."},
       "sort": {"type": "string", "enum": ["newest", "longest", "shortest"]}, "limit": LIMIT})
async def list_calls(s: Session, args: dict) -> dict:
    from datetime import date

    from app.routers.calls import list_calls as lc

    day = None
    if args.get("date"):
        try:
            day = date.fromisoformat(str(args["date"]))
        except ValueError:
            raise ToolError("date must be YYYY-MM-DD.")
    out = await lc(s.need_account(), s.db, agent_id=_uuid(args, "agent_id", False),
                   campaign_id=_uuid(args, "campaign_id", False), outcome=args.get("outcome") or None, call_type=None,
                   day=day, page=1, page_size=_int(args, "limit", 20, 1, 100), sort=args.get("sort") or "newest")
    return {"total": out.get("total"), "calls": [_call_brief(c) for c in out.get("items", [])]}


@tool("get_call", "Get a call", "One call in full: transcript, summary, outcome and details collected.",
      {"call_id": ID}, ["call_id"])
async def get_call(s: Session, args: dict) -> dict:
    from app.routers.calls import get_call as gc

    c = await gc(_uuid(args, "call_id"), s.need_account(), s.db)
    transcript = [{"role": t.get("role"), "text": t.get("text") or t.get("content")}
                  for t in (c.get("transcript") or []) if isinstance(t, dict)]
    return {**_call_brief(c), "extracted": c.get("extracted_data") or c.get("extracted"),
            "transcript": transcript[:400]}


@tool("get_analytics", "Calling results",
      "Totals for the last N days: calls, connects, outcomes, meetings booked, minutes and credits.",
      {"days": {"type": "integer", "minimum": 1, "maximum": 365, "description": "Default 30."}})
async def get_analytics(s: Session, args: dict) -> dict:
    from app.routers.calls import overview

    days = _int(args, "days", 30, 1, 365)
    out = await overview(s.need_account(), s.db, days=days)
    out.pop("calls_per_day", None)  # the daily series is for charts; the totals answer questions
    return {"days": days, **out}


# ── Contacts and campaigns ────────────────────────────────────────────────────


def _contact_brief(c: dict) -> dict:
    keep = ("id", "name", "phone", "email", "company", "role", "status", "tags", "dnc", "last_called_at")
    return {k: c.get(k) for k in keep if k in c}


@tool("list_contacts", "List contacts", "Search the account's contacts by name, phone, email or company.",
      {"query": STR, "campaign_id": ID, "limit": LIMIT})
async def list_contacts(s: Session, args: dict) -> dict:
    from app.routers.contacts import list_contacts as lc

    out = await lc(s.need_account(), s.db, q=str(args.get("query") or ""), status=None,
                   campaign_id=_uuid(args, "campaign_id", False), tag=None, dnc=None, page=1,
                   page_size=_int(args, "limit", 20, 1, 100))
    return {"total": out.get("total"), "contacts": [_contact_brief(c) for c in out.get("items", [])]}


@tool("add_contacts", "Add contacts",
      """Adds people to the account's contacts (up to 200 at a time), optionally straight into a campaign.
Each needs a phone number.""",
      {"contacts": {"type": "array", "minItems": 1, "maxItems": 200, "items": {
          "type": "object", "required": ["phone"], "additionalProperties": False,
          "properties": {"name": STR, "phone": STR, "email": STR, "company": STR, "role": STR, "notes": STR,
                         "tags": {"type": "array", "items": STR}}}},
       "campaign_id": ID},
      ["contacts"], read_only=False)
async def add_contacts(s: Session, args: dict) -> dict:
    from app.routers.contacts import ContactIn, create_contact

    ctx = s.need_account()
    campaign_id = _uuid(args, "campaign_id", False)
    added, failed = [], []
    for raw in (args.get("contacts") or [])[:200]:
        if not isinstance(raw, dict):
            continue
        try:
            c = await create_contact(ContactIn(**{k: v for k, v in raw.items() if k in ContactIn.model_fields},
                                               campaign_id=campaign_id), ctx, s.db)
            added.append(c.get("id"))
        except HTTPException as exc:
            await s.db.rollback()
            failed.append({"phone": raw.get("phone"), "reason": exc.detail})
        except ValueError as exc:
            failed.append({"phone": raw.get("phone"), "reason": str(exc)[:200]})
    return {"added": len(added), "failed": failed}


def _campaign_brief(c: dict) -> dict:
    keep = ("id", "name", "status", "direction", "agent_id", "agent_name", "total_leads", "called", "stats",
            "call_window_start", "call_window_end", "call_days", "timezone", "max_concurrent_calls")
    return {**{k: c.get(k) for k in keep if k in c}, "url": link(f"/campaigns/{c['id']}")}


@tool("list_campaigns", "List campaigns", "The account's calling campaigns with progress.", {"limit": LIMIT})
async def list_campaigns(s: Session, args: dict) -> dict:
    from app.routers.campaigns import list_campaigns as lc

    out = await lc(s.need_account(), s.db, page=1, page_size=_int(args, "limit", 20, 1, 100))
    return {"campaigns": [_campaign_brief(c) for c in out["campaigns"]]}


@tool("get_campaign", "Get a campaign", "One campaign: agent, calling hours, retries, progress and results.",
      {"campaign_id": ID}, ["campaign_id"])
async def get_campaign(s: Session, args: dict) -> dict:
    from app.routers.campaigns import get_campaign as gc

    c = await gc(_uuid(args, "campaign_id"), s.need_account(), s.db)
    return {**c, "url": link(f"/campaigns/{c['id']}")}


@tool("create_campaign", "Create a campaign",
      """Creates a campaign (not started). Outbound campaigns call the contacts added to them; inbound campaigns
answer one of the account's phone numbers. Calling hours are local times in the campaign's time zone.""",
      {"name": STR, "agent_id": ID, "direction": {"type": "string", "enum": ["outbound", "inbound"]},
       "phone_number_id": {"type": "string", "description": "Required for inbound (from list_phone_numbers)."},
       "description": STR,
       "call_window_start": {"type": "string", "description": "HH:MM, e.g. 09:00."},
       "call_window_end": {"type": "string", "description": "HH:MM, e.g. 17:00."},
       "call_days": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 6},
                     "description": "0=Mon … 6=Sun."},
       "timezone": {"type": "string", "description": "IANA time zone."},
       "max_attempts": {"type": "integer", "minimum": 1, "maximum": 10},
       "max_concurrent_calls": {"type": "integer", "minimum": 1, "maximum": 20}},
      ["name", "agent_id"], read_only=False)
async def create_campaign(s: Session, args: dict) -> dict:
    from app.routers.campaigns import CampaignCreate, create_campaign as cc

    fields = {k: v for k, v in args.items() if v is not None}
    try:
        body = CampaignCreate(**fields)
    except ValueError as exc:
        raise ToolError(f"Check the values: {exc}")
    c = await cc(body, s.need_account(), s.db)
    return {**_campaign_brief(c), "next_step": "Add contacts (add_contacts with this campaign_id), then start_campaign."}


@tool("start_campaign", "Start a campaign",
      """Starts the campaign: the agent begins calling its contacts during calling hours (outbound) or answering
its number (inbound). Uses calling credits. Confirm with the user first.""",
      {"campaign_id": ID}, ["campaign_id"], read_only=False, destructive=True, open_world=True)
async def start_campaign(s: Session, args: dict) -> dict:
    from app.routers.campaigns import start_campaign as sc

    bg = BackgroundTasks()
    out = await sc(_uuid(args, "campaign_id"), bg, s.need_account(), s.db)
    await _schedule(bg)
    return {"message": out.get("message"), **_campaign_brief(out["campaign"])}


@tool("pause_campaign", "Pause a campaign", "Stops new calls for a campaign until it's started again.",
      {"campaign_id": ID}, ["campaign_id"], read_only=False, idempotent=True)
async def pause_campaign(s: Session, args: dict) -> dict:
    from app.routers.campaigns import pause_campaign as pc

    out = await pc(_uuid(args, "campaign_id"), s.need_account(), s.db)
    camp = out.get("campaign", out) if isinstance(out, dict) else out
    return {"paused": True, **(_campaign_brief(camp) if isinstance(camp, dict) and camp.get("id") else {})}


# ── Numbers and billing ───────────────────────────────────────────────────────


@tool("list_phone_numbers", "List phone numbers", "The account's phone numbers and which agent answers each.")
async def list_phone_numbers(s: Session, args: dict) -> dict:
    from app.routers.phone_numbers import my_numbers

    out = await my_numbers(s.need_account(), s.db)
    return {"numbers": out.get("numbers", []), "pending_requests": out.get("requests", []),
            "can_buy_in_app": out.get("self_serve"), "manage_url": link("/phone-numbers")}


@tool("get_billing", "Plan and credits", "The account's plan, calling-credit balance and recent usage.")
async def get_billing(s: Session, args: dict) -> dict:
    from app.routers.billing import overview

    out = await overview(s.need_account(), s.db)
    return {"plan": out.get("plan"), "credits": out.get("credits"), "auto_recharge": out.get("auto_recharge"),
            "manage_url": link("/billing")}


# ── search / fetch (the standard pair some assistants use for lookups) ────────


@tool("search", "Search BlackSync",
      """Searches the account's agents, campaigns, contacts and recent calls. Returns ids that fetch can open.""",
      {"query": {"type": "string", "description": "Words to look for."}}, ["query"])
async def search(s: Session, args: dict) -> dict:
    from sqlalchemy import or_, select

    from app.models.agent import Agent
    from app.models.call_log import CallLog
    from app.models.campaign import Campaign
    from app.models.lead import Lead

    ctx = s.need_account()
    q = str(args.get("query") or "").strip()[:100]
    like = f"%{q}%"
    results = []
    for a in (await s.db.execute(select(Agent).where(Agent.org_id == ctx.org.id, Agent.name.ilike(like)).limit(10))).scalars():
        results.append({"id": f"agent:{a.id}", "title": f"Agent: {a.name}", "url": link(f"/agents/{a.id}")})
    for c in (await s.db.execute(select(Campaign).where(Campaign.org_id == ctx.org.id, Campaign.name.ilike(like)).limit(10))).scalars():
        results.append({"id": f"campaign:{c.id}", "title": f"Campaign: {c.name}", "url": link(f"/campaigns/{c.id}")})
    leads = (await s.db.execute(select(Lead).where(Lead.org_id == ctx.org.id, or_(
        Lead.name.ilike(like), Lead.phone.ilike(like), Lead.company.ilike(like), Lead.email.ilike(like))).limit(10))).scalars().all()
    for l in leads:
        results.append({"id": f"contact:{l.id}", "title": f"Contact: {l.name or l.phone}"
                        + (f" ({l.company})" if l.company else ""), "url": link(f"/contacts?contact={l.id}")})
    calls = (await s.db.execute(select(CallLog).where(CallLog.org_id == ctx.org.id, or_(
        CallLog.summary.ilike(like), CallLog.lead_id.in_([l.id for l in leads]) if leads else False))
        .order_by(CallLog.started_at.desc()).limit(10))).scalars().all()
    for c in calls:
        results.append({"id": f"call:{c.id}", "title": f"Call {c.started_at:%b %d}" if c.started_at else "Call",
                        "url": link(f"/calls?call={c.id}")})
    return {"results": results}


@tool("fetch", "Open a search result", "Opens an item returned by search (agent, campaign, contact or call).",
      {"id": {"type": "string", "description": "An id from search, like agent:… or call:…"}}, ["id"])
async def fetch(s: Session, args: dict) -> dict:
    kind, _, raw = str(args.get("id") or "").partition(":")
    if kind == "agent":
        data = await get_agent(s, {"agent_id": raw})
    elif kind == "campaign":
        data = await get_campaign(s, {"campaign_id": raw})
    elif kind == "call":
        data = await get_call(s, {"call_id": raw})
    elif kind == "contact":
        from app.routers.contacts import get_contact

        data = await get_contact(_uuid({"id": raw}, "id"), s.need_account(), s.db)
    else:
        raise ToolError("Unknown id. Use an id returned by search.")
    import json

    return {"id": args["id"], "title": data.get("name") or data.get("title") or args["id"],
            "text": json.dumps(data, default=str, ensure_ascii=False)[:20000], "url": data.get("url"), "metadata": {"type": kind}}
