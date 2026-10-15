"""
The BlackSync connector's MCP endpoint (Streamable HTTP, stateless JSON responses): POST /api/mcp.

Every request needs an OAuth access token from /api/oauth (see app/routers/oauth.py); without one the response is
401 with a WWW-Authenticate challenge that points the assistant at the sign-in flow. Tools live in
app/connector/tools.py.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select

from app.connector.tools import TOOLS, Session, ToolError
from app.database import AsyncSessionLocal
from app.models.account import Membership, Organization, User
from app.routers import oauth
from app.services.auth import Context, resolve_org

log = structlog.get_logger(__name__)
router = APIRouter(tags=["mcp"])

SERVER_INFO = {"name": "blacksync", "title": "BlackSync AI", "version": "1.0.0"}
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "BlackSync AI runs AI phone agents that call leads and answer calls for businesses. Use get_started first: it "
    "shows the account, a setup checklist and the next step. To onboard a new business: create_account (if they "
    "have none), scan_website or add_knowledge, build_agent (then poll get_agent_build_status), a test with "
    "call_with_agent to their own phone, launch_agent, add_contacts, create_campaign and start_campaign. Ask before "
    "anything that places calls or changes the account, and confirm phone numbers before calling them. Never invent "
    "results: read calls with list_calls / get_call."
)
RATE_LIMIT = 120  # tool calls per connection per minute
_recent: dict[str, deque] = defaultdict(deque)


def _challenge(error: str = "", description: str = "") -> str:
    parts = [f'resource_metadata="{oauth.resource_metadata_url()}"', f'scope="{oauth.SCOPE}"']
    if error:
        parts.insert(0, f'error="{error}"')
        parts.insert(1, f'error_description="{description}"')
    return "Bearer " + ", ".join(parts)


def _unauthorized(error: str = "", description: str = "") -> Response:
    return JSONResponse({"error": error or "unauthorized", "error_description": description or "Sign in to BlackSync."},
                        status_code=401, headers={"WWW-Authenticate": _challenge(error, description)})


def _result(id_, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _error(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


async def _context(db, token) -> tuple[User | None, Context | None]:
    user = await db.get(User, token.user_id)
    if user is None:
        return None, None
    if token.org_id:
        m = (await db.execute(select(Membership).where(
            Membership.user_id == user.id, Membership.org_id == token.org_id))).scalar_one_or_none()
        org = await db.get(Organization, token.org_id) if m else None
        if org is None:
            return user, None
        return user, Context(user=user, org=org, role=m.role)
    # Connected before they had an account (or chose none): use their account once they have one.
    org, role = await resolve_org(db, user)
    if org is not None and role == "superadmin":
        return user, None
    return user, Context(user=user, org=org, role=role) if org else None


def _content(data: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str, ensure_ascii=False)}],
            "structuredContent": data}


async def _call_tool(db, token, params: dict) -> dict:
    name = params.get("name")
    args = params.get("arguments") or {}
    t = TOOLS.get(name)
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

    user, ctx = await _context(db, token)
    if user is None:
        return {**_content({"error": "This connection is no longer valid."}), "isError": True,
                "_meta": {"mcp/www_authenticate": [_challenge("invalid_token", "Reconnect BlackSync.")]}}
    session = Session(user=user, db=db, ctx=ctx)
    try:
        data = await t.handler(session, args)
        log.info("mcp_tool", tool=name, org_id=str(ctx.org.id) if ctx else None, client=token.client_name)
        return _content(data)
    except ToolError as exc:
        await db.rollback()
        return {**_content({"error": str(exc)}), "isError": True}
    except HTTPException as exc:
        await db.rollback()
        detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, default=str)
        return {**_content({"error": detail}), "isError": True}
    except Exception as exc:
        await db.rollback()
        log.error("mcp_tool_failed", tool=name, error=str(exc)[:300])
        return {**_content({"error": "Something went wrong on BlackSync's side. Please try again."}), "isError": True}


async def _handle(db, token, msg: dict) -> dict | None:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid request")
    method, id_, params = msg["method"], msg.get("id"), msg.get("params") or {}
    if "id" not in msg:  # notification (initialized, cancelled, ...)
        return None
    if method == "initialize":
        asked = params.get("protocolVersion")
        return _result(id_, {
            "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return _result(id_, {})
    if method == "tools/list":
        return _result(id_, {"tools": [t.descriptor() for t in TOOLS.values()]})
    if method == "tools/call":
        try:
            return _result(id_, await _call_tool(db, token, params))
        except KeyError:
            return _error(id_, -32602, f"Unknown tool: {params.get('name')}")
    if method in ("resources/list", "resources/templates/list", "prompts/list"):
        key = {"resources/list": "resources", "resources/templates/list": "resourceTemplates",
               "prompts/list": "prompts"}[method]
        return _result(id_, {key: []})
    return _error(id_, -32601, f"Method not found: {method}")


@router.post("/api/mcp")
async def mcp(request: Request):
    auth = request.headers.get("authorization", "")
    raw = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    try:
        body = json.loads(await request.body() or b"null")
    except ValueError:
        return JSONResponse(_error(None, -32700, "Parse error"), status_code=400)
    async with AsyncSessionLocal() as db:
        token = await oauth.token_for(db, raw)
        if token is None:
            return _unauthorized("invalid_token", "The access token is missing, expired or revoked.") if raw \
                else _unauthorized()
        token.last_used_at = datetime.now(timezone.utc)
        await db.commit()
        if isinstance(body, list):
            replies = [r for r in [await _handle(db, token, m) for m in body] if r is not None]
            return JSONResponse(replies) if replies else Response(status_code=202)
        reply = await _handle(db, token, body)
    return JSONResponse(reply) if reply is not None else Response(status_code=202)


@router.get("/api/mcp")
@router.delete("/api/mcp")
async def mcp_other():
    # Stateless server: no server-initiated stream and no sessions to end.
    return Response(status_code=405, headers={"Allow": "POST"})
