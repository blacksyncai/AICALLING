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
                             "shows the choices). After that, write the first agent's script with the user "
                             "(get_script_guide) and create it with create_agent."}
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
        {"step": "Build an AI agent", "done": bool(built), "how": "get_script_guide, then write the script with the user and create_agent", "agents": len(built)},
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
call direction. Use the industry key with create_account; the agent types are ideas for what to build.""",
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
            "next_step": "Add business knowledge (scan_website if they have a site), then write the agent's "
                         "script with the user (get_script_guide) and create_agent.",
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


@tool("list_voices", "List voices", "Voices an agent can use (pass the id to create_agent or update_agent).")
async def list_voices(s: Session, args: dict) -> dict:
    from app.routers.settings import list_voices as lv

    s.need_account()
    out = await lv()
    voices = out.get("voices", []) if isinstance(out, dict) else []
    keep = ("id", "name", "gender", "accent", "language", "description", "category")
    return {"voices": [{k: v.get(k) for k in keep if v.get(k) is not None} for v in voices[:60]]}


SECTION_KEYS = ("identity", "context", "approved", "opening", "flow", "close", "situations", "rules")
SECTIONS_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "description": "The script in BlackSync's 8 sections (see get_script_guide). Markdown text for each.",
    "properties": {
        "identity": {"type": "string", "description": "Identity and Objective (with personality and delivery)."},
        "context": {"type": "string", "description": "What You Know: call details and business facts."},
        "approved": {"type": "string", "description": "Approved Wording: lines said word for word ('' if none)."},
        "opening": {"type": "string", "description": "Opening: first lines and discovery questions, Wait. after each."},
        "flow": {"type": "string", "description": "Conversation Flow: reason for the call and the stages."},
        "close": {"type": "string", "description": "Next Step and Close, including the callback flow."},
        "situations": {"type": "string", "description": "Situations and Objections: ### per objection, then direct "
                                                         "questions and other outcomes."},
        "rules": {"type": "string", "description": "Rules and Boundaries, then the internal call summary."},
    },
}


def _sections(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    return {k: str(raw[k]).strip()[:20000] for k in SECTION_KEYS if isinstance(raw.get(k), str)}


def _assemble(sections: dict) -> str:
    from app.agent.composer import assemble

    return assemble(sections)


def _sectioned_builder(sections: dict) -> dict:
    """The builder data the agent editor uses to show and edit the script section by section."""
    from app.agent.composer import SECTIONS_V4

    return {"schema": "v4", "sections": {k: sections.get(k, "") for k in SECTION_KEYS},
            "section_order": [list(x) for x in SECTIONS_V4], "source": "assistant"}


SCRIPT_GUIDE = """HOW A BLACKSYNC CALL SCRIPT IS WRITTEN (the structure our best agents use)

Write the script as these 8 sections (pass them to create_agent as "sections"; each shows as its own editable
section in BlackSync). What goes in each is below, in order. Spoken lines go in quotes; put "Wait." after
every question so the agent stops and listens. Lines are examples the agent adapts, unless marked "say exactly".

identity (Identity and Objective) — who the agent is ("You are <name> from <company>, calling on behalf of <person/team>"),
  who it's speaking with, and the one goal of the call (e.g. earn a 15-minute conversation). For outbound
  prospecting: "Begin with a few natural questions about their situation before explaining why you're calling."
  Also personality and delivery: tone; one or two short sentences per turn; one question at a time; acknowledge what
  they said; don't repeat answered questions; how to handle "are you an AI?" (always honest if asked).
context (What You Know) — call details and facts: {{name}} and other contact fields, company, team, time zone,
  what the business offers. Only real facts.
approved (Approved Wording) — lines the user wants said word for word (prices, offers, disclaimers); "" if none.
opening (Opening) — the exact first lines with Wait. after each: confirm the person, say who's calling, ask for a quick
  second, then 1-3 easy questions about their situation (skip any they already answered). If they ask why
  you're calling, answer straight away.
flow (Conversation Flow) — the reason for the call: one or two plain sentences, then the value only if they're curious, then an open question
  ("would you consider some help if the numbers made sense?").
  If they're open: timeline if unknown, then offer the next step (a call with the team).
close (Next Step and Close) — the ask, what to say if yes / not now, the goodbye, and the callback flow:
  day → time → confirm time zone → repeat once ("So Thursday around two Central?") → "I'll pass that along so
  the team can confirm." Never claim it's booked unless a booking tool confirmed it.
situations (Situations and Objections) —
 one ### subsection per objection — heading = what they say; the first answer (often a question back: "Is X the main
  reason?"), then "If they agree:" / "If they give another reason:" follow-ups with the words to say. One
  thoughtful try, then thank them and end politely. Typical: "I'm doing it myself", price/fees, "already have
  someone", "not interested", "send me something", "I'm busy", "how did you get my number?".
  Then direct questions — "do you have a buyer/customer?", "what do you charge?", "are you a real company?", "what
  would you do differently?": honest short answers; anything the agent can't know is for the team to explain.
  Never invent prices, results, buyers, offers or guarantees.
  Then other outcomes — sold/not relevant anymore, wrong number, clear no, do-not-call (end immediately and flag it).
rules (Rules and Boundaries) — the musts and must-nots for this business, then the internal call summary: the facts
  to record, only what they actually said; unknown otherwise.

Platform facts: the agent can end calls; it can transfer only if the agent has a transfer number, and book only
with a connected calendar — otherwise it takes a callback preference. Contact fields available as placeholders:
{{name}}, {{full_name}}, {{company}}, {{phone}}, {{email}}, {{role}}, plus any custom contact columns (e.g.
{{property_address}}; {{property_street}} is derived from it). BlackSync adds its own call-handling rules
(interruptions, voicemail, do-not-call) at call time, so the script doesn't need them. A good script is usually
1,500-3,000 words."""


@tool("get_script_guide", "How to write a call script",
      """Returns the structure BlackSync's best call scripts follow (sections, spoken lines, objection flows,
