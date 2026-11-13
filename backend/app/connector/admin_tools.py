"""
Tools for the BlackSync Admin MCP server (app/routers/admin_mcp.py), a separate connector for platform admins.

It serves these admin tools plus every regular connector tool with an optional account_id, so the admin can do
anything a customer's own connector can do, in any account. admin_use_account sets the default account.
Every call is written to admin_mcp_actions.
"""

from __future__ import annotations

import uuid

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from app.connector.tools import LIMIT, STR, Session, Tool, ToolError, _int, _uuid
from app.models.account import Organization
from app.services.auth import Context


@dataclass
class AdminSession(Session):
    """A regular tool session, aimed at whichever customer account the admin picked."""

    token: Any = None  # the BlackSync Admin connection (OAuthToken)

    def need_account(self) -> Context:
        if self.ctx is None:
            raise ToolError("Pick the customer account first: find it with admin_list_accounts, then call "
                            "admin_use_account, or pass account_id to this tool.")
        return self.ctx

ADMIN_TOOLS: dict[str, Tool] = {}

ACCOUNT_ID = {"type": "string", "description": "The customer account's id (from admin_list_accounts)."}


def admin_tool(name: str, title: str, description: str, properties: dict | None = None,
               required: list[str] | None = None, **flags):
    def wrap(fn):
        schema = {"type": "object", "properties": properties or {}, "additionalProperties": False}
        if required:
            schema["required"] = required
        ADMIN_TOOLS[name] = Tool(name, title, ("Platform admin only. " + description.strip()), schema, fn, **flags)
        return fn
    return wrap


async def _org(s: Session, args: dict, key: str = "account_id") -> Organization:
    org_id = _uuid(args, key)
    org = await s.db.get(Organization, org_id)
    if org is None:
        raise ToolError("No account with that id. Use admin_list_accounts to find it.")
    return org


@admin_tool("admin_list_accounts", "All customer accounts",
            """Every account on BlackSync with its owner, plan, credits, agents, contacts and recent usage.
Search by account name or owner email.""",
            {"query": STR, "limit": LIMIT})
async def admin_list_accounts(s: Session, args: dict) -> dict:
    from app.routers.admin import list_orgs

    rows = (await list_orgs(s.user, s.db, str(args.get("query") or "")))["orgs"]
    limit = _int(args, "limit", 25, 1, 100)
    keep = ("id", "name", "status", "plan", "credits_balance", "unlimited_credits", "industry", "owner", "members",
            "agents", "contacts", "phone_numbers", "usage_30d", "last_call_at", "created_at")
    return {"total": len(rows), "accounts": [{k: r.get(k) for k in keep} for r in rows[:limit]],
            "current_account_id": str(s.token.admin_org_id) if s.token and s.token.admin_org_id else None}


@admin_tool("admin_get_account", "Open a customer account",
            "One account in full: team, usage, agent/campaign/contact counts and the latest credit transactions.",
            {"account_id": ACCOUNT_ID}, ["account_id"])
async def admin_get_account(s: Session, args: dict) -> dict:
    from app.routers.admin import get_org

    org = await _org(s, args)
    data = await get_org(org.id, s.user, s.db)
    data["transactions"] = data.get("transactions", [])[:10]
    return data


@admin_tool("admin_use_account", "Work inside a customer account",
            """Sets the account every other BlackSync tool acts in from now on (agents, contacts, campaigns,
knowledge, calls, CRM, Radar...). Always tell the user which account you switched to before changing anything.""",
            {"account_id": ACCOUNT_ID}, ["account_id"], read_only=False, idempotent=True)
async def admin_use_account(s: Session, args: dict) -> dict:
    org = await _org(s, args)
    s.token.admin_org_id = org.id
    await s.db.commit()
    return {"account": {"id": str(org.id), "name": org.name},
            "note": f"Now working in {org.name}. Every tool acts in this account until you switch again."}


@admin_tool("admin_add_credits", "Add or remove calling credits",
            """Adds calling credits to an account (a negative amount removes them; never below zero). Audited.
Without confirmed=true it only shows what would change: tell the user and repeat with confirmed=true once they agree.""",
            {"account_id": ACCOUNT_ID, "amount": {"type": "integer", "minimum": -1_000_000, "maximum": 1_000_000},
             "note": {"type": "string", "description": "Why (shown in the account's credit history)."},
             "confirmed": {"type": "boolean"}},
            ["account_id", "amount"], read_only=False, destructive=True)
async def admin_add_credits(s: Session, args: dict) -> dict:
    from app.routers.admin import CreditGrant, grant_credits

    org = await _org(s, args)
    try:
        amount = int(args.get("amount"))
    except (TypeError, ValueError):
        raise ToolError("amount must be a whole number of credits.")
    if amount == 0:
        raise ToolError("Enter a non-zero amount.")
    await s.db.refresh(org, ["credits_balance"])
    before = org.credits_balance or 0
    if not args.get("confirmed"):
        return {"needs_confirmation": True, "account": org.name, "balance_now": before,
                "balance_after": max(0, before + amount),
                "note": "Confirm with the user, then repeat with confirmed=true."}
    try:
        out = await grant_credits(org.id, CreditGrant(amount=amount, note=str(args.get("note") or "")[:300]),
                                  s.user, s.db)
    except HTTPException as exc:
        raise ToolError(str(exc.detail))
    return {"account": org.name, "balance": out["balance"]}


