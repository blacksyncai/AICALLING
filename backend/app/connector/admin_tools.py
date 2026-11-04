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