callback flow, call summary) and the placeholders and tools agents have. Read it before writing a script for
create_agent or rewriting one with update_agent.""")
async def get_script_guide(s: Session, args: dict) -> dict:
    return {"guide": SCRIPT_GUIDE}


@tool("create_agent", "Create an agent from your own script",
      """Creates an AI calling agent from the script you write with the user (call get_script_guide first and follow
its structure; write the full script, not a summary). The agent starts paused: offer a test call
(call_with_agent) and launch_agent when they're happy.""",
      {"name": {"type": "string", "description": "Agent name shown in BlackSync, e.g. \"FSBO Prospecting · Maya\"."},
       "sections": SECTIONS_SCHEMA,
       "system_prompt": {"type": "string", "description": "Only if you can't split it into sections: the whole script."},
       "first_message": {"type": "string", "description": "The exact first line when the call connects, e.g. "
                                                         "\"Hey, this is {{name}}, right?\""},
       "description": {"type": "string", "description": "One line on what the agent does."},
       "voice_id": {"type": "string", "description": "From list_voices (optional; a natural default is used)."},
       "transfer_number": {"type": "string", "description": "Number to transfer interested people to (optional)."},
       "voicemail_action": {"type": "string", "enum": ["hang_up", "leave_message", "ignore"]},
       "voicemail_message": STR,
       "ai_disclosure": {"type": "boolean", "description": "Say it's an AI up front (default true). Always honest "
                                                           "when asked either way."},
       "extraction_fields": {"type": "array", "maxItems": 12, "items": {
           "type": "object", "required": ["name"], "additionalProperties": False,
           "properties": {"name": {"type": "string", "description": "snake_case"}, "description": STR}},
           "description": "What to record from each call (the call summary)."},
       "success_criteria": {"type": "string", "description": "What counts as a successful call."}},
      ["name", "first_message"], read_only=False)
async def create_agent(s: Session, args: dict) -> dict:
    from app.routers.agents import AgentUpdate, new_agent_from_template, update_agent as ua

    ctx = s.need_account()
    sections = _sections(args.get("sections"))
    script = _assemble(sections) if sections else str(args.get("system_prompt") or "")
    if len(script.split()) < 80:
        raise ToolError("That script is too short to run a call. Write the full script (get_script_guide shows the "
                        "structure), then try again.")
    agent = new_agent_from_template("blank", str(args.get("name") or "New agent")[:80])
    agent.org_id, agent.status = ctx.org.id, "paused"
    from app.services import agent_calendar

    await agent_calendar.apply_default(s.db, agent)
    s.db.add(agent)
    await s.db.commit()
    fields = {k: args[k] for k in ("first_message", "description", "voice_id", "transfer_number",
                                   "voicemail_action", "voicemail_message", "ai_disclosure", "extraction_fields",
                                   "success_criteria") if args.get(k) is not None}
    fields["system_prompt"] = script
    if sections:
        fields["builder"] = _sectioned_builder(sections)
    try:
        body = AgentUpdate(**fields)
    except ValueError as exc:
        await s.db.delete(agent)
        await s.db.commit()
        raise ToolError(f"Check the values: {exc}")
    a = await ua(agent.id, body, ctx, s.db)
    return {**_agent_brief(a), "words": len(script.split()), "sections": list(sections) if sections else None,
            "next_step": "Offer a test call to the user's own phone (call_with_agent), then launch_agent."}


@tool("update_agent", "Edit an AI agent",
      """Changes an agent's settings. Only pass what should change. system_prompt replaces the whole call script, so
read it with get_agent first and keep everything that isn't meant to change.""",
      {"agent_id": ID, "name": STR, "first_message": {"type": "string", "description": "What it says first."},
       "sections": {**SECTIONS_SCHEMA, "description": "Sections to replace (only the ones that change); the rest "
                                                      "stay. Works on agents built in sections."},
       "system_prompt": {"type": "string", "description": "The full call script/instructions."},
       "voice_id": STR, "transfer_number": {"type": "string", "description": "\"\" removes it."},
       "voicemail_action": {"type": "string", "enum": ["hang_up", "leave_message", "ignore"]},
       "voicemail_message": STR,
       "max_duration_seconds": {"type": "integer", "minimum": 30, "maximum": 3600}},
      ["agent_id"], read_only=False, idempotent=True)
async def update_agent(s: Session, args: dict) -> dict:
    from app.routers.agents import AgentUpdate, update_agent as ua

    fields = {k: v for k, v in args.items() if k not in ("agent_id", "sections") and v is not None}
    changed = _sections(args.get("sections"))
    if changed:
        from app.routers.agents import get_agent as ga

        current = await ga(_uuid(args, "agent_id"), s.need_account(), s.db)
        b = current.get("builder") or {}
        if b.get("schema") != "v4" or not b.get("sections"):
            raise ToolError("This agent's script isn't split into sections. Send the whole script as system_prompt.")
        merged = {**b["sections"], **changed}
        fields["system_prompt"] = _assemble(merged)
        fields["builder"] = {**b, **_sectioned_builder(merged)}
    if not fields:
        raise ToolError("Nothing to change.")
    try:
        body = AgentUpdate(**fields)
    except ValueError as exc:
        raise ToolError(f"Check the values: {exc}")
    a = await ua(_uuid(args, "agent_id"), body, s.need_account(), s.db)
    return {"updated": sorted(set(fields) - {"builder"} | ({"sections"} if changed else set())), **_agent_brief(a)}


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


# ── Shared helpers for the tools below ────────────────────────────────────────


def _refusal(resp) -> dict:
    """Some endpoints answer a refusal as a JSONResponse (with a code the app acts on) instead of raising."""
    import json

    try:
        return json.loads(resp.body)
    except (ValueError, AttributeError):
        return {"detail": "That didn't work."}


def _ids(args: dict, key: str, most: int = 500) -> list[uuid.UUID]:
    raw = args.get(key) or []
    if not isinstance(raw, list) or not raw:
        raise ToolError(f"{key} needs at least one id.")
    return [_uuid({"id": x}, "id") for x in raw[:most]]


