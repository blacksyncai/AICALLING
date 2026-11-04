"""
BlackSync Admin: a separate MCP server for platform admins (POST /api/admin-mcp).

Connected from ChatGPT or Claude as its own connector, set up from the admin portal (Admin > AI access). Only a
super-admin can approve it, with the admin portal unlocked, and its tokens only work here (the customer connector's
tokens are refused, and these are refused on /api/mcp). It can act in any customer account and logs every call.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from app.connector.admin_tools import ADMIN_TOOLS, AdminSession, parse_account_id, with_account_id
from app.connector.tools import TOOLS, ToolError
from app.database import AsyncSessionLocal
from app.models.account import Organization, User
from app.models.oauth import AdminMcpAction
from app.routers import oauth
from app.routers.mcp import PROTOCOL_VERSIONS, _content, _error, _result
from app.services.auth import Context

log = structlog.get_logger(__name__)
router = APIRouter(tags=["admin-mcp"])

SERVER_INFO = {"name": "blacksync-admin", "title": "BlackSync Admin", "version": "1.0.0",
               "websiteUrl": "https://blacksync.si",
               "icons": [{"src": "https://blacksync.si/blacksync-icon.png", "mimeType": "image/png", "sizes": ["512x512"]}]}
INSTRUCTIONS = (
    "BlackSync Admin manages every customer account on BlackSync. Find accounts with admin_list_accounts and open "
    "one with admin_get_account. Before changing anything, call admin_use_account so every other tool acts in that "
    "account (or pass account_id to a single call), and tell the user which account you are working in. Every "
    "regular BlackSync tool works here: agents (get_script_guide, create_agent, update_agent, launch_agent), "
    "knowledge (scan_website, add_knowledge), contacts (add_contacts, up to 200 per call), campaigns, calls, CRM "
    "and Radar. Ask before anything that places calls, spends money or changes an account, and confirm phone numbers "
    "before calling. Never invent results. Every call made here is logged."
)
RATE_LIMIT = 180
_recent: dict[str, deque] = defaultdict(deque)


def _challenge(error: str = "", description: str = "") -> str:
    parts = [f'resource_metadata="{oauth.admin_resource_metadata_url()}"', f'scope="{oauth.SCOPE}"']
    if error:
        parts = [f'error="{error}"', f'error_description="{description}"', *parts]
    return "Bearer " + ", ".join(parts)


def _unauthorized(error: str = "", description: str = "") -> Response:
    return JSONResponse({"error": error or "unauthorized", "error_description": description or "Sign in to BlackSync."},
                        status_code=401, headers={"WWW-Authenticate": _challenge(error, description)})


async def _record(db, token, user, org, name: str, args: dict, read_only: bool, error: str = "") -> None:
    try:
        db.add(AdminMcpAction(token_id=token.id, admin_id=user.id, org_id=org.id if org else None,
                              org_name=org.name if org else "", tool=name, read_only=read_only,
                              arguments=json.dumps(args, default=str)[:4000], ok=not error, error=error[:1000]))
        await db.commit()
    except Exception as exc:  # the log row must never break the tool call, but it must be noticed
        await db.rollback()
        log.error("admin_mcp_audit_failed", tool=name, error=str(exc)[:300])


async def _call_tool(db, token, user: User, params: dict) -> dict:
    name = params.get("name")
    args = params.get("arguments") or {}
    t = ADMIN_TOOLS.get(name) or TOOLS.get(name)
    if t is None:
        raise KeyError(name)
    if not isinstance(args, dict):
        return {**_content({"error": "arguments must be an object"}), "isError": True}
    window = _recent[str(token.id)]
    now = time.monotonic()
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= RATE_LIMIT:
        return {**_content({"error": "Too many requests. Wait a minute and try again."}), "isError": True}
    window.append(now)

    args = dict(args)
    org = None
    try:
        if name in ADMIN_TOOLS:
            if args.get("account_id"):
                org = await db.get(Organization, parse_account_id(args["account_id"]))
        else:
            org_id = parse_account_id(args.pop("account_id", None)) or token.admin_org_id
            org = await db.get(Organization, org_id) if org_id else None
            if org_id and org is None:
                raise ToolError("No account with that id. Use admin_list_accounts to find it.")
        ctx = Context(user=user, org=org, role="superadmin") if org else None
        data = await t.handler(AdminSession(user=user, db=db, ctx=ctx, token=token), args)
    except (ToolError, HTTPException) as exc:
        await db.rollback()
        msg = str(exc) if isinstance(exc, ToolError) else (
            exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, default=str))
        await _record(db, token, user, org, name, args, t.read_only, msg or "error")
        return {**_content({"error": msg}), "isError": True}
    except Exception as exc:
        await db.rollback()
        log.error("admin_mcp_tool_failed", tool=name, error=str(exc)[:300])
        await _record(db, token, user, org, name, args, t.read_only, "internal error")
        return {**_content({"error": "Something went wrong on BlackSync's side. Please try again."}), "isError": True}
    if name == "admin_use_account":
        org = await db.get(Organization, token.admin_org_id) if token.admin_org_id else None
    await _record(db, token, user, org, name, args, t.read_only)
    log.info("admin_mcp_tool", tool=name, org_id=str(org.id) if org else None, client=token.client_name)
    if org is not None and isinstance(data, dict):
        data = {**data, "acting_account": {"id": str(org.id), "name": org.name}}
    return _content(data)


def _tools() -> list[dict]:
    return [t.descriptor() for t in ADMIN_TOOLS.values()] + [with_account_id(t) for t in TOOLS.values()]


async def _handle(db, token, user: User, msg: dict) -> dict | None:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid request")
    method, id_, params = msg["method"], msg.get("id"), msg.get("params") or {}
    if "id" not in msg:
        return None
    if method == "initialize":
        asked = params.get("protocolVersion")
        return _result(id_, {"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                             "capabilities": {"tools": {"listChanged": False}},
                             "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS})
    if method == "ping":
        return _result(id_, {})
    if method == "tools/list":
        return _result(id_, {"tools": _tools()})
    if method == "tools/call":
        try:
            return _result(id_, await _call_tool(db, token, user, params))
        except KeyError:
            return _error(id_, -32602, f"Unknown tool: {params.get('name')}")
    if method in ("resources/list", "resources/templates/list", "prompts/list"):
        key = {"resources/list": "resources", "resources/templates/list": "resourceTemplates",
               "prompts/list": "prompts"}[method]
        return _result(id_, {key: []})
    return _error(id_, -32601, f"Method not found: {method}")


@router.post("/api/admin-mcp")
async def admin_mcp(request: Request):
    auth = request.headers.get("authorization", "")
    raw = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    try:
        body = json.loads(await request.body() or b"null")
    except ValueError:
        return JSONResponse(_error(None, -32700, "Parse error"), status_code=400)
    async with AsyncSessionLocal() as db:
        token = await oauth.token_for(db, raw, admin=True)
        if token is None:
            return _unauthorized("invalid_token", "The access token is missing, expired or revoked.") if raw \
                else _unauthorized()
        user = await db.get(User, token.user_id)
        if user is None or not user.is_superadmin:
            return _unauthorized("invalid_token", "BlackSync Admin is only for BlackSync platform admins.")
        token.last_used_at = datetime.now(timezone.utc)
        await db.commit()
        if isinstance(body, list):
            replies = [r for r in [await _handle(db, token, user, m) for m in body] if r is not None]
            return JSONResponse(replies) if replies else Response(status_code=202)
        reply = await _handle(db, token, user, body)
    return JSONResponse(reply) if reply is not None else Response(status_code=202)


@router.get("/api/admin-mcp")
@router.delete("/api/admin-mcp")
async def admin_mcp_other():
    return Response(status_code=405, headers={"Allow": "POST"})