@admin_tool("admin_find_phone_number", "Find which account has a phone number",
            "Looks a phone number up across every account: which account it's on, its carrier and whether it's the "
            "default there. Use this before moving a number.",
            {"number": {"type": "string", "description": "The phone number, e.g. +14155550123."}}, ["number"])
async def admin_find_phone_number(s: Session, args: dict) -> dict:
    from app.models.billing import PhoneNumber
    from app.services.contacts import normalize_phone

    number = normalize_phone(str(args.get("number") or ""))
    rows = (await s.db.execute(select(PhoneNumber).where(PhoneNumber.number == number))).scalars().all()
    if not rows:
        raise ToolError(f"{number or 'That number'} isn't on BlackSync.")
    out = []
    for r in rows:
        org = await s.db.get(Organization, r.org_id) if r.org_id else None
        out.append({"number_id": str(r.id), "number": r.number, "status": r.status, "carrier": r.carrier or "twilio",
                    "is_default": bool(r.is_default), "account_id": str(org.id) if org else None,
                    "account": org.name if org else None})
    return {"numbers": out}


@admin_tool("admin_move_phone_number", "Move a phone number to another account",
            """Moves a phone number that's on the wrong account to the right one. The number keeps working (nothing
changes at the carrier). In the old account it's removed from campaigns, rotations, agent caller IDs and inbound
routing; in the new account it's added to the numbers list (and becomes the default if it's that account's first).
Without confirmed=true it only shows what would change: tell the user and repeat with confirmed=true once they agree.""",
            {"number": {"type": "string", "description": "The phone number to move, e.g. +14155550123."},
             "to_account_id": {**ACCOUNT_ID, "description": "The account that should have the number."},
             "confirmed": {"type": "boolean"}},
            ["number", "to_account_id"], read_only=False, destructive=True)
async def admin_move_phone_number(s: Session, args: dict) -> dict:
    from app.models.billing import BillingAudit, PhoneNumber
    from app.services import telephony
    from app.services.contacts import normalize_phone

    number = normalize_phone(str(args.get("number") or ""))
    row = (await s.db.execute(select(PhoneNumber).where(PhoneNumber.number == number,
                                                        PhoneNumber.status == "active"))).scalar_one_or_none()
    if row is None:
        raise ToolError(f"{number or 'That number'} isn't an active number on any account.")
    target = await _org(s, args, "to_account_id")
    source = await s.db.get(Organization, row.org_id) if row.org_id else None
    if source is not None and source.id == target.id:
        raise ToolError(f"{number} is already on {target.name}.")
    if not args.get("confirmed"):
        return {"needs_confirmation": True, "number": number, "from_account": source.name if source else None,
                "to_account": target.name, "was_default_on_old_account": bool(row.is_default),
                "note": "Confirm with the user, then repeat with confirmed=true."}
    try:
        await telephony.move_number(s.db, row, target.id)
    except telephony.TelephonyError as exc:
        raise ToolError(str(exc))
    s.db.add(BillingAudit(admin_id=s.user.id, org_id=target.id, target="phone_number",
                          previous=(source.name if source else "none")[:64], adjustment="moved", new=target.name[:64],
                          reason=f"{number} moved from {source.name if source else 'no account'} to {target.name}"))
    await s.db.commit()
    from app.routers.phone_numbers import _sync_billing

    for org_id in filter(None, {source.id if source else None, target.id}):
        await _sync_billing(s.db, org_id)  # extra-number charges follow the number
    return {"number": number, "from_account": source.name if source else None, "to_account": target.name,
            "is_default_on_new_account": bool(row.is_default)}


@admin_tool("admin_activity", "Admin action log",
            "The latest tool calls made in admin mode (any connection), newest first. Optionally one account only.",
            {"account_id": {**ACCOUNT_ID, "description": "Only this account (optional)."}, "limit": LIMIT})
async def admin_activity(s: Session, args: dict) -> dict:
    from app.models.oauth import AdminMcpAction

    q = select(AdminMcpAction).order_by(AdminMcpAction.created_at.desc()).limit(_int(args, "limit", 30, 1, 100))
    org_id = _uuid(args, "account_id", False)
    if org_id:
        q = q.where(AdminMcpAction.org_id == org_id)
    rows = (await s.db.execute(q)).scalars().all()
    return {"actions": [{"at": r.created_at.isoformat() if r.created_at else None, "account": r.org_name or None,
                         "tool": r.tool, "changed_something": not r.read_only, "ok": r.ok,
                         "error": r.error or None} for r in rows]}


def with_account_id(t: Tool) -> dict:
    """A regular tool's descriptor with the optional account_id an admin can pass to aim it at one account."""
    d = t.descriptor()
    schema = {**d["inputSchema"], "properties": {
        **d["inputSchema"].get("properties", {}),
        "account_id": {"type": "string", "description": "Admin mode: the customer account to act in (defaults to "
                                                          "the one picked with admin_use_account)."}}}
    return {**d, "inputSchema": schema}