IDS = {"type": "array", "items": STR, "minItems": 1, "maxItems": 500, "description": "Contact ids (from list tools)."}
CRM = {"type": "string", "description": "The CRM's key, e.g. followupboss, hubspot, close (from list_crm_integrations)."}


def _crm_key(args: dict) -> str:
    key = str(args.get("crm") or "").strip().lower()
    if not key:
        raise ToolError("crm is required (see list_crm_integrations).")
    return key


# ── Contacts (more) ───────────────────────────────────────────────────────────


@tool("get_contact", "Get a contact", "One contact in full, with every call made to them (outcome, summary, length).",
      {"contact_id": ID}, ["contact_id"])
async def get_contact_tool(s: Session, args: dict) -> dict:
    from app.routers.contacts import get_contact

    c = await get_contact(_uuid(args, "contact_id"), s.need_account(), s.db)
    return {**c, "url": link(f"/contacts/{c['id']}")}


@tool("update_contact", "Edit a contact",
      """Changes a contact's details, pipeline status (e.g. interested, callback, meeting_booked, not_interested),
tags, notes, campaign or Do-Not-Call flag. Only the fields you pass change.""",
      {"contact_id": ID, "name": STR, "phone": STR, "email": STR, "company": STR, "role": STR, "notes": STR,
       "status": STR, "tags": {"type": "array", "items": STR}, "campaign_id": ID,
       "do_not_call": {"type": "boolean"}},
      ["contact_id"], read_only=False, idempotent=True)
async def update_contact_tool(s: Session, args: dict) -> dict:
    from app.routers.contacts import ContactPatch, update_contact

    fields = {k: v for k, v in args.items() if k != "contact_id" and v is not None}
    try:
        body = ContactPatch(**fields)
    except ValueError as exc:
        raise ToolError(f"Check the values: {exc}")
    return _contact_brief(await update_contact(_uuid(args, "contact_id"), body, s.need_account(), s.db))


@tool("bulk_update_contacts", "Update many contacts",
      """Applies one change to many contacts: add_to_campaign (queues them to be called), set_status, add_tag,
dnc_on or dnc_off.""",
      {"contact_ids": IDS, "action": {"type": "string", "enum": ["add_to_campaign", "set_status", "add_tag", "dnc_on", "dnc_off"]},
       "campaign_id": ID, "status": STR, "tag": STR},
      ["contact_ids", "action"], read_only=False, idempotent=True)
async def bulk_update_contacts(s: Session, args: dict) -> dict:
    from app.routers.contacts import BulkAction, bulk_action

    action = str(args.get("action") or "")
    if action not in ("add_to_campaign", "set_status", "add_tag", "dnc_on", "dnc_off"):
        raise ToolError("Unknown action.")
    return await bulk_action(BulkAction(ids=_ids(args, "contact_ids"), action=action,
                                        campaign_id=_uuid(args, "campaign_id", False), status=args.get("status"),
                                        tag=args.get("tag")), s.need_account(), s.db)


@tool("call_contact", "Call a contact now",
      "Places a real call right now: the agent calls this contact. Uses calling credits. Confirm with the user first.",
      {"contact_id": ID, "agent_id": ID}, ["contact_id", "agent_id"], read_only=False, destructive=True, open_world=True)
async def call_contact_tool(s: Session, args: dict) -> dict:
    from app.routers.contacts import CallContact, call_contact

    out = await call_contact(_uuid(args, "contact_id"), CallContact(agent_id=_uuid(args, "agent_id")),
                             s.need_account(), s.db)
    return {**out, "next_step": "When the call ends, get_call shows the transcript and outcome."}


# ── Campaigns (more) ──────────────────────────────────────────────────────────


@tool("update_campaign", "Edit a campaign",
      """Changes a campaign's name, agent, calling hours (HH:MM in its time zone), days (0=Mon … 6=Sun), time zone,
retries, concurrency or caller number. Only the fields you pass change.""",
      {"campaign_id": ID, "name": STR, "description": STR, "agent_id": ID,
       "call_window_start": STR, "call_window_end": STR,
       "call_days": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 6}},
       "timezone": STR, "max_attempts": {"type": "integer", "minimum": 1, "maximum": 10},
       "retry_delay_minutes": {"type": "integer", "minimum": 1},
       "max_concurrent_calls": {"type": "integer", "minimum": 1, "maximum": 20}, "phone_number_id": ID},
      ["campaign_id"], read_only=False, idempotent=True)
async def update_campaign_tool(s: Session, args: dict) -> dict:
    from app.routers.campaigns import CampaignUpdate, update_campaign

    fields = {k: v for k, v in args.items() if k != "campaign_id" and v is not None}
    try:
        body = CampaignUpdate(**fields)
    except ValueError as exc:
        raise ToolError(f"Check the values: {exc}")
    out = await update_campaign(_uuid(args, "campaign_id"), body, s.need_account(), s.db)
    return _campaign_brief(out.get("campaign", out) if isinstance(out, dict) else out)


@tool("list_campaign_contacts", "Contacts in a campaign",
      "The contacts in one campaign with their status (filter by status, e.g. new, no_answer, interested).",
      {"campaign_id": ID, "status": STR, "limit": LIMIT}, ["campaign_id"])
async def list_campaign_contacts(s: Session, args: dict) -> dict:
    from app.routers.campaigns import list_campaign_leads

    out = await list_campaign_leads(_uuid(args, "campaign_id"), s.need_account(), s.db, status=args.get("status") or None,
                                    page=1, page_size=_int(args, "limit", 20, 1, 100))
    items = out.get("leads") or out.get("items") or []
    return {"total": out.get("total"), "by_status": out.get("status_counts"),
            "contacts": [_contact_brief(c) for c in items]}


@tool("call_campaign_contacts", "Call picked contacts now",
      """Dials the given contacts from a campaign right now (within its calling hours), without starting the whole
campaign. Uses calling credits. Confirm with the user first.""",
      {"campaign_id": ID, "contact_ids": IDS}, ["campaign_id", "contact_ids"],
      read_only=False, destructive=True, open_world=True)
async def call_campaign_contacts(s: Session, args: dict) -> dict:
    from app.routers.campaigns import CallSelectedRequest, call_selected_leads

    bg = BackgroundTasks()
    out = await call_selected_leads(_uuid(args, "campaign_id"), CallSelectedRequest(lead_ids=_ids(args, "contact_ids")),
                                    bg, s.need_account(), s.db)
    await _schedule(bg)
    return {"dialing": out.get("dispatched"), "skipped_dnc": out.get("skipped_dnc")}


# ── Meetings and call follow-up ───────────────────────────────────────────────


@tool("list_meetings", "Booked meetings",
      "Meetings the agents booked (newest first) with contact, time and status, plus show-rate stats.",
      {"upcoming_only": {"type": "boolean", "description": "Only meetings still scheduled."}, "limit": LIMIT})
async def list_meetings_tool(s: Session, args: dict) -> dict:
    from app.routers.meetings import list_meetings

    out = await list_meetings(s.need_account(), s.db, status="upcoming" if args.get("upcoming_only") else "all",
                              limit=_int(args, "limit", 20, 1, 100))
    return {"total": out["total"], "stats": out["stats"], "meetings": out["items"]}


@tool("update_meeting", "Update a meeting",
      "Marks a booked meeting completed, no_show or cancelled, or moves it (start as ISO 8601 with offset).",
      {"call_id": {"type": "string", "description": "The meeting's call_id (from list_meetings)."},
       "status": {"type": "string", "enum": ["scheduled", "completed", "no_show", "cancelled"]},
       "start": {"type": "string", "description": "e.g. 2026-11-03T15:00:00-05:00"},
       "duration_minutes": {"type": "integer", "minimum": 5, "maximum": 480}},
      ["call_id"], read_only=False, idempotent=True)
async def update_meeting_tool(s: Session, args: dict) -> dict:
    from app.routers.meetings import MeetingUpdate, update_meeting

    fields = {k: args[k] for k in ("status", "start", "duration_minutes") if args.get(k) is not None}
    try:
        body = MeetingUpdate(**fields)
    except ValueError as exc:
        raise ToolError(f"Check the values: {exc}")
    return await update_meeting(_uuid(args, "call_id"), body, s.need_account(), s.db)


@tool("reanalyze_call", "Re-read a call",
      "Runs the post-call analysis again (outcome, summary, details collected), e.g. after changing the agent.",
      {"call_id": ID}, ["call_id"], read_only=False, idempotent=True)
async def reanalyze_call_tool(s: Session, args: dict) -> dict:
    from app.routers.calls import reanalyze_call

    bg = BackgroundTasks()
    out = await reanalyze_call(_uuid(args, "call_id"), bg, s.need_account(), s.db)
    await _schedule(bg)
    return {**out, "next_step": "Give it a minute, then get_call shows the new outcome."}


# ── Lead Finder (property owner lookups) ──────────────────────────────────────


def _lookup_out(out: dict) -> dict:
    lk = out.get("lookup", out)
    return {**lk, "url": link("/lead-finder")}


def _pay_needed(body: dict) -> dict:
    """Turn a 402 from Lead Finder into a clear answer: ask the user to accept the price, or say why it can't run."""
    if body.get("code") == "confirm_price":
        price = body.get("price_cents") or 0
        return {"needs_confirmation": True, "price_cents": price, "count": body.get("count"),
                "total_cents": body.get("total_cents"), "balance_cents": body.get("balance_cents"),
                "message": f"Today's free lookups are used up. Each new lookup costs ${price / 100:.2f}. "
                           f"Ask the user, then call again with expected_price_cents={price}."}
    raise ToolError(body.get("detail") or "Lead Finder couldn't run that.")


@tool("lead_finder_status", "Lead Finder balance",
      "Whether Lead Finder is on, free lookups left today, lookup credits, balance and the price per lookup.")
async def lead_finder_status(s: Session, args: dict) -> dict:
    from app.routers.lead_finder import get_usage

    return {**await get_usage(s.need_account(), s.db), "url": link("/lead-finder")}


@tool("lookup_property", "Find a property's owner",
      """Looks up who owns a US property and their phone numbers and emails. Pass the full address as one line
("123 Main St, Erie, PA 16503") or street/city/state/zip. A saved result is free; a new one uses a free daily
lookup or a lookup credit. If it answers needs_confirmation, tell the user the price and only call again with
expected_price_cents once they agree.""",
      {"address": {"type": "string", "description": "Full address on one line."}, "street": STR, "city": STR,
       "state": STR, "zip": STR, "expected_price_cents": {"type": "integer", "minimum": 0}},
      read_only=False, open_world=True)
async def lookup_property(s: Session, args: dict) -> dict:
    from fastapi.responses import JSONResponse

    from app.routers.lead_finder import LookupRequest, create_lookup
    from app.services import lead_finder as lf

    parts = {k: str(args.get(k) or "").strip() for k in ("street", "city", "state", "zip")}
    if args.get("address") and not parts["street"]:
        parsed = lf.parse_full_address(str(args["address"])[:400])
        parts = {k: str(parsed.get(k) or "") for k in parts}
    if not parts["street"]:
        raise ToolError("Give the property address (street, city, state).")
    out = await create_lookup(LookupRequest(**parts, expected_price_cents=args.get("expected_price_cents")),
                              s.need_account(), s.db)
    if isinstance(out, JSONResponse):
        return _pay_needed(_refusal(out))
    return {**_lookup_out(out), "cached": out.get("cached"),
            "next_step": "save_lookup_to_contacts adds the owner to Contacts so an agent can call them."}


@tool("list_property_lookups", "Recent property lookups", "The latest single-address owner lookups.", {"limit": LIMIT})
async def list_property_lookups(s: Session, args: dict) -> dict:
    from app.routers.lead_finder import list_lookups

    return await list_lookups(s.need_account(), s.db, limit=_int(args, "limit", 20, 1, 100))