def parse_account_id(raw) -> uuid.UUID | None:
    if raw in (None, ""):
        return None
    try:
        return uuid.UUID(str(raw).split(":")[-1])
    except ValueError:
        raise ToolError(f"account_id isn't a valid id: {raw}")


@admin_tool("admin_correct_call", "Correct a call's transcript or recording",
            """Fix a call whose transcript was lost or garbled (for example a call cut off by a restart): replace
its transcript with what was actually said, optionally trim the recording to the first keep_seconds (the untouched
original is kept next to it), then re-run the AI analysis so the summary, result and extracted details update.
The original transcript is saved on the call. Without confirmed=true it only shows what would change.""",
            {"account_id": ACCOUNT_ID, "call_id": {"type": "string"},
             "transcript": {"type": "array", "items": {"type": "object", "properties": {
                 "role": {"type": "string", "enum": ["assistant", "user"]}, "text": {"type": "string"}},
                 "required": ["role", "text"]}, "description": "assistant = the agent, user = the contact."},
             "keep_seconds": {"type": "number", "description": "Trim the recording to this many seconds (optional)."},
             "confirmed": {"type": "boolean"}},
            ["account_id", "call_id"], read_only=False, destructive=True)
async def admin_correct_call(s: Session, args: dict) -> dict:
    from datetime import datetime, timezone

    from app.models.call_log import CallLog
    from app.services import recordings

    org = await _org(s, args)
    call = await s.db.get(CallLog, _uuid(args, "call_id"))
    if call is None or call.org_id != org.id:
        raise ToolError("No call with that id in this account.")
    turns = [{"role": t["role"], "text": " ".join(str(t.get("text") or "").split())[:2000]}
             for t in (args.get("transcript") or []) if isinstance(t, dict) and t.get("role") in ("assistant", "user")]
    turns = [t for t in turns if t["text"]]
    keep = args.get("keep_seconds")
    if keep is not None:
        try:
            keep = float(keep)
        except (TypeError, ValueError):
            raise ToolError("keep_seconds must be a number.")
        if not call.recording_key:
            raise ToolError("This call has no stored recording to trim.")
    if not turns and keep is None:
        raise ToolError("Give a transcript, keep_seconds, or both.")
    if not args.get("confirmed"):
        return {"needs_confirmation": True, "account": org.name, "call_id": str(call.id),
                "transcript_turns_now": len(call.transcript or []), "transcript_turns_after": len(turns) or None,
                "trim_recording_to_seconds": keep,
                "note": "Confirm with the user, then repeat with confirmed=true."}
    from app.services.call_corrections import apply_correction

    await apply_correction(s.db, call, turns, keep, by=getattr(s.user, "email", None))
    return {"account": org.name, "call_id": str(call.id), "outcome": call.outcome, "summary": call.summary,
            "extracted": {k: v for k, v in (call.extracted_data or {}).items() if not k.startswith("_")},
            "recording_trimmed_to": keep}


@admin_tool("admin_check_calendar", "Check an agent's calendar booking setup",
            "Read-only check of an agent's Cal.com connection: whether its key and event type work, what the event "
            "type requires to book (booking questions, attendee phone, location), and the calendar's own error "
            "messages from the agent's recent booking attempts. Never creates a booking.",
            {"agent_id": {"type": "string", "description": "The agent's id."}}, ["agent_id"])
async def admin_check_calendar(s: Session, args: dict) -> dict:
    import uuid as _uuid

    from app.models.agent import Agent
    from app.models.call_log import CallLog
    from app.services import calendar
    from app.services.secret_store import decrypt_value

    try:
        agent = await s.db.get(Agent, _uuid.UUID(str(args.get("agent_id") or "")))
    except ValueError:
        agent = None
    if agent is None:
        raise ToolError("No agent with that id.")
    provider = agent.calendar_provider or "calcom"
    out: dict = {"agent": agent.name, "account_id": str(agent.org_id), "booking_enabled": bool(agent.enable_booking),
                 "provider": provider, "event_type_id": agent.calcom_event_type_id or None,
                 "key_saved": bool(agent.calcom_api_key_enc), "calendar_timezone": agent.calendar_timezone or None}
    if provider == "calcom":
        out["event_type"] = await calendar.event_type_check(decrypt_value(agent.calcom_api_key_enc),
                                                            agent.calcom_event_type_id)
    rows = (await s.db.execute(select(CallLog.id, CallLog.started_at, CallLog.outcome, CallLog.transcript)
                               .where(CallLog.agent_id == agent.id).order_by(CallLog.started_at.desc()).limit(40))).all()
    attempts = []
    for cid, started, outcome, transcript in rows:
        for t in transcript or []:
            if t.get("role") == "tool" and t.get("tool") == "book_appointment":
                result = t.get("result") or {}
                attempts.append({"call_id": str(cid), "at": started.isoformat() if started else None,
                                 "call_outcome": outcome, "success": result.get("success") is not False,
                                 "result": result.get("output")})
    out["recent_booking_attempts"] = attempts[:15]
    return out