@tool("get_property_lookup", "Open a property lookup", "One saved lookup with the owner's phones and emails (free).",
      {"lookup_id": ID}, ["lookup_id"])
async def get_property_lookup(s: Session, args: dict) -> dict:
    from app.routers.lead_finder import get_lookup

    return _lookup_out(await get_lookup(_uuid(args, "lookup_id"), s.need_account(), s.db))


@tool("save_lookup_to_contacts", "Save an owner as a contact",
      "Adds the owner from a lookup to Contacts (no duplicates), optionally straight into a campaign.",
      {"lookup_id": ID, "campaign_id": ID}, ["lookup_id"], read_only=False, idempotent=True)
async def save_lookup_to_contacts(s: Session, args: dict) -> dict:
    from app.routers.contacts import BulkAction, bulk_action
    from app.routers.lead_finder import save_as_lead

    ctx = s.need_account()
    out = await save_as_lead(_uuid(args, "lookup_id"), ctx, s.db)
    campaign_id = _uuid(args, "campaign_id", False)
    if campaign_id:
        await bulk_action(BulkAction(ids=[uuid.UUID(out["lead_id"])], action="add_to_campaign", campaign_id=campaign_id),
                          ctx, s.db)
    return {"contact_id": out["lead_id"], "created": out["created"], "in_campaign": str(campaign_id) if campaign_id else None}


@tool("bulk_lookup_prepare", "Prepare a bulk owner lookup",
      """Reads a CSV of addresses (columns like street, city, state, zip, or one address column) and says how many
are new and what it will cost. Nothing is looked up or charged yet: bulk_lookup_start runs it.""",
      {"csv": {"type": "string", "description": "CSV text with a header row."}, "filename": STR}, ["csv"],
      read_only=False)
async def bulk_lookup_prepare(s: Session, args: dict) -> dict:
    from app.routers.lead_finder import BatchUpload, upload_batch

    text = str(args.get("csv") or "")
    if not text.strip():
        raise ToolError("csv is required.")
    try:
        body = BatchUpload(filename=str(args.get("filename") or "addresses.csv")[:255], text=text)
    except ValueError:
        raise ToolError("That file is too big. Split it into smaller parts.")
    out = await upload_batch(body, s.need_account(), s.db)
    keep = ("id", "valid", "invalid", "cached_rows", "new_rows", "pay_with", "price_cents", "max_total_cents",
            "enough_credits")
    return {**{k: out.get(k) for k in keep}, "invalid": (out.get("invalid") or [])[:20],
            "next_step": "Tell the user the cost, then bulk_lookup_start with this id."}


@tool("bulk_lookup_start", "Run a bulk owner lookup",
      """Runs a prepared bulk lookup in the background. Uses lookup credits or balance for every new address.
Confirm the cost with the user first; if it answers needs_confirmation, call again with expected_price_cents.""",
      {"batch_id": ID, "expected_price_cents": {"type": "integer", "minimum": 0}}, ["batch_id"],
      read_only=False, destructive=True, open_world=True)
async def bulk_lookup_start(s: Session, args: dict) -> dict:
    from fastapi.responses import JSONResponse

    from app.routers.lead_finder import BatchStart, start_batch

    bg = BackgroundTasks()
    out = await start_batch(_uuid(args, "batch_id"), bg, s.need_account(), s.db,
                            BatchStart(expected_price_cents=args.get("expected_price_cents")))
    if isinstance(out, JSONResponse):
        return _pay_needed(_refusal(out))
    await _schedule(bg)
    return {**out, "next_step": "get_bulk_lookup shows progress; save_bulk_to_contacts adds the owners found."}


@tool("get_bulk_lookup", "Bulk lookup progress",
      "A bulk lookup's progress and its rows (owner found or not). Without batch_id, lists recent bulk lookups.",
      {"batch_id": ID, "limit": LIMIT})
async def get_bulk_lookup(s: Session, args: dict) -> dict:
    from app.routers.lead_finder import get_batch, list_batches

    if not args.get("batch_id"):
        return await list_batches(s.need_account(), s.db)
    out = await get_batch(_uuid(args, "batch_id"), s.need_account(), s.db, offset=0, limit=_int(args, "limit", 20, 1, 100))
    out.pop("usage", None)
    return out


@tool("save_bulk_to_contacts", "Save bulk owners as contacts",
      "Adds every owner found in a bulk lookup to Contacts (no duplicates), optionally into a campaign.",
      {"batch_id": ID, "campaign_id": ID}, ["batch_id"], read_only=False, idempotent=True)
async def save_bulk_to_contacts(s: Session, args: dict) -> dict:
    from sqlalchemy import select

    from app.models.lead_finder import PropertyLookup
    from app.routers.contacts import BulkAction, bulk_action
    from app.routers.lead_finder import save_batch_leads

    ctx = s.need_account()
    batch_id = _uuid(args, "batch_id")
    out = await save_batch_leads(batch_id, ctx, s.db)
    campaign_id = _uuid(args, "campaign_id", False)
    if campaign_id:
        ids = list((await s.db.execute(select(PropertyLookup.lead_id).where(
            PropertyLookup.batch_id == batch_id, PropertyLookup.org_id == ctx.org.id,
            PropertyLookup.lead_id.is_not(None)))).scalars())
        if ids:
            await bulk_action(BulkAction(ids=ids, action="add_to_campaign", campaign_id=campaign_id), ctx, s.db)
        out["in_campaign"] = len(ids)
    return out


# ── Radar (who to call now, from the connected CRM) ───────────────────────────

_RADAR_ITEM = ("external_id", "name", "phone", "company", "reason", "stage", "source", "last_touch", "calls")


def _radar_item(i: dict) -> dict:
    bs = i.get("bs") or {}
    out = {k: i.get(k) for k in _RADAR_ITEM if i.get(k) not in (None, "", [])}
    if i.get("dnc"):
        out["dnc"] = True
    if bs:
        out["blacksync"] = {k: bs[k] for k in ("campaign", "calls", "last_outcome", "verified") if bs.get(k)}
    return out


def _radar_summary(scan: dict, per_play: int = 5) -> dict:
    return {"scan_id": scan.get("id"), "crm": scan.get("provider"), "scanned": scan.get("scanned"),
            "depth": scan.get("depth"), "more_to_scan": bool(scan.get("next")),
            "plays": [{"play": pl["key"], "title": pl.get("title"), "why": pl.get("why"), "count": pl.get("count"),
                       "top": [_radar_item(i) for i in pl.get("items", [])[:per_play]]}
                      for pl in scan.get("plays") or [] if pl.get("count")],
            "url": link("/radar")}


@tool("radar_overview", "Radar",
      """Radar finds the people worth calling now in the connected CRM (hot leads, stale follow-ups, old leads).
Shows each CRM Radar can read, its BlackSync pipelines, and the last scan's plays.""")
async def radar_overview(s: Session, args: dict) -> dict:
    from app.routers.radar import overview

    out = await overview(s.need_manager(), s.db)
    return {"crms": [{"crm": c["provider"], "name": c["name"], "account": c["account_label"], "pipelines": c["installs"],
                      "last_scan": _radar_summary(c["last_scan"]) if c.get("last_scan") else None} for c in out["crms"]],
            "url": link("/radar")}


@tool("radar_scan", "Scan the CRM with Radar",
      """Scans a connected CRM and groups people into plays worth calling now. depth: quick (newest), recent
(recent activity, default) or old (oldest first, to revive old leads). Pass continue_from (an earlier scan_id)
to read the next batch of a big CRM.""",
      {"crm": CRM, "depth": {"type": "string", "enum": ["quick", "recent", "old"]},
       "continue_from": {"type": "string", "description": "scan_id to extend."}},
      ["crm"], read_only=False, open_world=True)
async def radar_scan(s: Session, args: dict) -> dict:
    from app.routers.radar import scan

    out = await scan(_crm_key(args), s.need_manager(), s.db, depth=str(args.get("depth") or ""),
                     continue_from=_uuid(args, "continue_from", False))
    return {**_radar_summary(out), "next_step": "radar_play lists everyone in a play; radar_launch calls them."}


@tool("radar_play", "People in a Radar play", "Everyone in one play of a Radar scan (paged).",
      {"scan_id": ID, "play": {"type": "string", "description": "The play key from radar_scan."},
       "offset": {"type": "integer", "minimum": 0}, "limit": LIMIT}, ["scan_id", "play"])
async def radar_play(s: Session, args: dict) -> dict:
    from app.models.crm import CrmConnection, CrmScan
    from app.routers.radar import _require_radar, _scan_view

    ctx = s.need_manager()
    await _require_radar(ctx, s.db)
    row = await s.db.get(CrmScan, _uuid(args, "scan_id"))
    if not row or row.org_id != ctx.org.id:
        raise ToolError("Scan not found.")
    conn = await s.db.get(CrmConnection, row.connection_id)
    view = await _scan_view(s.db, ctx.org.id, row, conn.provider if conn else "")
    pl = next((p for p in view.get("plays") or [] if p["key"] == args.get("play")), None)
    if not pl:
        raise ToolError(f"No play {args.get('play')!r} in that scan. Plays: "
                        + ", ".join(p["key"] for p in view.get("plays") or []))
    start, n = _int(args, "offset", 0, 0, 100000), _int(args, "limit", 20, 1, 100)
    return {"play": pl["key"], "title": pl.get("title"), "why": pl.get("why"), "count": pl.get("count"),
            "offset": start, "people": [_radar_item(i) for i in pl["items"][start:start + n]]}


@tool("radar_list_segments", "CRM lists Radar can open",
      "The CRM's own ponds, lead sources and stages, which radar_open_segment turns into a list to call.",
      {"crm": CRM}, ["crm"])
async def radar_list_segments(s: Session, args: dict) -> dict:
    from app.routers.radar import segments

    return await segments(_crm_key(args), s.need_manager(), s.db)


@tool("radar_open_segment", "Open a CRM list in Radar",
      "Pulls everyone in one pond, lead source, stage or deal stage (Follow Up Boss deals) into a Radar play you can launch.",
      {"crm": CRM, "kind": {"type": "string", "enum": ["pond", "source", "stage", "deal"]},
       "value": {"type": "string", "description": "The segment's value from radar_list_segments."}, "label": STR},
      ["crm", "kind", "value"], read_only=False, open_world=True)
async def radar_open_segment(s: Session, args: dict) -> dict:
    from app.routers.radar import SegmentIn, open_segment

    try:
        body = SegmentIn(kind=str(args.get("kind") or ""), value=str(args.get("value") or ""),
                         label=str(args.get("label") or ""))
    except ValueError as exc:
        raise ToolError(f"Check the values: {exc}")
    return _radar_summary(await open_segment(_crm_key(args), body, s.need_manager(), s.db))


@tool("radar_launch", "Call a Radar play",
      """Calls the people in a Radar play with an agent. mode campaign makes a draft campaign of them (start it with
start_campaign). Pass campaign_id to add to an existing draft, paused, or running outbound campaign;
use that campaign's agent_id. Assigned contacts are skipped. A running campaign may call new contacts during saved hours.
mode pipeline drops them into the agent's BlackSync pipeline in the CRM, where calling starts
on its own. Pass external_ids to call only some. Confirm with the user first.""",
      {"scan_id": ID, "play": STR, "agent_id": ID, "mode": {"type": "string", "enum": ["campaign", "pipeline"]},
       "external_ids": {"type": "array", "items": STR}, "campaign_name": STR, "campaign_id": {**ID, "description": "Optional existing outbound campaign. Uses its current agent and settings; assigned contacts are skipped."}},
      ["scan_id", "play", "agent_id", "mode"], read_only=False, destructive=True, open_world=True)
async def radar_launch(s: Session, args: dict) -> dict:
    from app.routers.radar import LaunchIn, launch

    ids = args.get("external_ids")
    try:
        body = LaunchIn(play=str(args.get("play") or ""), agent_id=_uuid(args, "agent_id"), mode=str(args.get("mode") or ""),
                        external_ids=[str(x) for x in ids] if isinstance(ids, list) else None,
                        campaign_id=_uuid(args, "campaign_id", False),
                        campaign_name=str(args.get("campaign_name") or "")[:120])
    except ValueError as exc:
        raise ToolError(f"Check the values: {exc}")
    out = await launch(_uuid(args, "scan_id"), body, s.need_manager(), s.db)
    if out.get("campaign_id"):
        out["url"] = link(f"/campaigns/{out['campaign_id']}")
        out["next_step"] = ("Added to the existing campaign without changing its settings or status. Running campaigns can call during saved hours."
                            if out.get("existing_campaign") else "The campaign is a draft: start_campaign begins calling.")
    return out


# ── CRM integrations ──────────────────────────────────────────────────────────


@tool("list_crm_integrations", "Connected CRMs", "The CRMs and tools connected to this account and what each can do.")
async def list_crm_integrations(s: Session, args: dict) -> dict:
    from app.routers.crm import overview

    out = await overview(s.need_manager(), s.db)
    names = {p["key"]: p for p in out["providers"]}
    conns = []
    for c in out["connections"]:
        p = names.get(c.get("provider"), {})
        conns.append({"crm": c.get("provider"), "name": p.get("name"), "account": c.get("account_label"),
                      "status": c.get("status"), "can_import": p.get("can_import"),
                      "last_synced_at": c.get("last_synced_at"), "last_error": c.get("last_error")})
    return {"connected": conns, "available": sorted(names), "url": link("/integrations")}


@tool("crm_import_options", "CRM import filters", "The filters a CRM import can use (tags, stages, sources, lists…).",
      {"crm": CRM}, ["crm"])
async def crm_import_options(s: Session, args: dict) -> dict:
    from app.routers.crm import import_options

    return await import_options(_crm_key(args), s.need_manager(), s.db)


@tool("crm_import_contacts", "Import contacts from a CRM",
      """Brings contacts from a connected CRM into BlackSync, optionally into a campaign. filters use the keys and
values from crm_import_options. preview=true only counts them (nothing is imported).""",
      {"crm": CRM, "filters": {"type": "object", "description": "e.g. {\"tags\": [\"Seller\"], \"stage\": \"Lead\"}"},
       "skip_contacted": {"type": "boolean", "description": "Leave out people BlackSync already called."},
       "tag": {"type": "string", "description": "Tag to put on the imported contacts."},
       "limit": {"type": "integer", "minimum": 1, "maximum": 2000}, "campaign_id": ID,
       "preview": {"type": "boolean"}},
      ["crm"], read_only=False, open_world=True)
async def crm_import_contacts(s: Session, args: dict) -> dict:
    from app.routers.crm import ImportIn, import_contacts, import_preview

    try:
        body = ImportIn(filters=args.get("filters") or {}, skip_contacted=bool(args.get("skip_contacted")),
                        list_tag=str(args.get("tag") or "")[:60], limit=_int(args, "limit", 500, 1, 2000),
                        campaign_id=str(args["campaign_id"]) if args.get("campaign_id") else None)
    except ValueError as exc:
        raise ToolError(f"Check the filters: {exc}")
    key, ctx = _crm_key(args), s.need_manager()
    if args.get("preview"):
        out = await import_preview(key, body, ctx, s.db)
        if isinstance(out, dict) and isinstance(out.get("sample"), list):
            out["sample"] = out["sample"][:10]
        return out
    return await import_contacts(key, ctx, s.db, body)


@tool("crm_activity", "CRM sync log", "The latest sync activity for a CRM: calls logged, imports, errors.",
      {"crm": CRM, "limit": LIMIT}, ["crm"])
async def crm_activity(s: Session, args: dict) -> dict:
    from app.routers.crm import activity

    out = await activity(_crm_key(args), s.need_manager(), s.db)
    return {"items": out["items"][:_int(args, "limit", 20, 1, 50)]}


# ── Phone numbers (more) ──────────────────────────────────────────────────────


@tool("search_phone_numbers", "Find numbers to buy", "Phone numbers available to buy, optionally in an area code.",
      {"area_code": {"type": "string", "description": "3 digits, e.g. 512."}})
async def search_phone_numbers(s: Session, args: dict) -> dict:
    from app.routers.phone_numbers import available_numbers

    out = await available_numbers(s.need_manager(), s.db, area_code=str(args.get("area_code") or ""), carrier=None)
    return {"numbers": (out.get("numbers") or [])[:20]}


@tool("buy_phone_number", "Buy a phone number",
      """Buys a number for the account. A number beyond the plan's included ones is charged monthly: if it answers
needs_confirmation, tell the user the price and only call again with confirm_charge=true once they agree.""",
      {"number": {"type": "string", "description": "From search_phone_numbers, e.g. +15125550123."}, "label": STR,
       "confirm_charge": {"type": "boolean"}},
      ["number"], read_only=False, destructive=True, open_world=True)
async def buy_phone_number(s: Session, args: dict) -> dict:
    from fastapi.responses import JSONResponse

    from app.routers.phone_numbers import PurchaseIn, purchase_number

    body = PurchaseIn(number=str(args.get("number") or ""), label=str(args.get("label") or "")[:100],
                      confirm_charge=bool(args.get("confirm_charge")))
    try:
        out = await purchase_number(body, s.need_manager(), s.db)
    except HTTPException as exc:
        if exc.status_code == 409 and isinstance(exc.detail, dict) and exc.detail.get("code") == "confirm_charge":
            return {"needs_confirmation": True, "unit_cents": exc.detail.get("unit_cents"),
                    "message": exc.detail.get("message")}
        raise
    if isinstance(out, JSONResponse):
        url = _refusal(out).get("checkout_url")
        return {"needs_payment": True, "checkout_url": url,
                "message": "This account has no plan, so the number is bought through checkout. Send the user this link."}
    return out


@tool("update_phone_number", "Edit a phone number",
      "Renames a number, makes it the default caller ID, or puts a rested (spam-flagged) number back into rotation.",
      {"number_id": ID, "label": STR, "make_default": {"type": "boolean"},
       "resume": {"type": "boolean", "description": "End its rest so campaigns use it again."}},
      ["number_id"], read_only=False, idempotent=True)
async def update_phone_number(s: Session, args: dict) -> dict:
    from app.routers.phone_numbers import NumberPatch, resume_number, update_number

    ctx, number_id = s.need_manager(), _uuid(args, "number_id")
    out = None
    if args.get("label") is not None or args.get("make_default"):
        out = await update_number(number_id, NumberPatch(label=args.get("label"), is_default=bool(args.get("make_default")) or None),
                                  ctx, s.db)
    if args.get("resume"):
        out = await resume_number(number_id, ctx, s.db)
    if out is None:
        raise ToolError("Pass label, make_default or resume.")
    return out


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


# Radar rule tools use the exact dashboard validation/permissions/entitlements.
def _rule_tool_schema():
    from app.services.crm.automation_schema import RuleIn
    schema = RuleIn.model_json_schema()
    definitions = schema.get("$defs", {})
    def expand(value):
        if isinstance(value, list):
            return [expand(x) for x in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            return expand(definitions[value["$ref"].rsplit("/", 1)[-1]])
        return {k: expand(v) for k, v in value.items() if k != "$defs"}
    return expand(schema)


RULE_SCHEMA = _rule_tool_schema()


def _rule_body(args):
    from pydantic import ValidationError
    from app.services.crm.automation_schema import RuleIn
    try:
        return RuleIn.model_validate(args.get("rule") or {})
    except ValidationError as exc:
        raise ToolError("Invalid automation rule. Use the exact source and destination IDs from radar_automation_resources; provide a supported condition and one to four actions.") from exc


@tool("radar_list_automations", "Radar automation rules", "List this account's saved rules, statuses, versions, sources and CRM connections.")
async def radar_list_automations(s: Session, args: dict) -> dict:
    from app.routers.radar_automations import list_rules
    return await list_rules(s.need_manager(), s.db)


@tool("radar_automation_resources", "Radar rule destinations", "Read actual agents, campaigns, ponds, CRM stages and pipelines for building a rule. Never invent IDs.", {"crm": STR}, ["crm"], open_world=True)
async def radar_automation_resources(s: Session, args: dict) -> dict:
    from app.routers.radar_automations import resources
    return await resources(_crm_key(args), s.need_manager(), s.db)


@tool("radar_preview_automation", "Preview a Radar rule", "Validate a rule and preview matching calls without activating it or writing to the CRM.", {"rule": RULE_SCHEMA}, ["rule"], open_world=True)
async def radar_preview_automation(s: Session, args: dict) -> dict:
    from app.routers.radar_automations import preview
    return await preview(_rule_body(args), s.need_manager(), s.db)


@tool("radar_save_automation", "Save a Radar draft rule", "Create a draft, or edit rule_id. Editing an active rule returns it to draft and requires explicit reactivation. Confirm changes with the user first. Does not activate or run a rule.",
      {"rule": RULE_SCHEMA, "rule_id": ID}, ["rule"], read_only=False)
async def radar_save_automation(s: Session, args: dict) -> dict:
    from app.routers.radar_automations import save_rule, edit_rule
    ctx = s.need_manager()
    body = _rule_body(args)
    key = _uuid(args, "rule_id", False)
    return await edit_rule(key, body, ctx, s.db) if key else await save_rule(body, ctx, s.db)


@tool("radar_set_automation_state", "Activate or pause a Radar rule", "Activation enables future matching CRM actions. Explain the rule and obtain approval before repeating with confirmed=true. Pausing stops future work; completed actions remain.",
      {"rule_id": ID, "status": {"type": "string", "enum": ["active", "paused"]}, "confirmed": {"type": "boolean"}},
      ["rule_id", "status"], read_only=False, destructive=True, open_world=True)
async def radar_set_automation_state(s: Session, args: dict) -> dict:
    from app.routers.radar_automations import owned_rule, require, state, StateIn
    ctx = s.need_manager()
    await require(ctx, s.db)
    key = _uuid(args, "rule_id")
    await owned_rule(s.db, ctx.org.id, key)
    if args.get("status") not in ("active", "paused"):
        raise ToolError("Choose active or paused.")
    if args.get("confirmed") is not True:
        return {"needs_confirmation": True, "rule_id": str(key), "status": args["status"], "writes_performed": False}
    return await state(key, StateIn(status=args["status"]), ctx, s.db)


@tool("radar_automation_activity", "Radar rule execution history", "Read this account's recent automation executions, errors, retries and confirmed results.")
async def radar_automation_activity(s: Session, args: dict) -> dict:
    from app.routers.radar_automations import activity
    return await activity(s.need_manager(), s.db)


@tool("radar_run_automation", "Apply a rule to selected past calls", "Queues matching selected past calls for an active rule. This can change CRM records, but places no phone calls. Preview first and obtain approval before confirmed=true. Does not process all past calls.",
      {"rule_id": ID, "call_ids": {"type": "array", "items": ID, "minItems": 1, "maxItems": 100}, "confirmed": {"type": "boolean"}},
      ["rule_id", "call_ids"], read_only=False, destructive=True, open_world=True)
async def radar_run_automation(s: Session, args: dict) -> dict:
    from app.routers.radar_automations import owned_rule, require, run_selected, RunIn
    from pydantic import ValidationError
    ctx = s.need_manager()
    await require(ctx, s.db)
    key = _uuid(args, "rule_id")
    await owned_rule(s.db, ctx.org.id, key)
    try:
        body = RunIn(call_ids=args.get("call_ids") or [])
    except ValidationError as exc:
        raise ToolError("Select one to 100 valid call IDs.") from exc
    if args.get("confirmed") is not True:
        return {"needs_confirmation": True, "rule_id": str(key), "call_ids": [str(x) for x in body.call_ids], "writes_performed": False}
    return await run_selected(key, body, ctx, s.db)
