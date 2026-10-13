"""
Support: the in-app widget (chat with AI or a person, tickets, help center) and the BlackSync staff
inbox. Customers only ever see their own chats and their organization's tickets; the staff routes
need a platform admin with the admin portal unlocked (account owners are never staff).

Real time: long polling — the client asks for messages after the last sequence number it has, and
the request waits (up to ~25 s) until something new arrives. Works with the normal auth headers, on
any number of API instances (it re-checks the database), with no extra service.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import timedelta

import structlog
from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.database import AsyncSessionLocal
from app.models.account import Organization, User
from app.models.support import (
    KB_CATEGORIES, TICKET_CATEGORIES, TICKET_PRIORITIES, TICKET_STATUSES, KbArticle, SupportAiUsage, SupportAttachment,
    SupportConversation, SupportMessage, SupportNotification, SupportTicket, TicketReply,
)
from app.services.auth import AdminDep, CtxDep, DbDep
from app.services.support import ai, core
from app.services.support.core import iso, now

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/support", tags=["support"])
admin_router = APIRouter(prefix="/api/admin/support", tags=["admin"])

MAX_BODY = 4000
MAX_ATTACH = 3
MAX_FILE = 5 * 1024 * 1024
POLL_MAX = 25.0
_IMAGE_SIGS = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg", b"GIF87a": "image/gif", b"GIF89a": "image/gif"}


# ── Serialization ─────────────────────────────────────────────────────────────


async def _names(db, ids) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {u.id: u for u in rows}


async def _att_list(db, ids) -> list[dict]:
    if not ids:
        return []
    uids = []
    for i in ids:
        try:
            uids.append(uuid.UUID(str(i)))
        except ValueError:
            continue
    rows = (await db.execute(select(SupportAttachment.id, SupportAttachment.filename, SupportAttachment.content_type,
                                    SupportAttachment.size).where(SupportAttachment.id.in_(uids)))).all()
    return [{"id": str(r[0]), "filename": r[1], "content_type": r[2], "size": r[3]} for r in rows]


async def _messages_out(db, msgs: list[SupportMessage], staff: bool) -> list[dict]:
    users = await _names(db, [m.author_id for m in msgs])
    out = []
    for m in msgs:
        u = users.get(m.author_id)
        name = None
        if m.sender == "agent":
            own = (u.full_name or u.email) if u else "BlackSync team"
            if staff:
                name = f"{m.display_name} ({own})" if m.display_name else own
            else:
                name = m.display_name or ((u.first_name if u else None) or "BlackSync team")
        elif m.sender == "customer" and u:
            name = u.full_name or u.email
        out.append({"id": str(m.id), "seq": m.seq, "sender": m.sender, "author_name": name, "body": m.body,
                    "internal": m.internal, "attachments": await _att_list(db, m.attachments or []),
                    "meta": m.meta or {}, "client_id": m.client_id, "created_at": iso(m.created_at)})
    return out


async def _conv_out(db, c: SupportConversation, staff: bool = False) -> dict:
    users = await _names(db, [c.user_id, c.assigned_to])
    agent = users.get(c.assigned_to)
    out = {"id": str(c.id), "mode": c.mode, "subject": c.subject, "last_seq": c.last_seq,
           "last_message_at": iso(c.last_message_at), "last_preview": c.last_preview,
           "ticket_id": str(c.ticket_id) if c.ticket_id else None, "created_at": iso(c.created_at),
           "typing": core.typing(c.id),
           "agent_name": (c.agent_alias or ((agent.first_name or "BlackSync team") if agent else None)) if not staff else
                         ((agent.full_name or agent.email) if agent else None),
           "agent_alias": c.agent_alias if staff else None}
    if staff:
        cust = users.get(c.user_id)
        org = await db.get(Organization, c.org_id)
        out.update(org_id=str(c.org_id), org_name=org.name if org else "", assigned_to=str(c.assigned_to) if c.assigned_to else None,
                   customer={"id": str(cust.id), "name": cust.full_name, "email": cust.email} if cust else None,
                   unread=c.mode != "ai_active" and c.last_seq > c.staff_read_seq)
    else:
        out["unread"] = c.last_seq > c.customer_read_seq
    return out


def _ticket_out(t: SupportTicket, users: dict | None = None, org: Organization | None = None, staff: bool = False) -> dict:
    users = users or {}
    cust, agent = users.get(t.user_id), users.get(t.assigned_to)
    out = {"id": str(t.id), "number": t.number, "subject": t.subject, "description": t.description,
           "category": t.category, "priority": t.priority, "status": t.status,
           "conversation_id": str(t.conversation_id) if t.conversation_id else None,
           "assigned_name": ((agent.first_name or "BlackSync team") if agent and not staff else (agent.full_name or agent.email) if agent else None),
           "last_reply_by": t.last_reply_by, "last_reply_at": iso(t.last_reply_at),
           "created_at": iso(t.created_at), "updated_at": iso(t.updated_at),
           "customer_name": (cust.full_name or cust.email) if cust else None,
           "unread": bool(t.last_reply_by == "staff" and (not t.customer_read_at or core.aware(t.customer_read_at) < core.aware(t.last_reply_at)))}
    if staff:
        out.update(org_id=str(t.org_id), org_name=org.name if org else "", assigned_to=str(t.assigned_to) if t.assigned_to else None,
                   customer_email=cust.email if cust else None)
    return out


async def _replies_out(db, t: SupportTicket, staff: bool) -> list[dict]:
    stmt = select(TicketReply).where(TicketReply.ticket_id == t.id)
    if not staff:
        stmt = stmt.where(TicketReply.internal.is_(False))
    rows = (await db.execute(stmt.order_by(TicketReply.created_at))).scalars().all()
    users = await _names(db, [r.author_id for r in rows])
    out = []
    for r in rows:
        u = users.get(r.author_id)
        own = (u.full_name or u.email) if u else None
        if r.author_kind == "system":
            name = "BlackSync"
        elif r.author_kind == "staff" and not staff:
            name = r.display_name or ((u.first_name if u else None) or "BlackSync team")
        elif r.author_kind == "staff":
            name = f"{r.display_name} ({own})" if r.display_name else own
        else:
            name = own
        out.append({"id": str(r.id), "author_kind": r.author_kind, "author_name": name, "body": r.body,
                    "internal": r.internal, "attachments": await _att_list(db, r.attachments or []), "created_at": iso(r.created_at)})
    return out


# ── Access helpers ────────────────────────────────────────────────────────────


async def _my_conv(db, ctx, conv_id: uuid.UUID) -> SupportConversation:
    c = await db.get(SupportConversation, conv_id)
    if not c or c.org_id != ctx.org.id or c.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return c


async def _my_ticket(db, ctx, ticket_id: uuid.UUID) -> SupportTicket:
    t = await db.get(SupportTicket, ticket_id)
    if not t or t.org_id != ctx.org.id or (t.user_id != ctx.user.id and not ctx.can_manage):
        raise HTTPException(status_code=404, detail="Ticket not found")
    return t


async def _claim_attachments(db, ids: list[str], uploader: User, *, conversation_id=None, ticket_id=None) -> list[str]:
    """Only the uploader's own, not-yet-used files can be attached."""
    if not ids:
        return []
    if len(ids) > MAX_ATTACH:
        raise HTTPException(status_code=400, detail=f"Attach up to {MAX_ATTACH} screenshots.")
    out = []
    for raw in ids:
        try:
            att = await db.get(SupportAttachment, uuid.UUID(str(raw)))
        except ValueError:
            att = None
        if not att or att.uploader_id != uploader.id or att.conversation_id or att.ticket_id:
            raise HTTPException(status_code=400, detail="That screenshot can't be attached.")
        att.conversation_id, att.ticket_id = conversation_id, ticket_id
        out.append(str(att.id))
    return out


def _clean_body(text: str) -> str:
    text = (text or "").replace("\x00", "").strip()
    if len(text) > MAX_BODY:
        raise HTTPException(status_code=400, detail=f"Messages can be up to {MAX_BODY} characters.")
    return text


# ── AI replies ────────────────────────────────────────────────────────────────


async def _ai_events(conv_id: uuid.UUID, user_id: uuid.UUID):
    """Generate the AI reply for the newest customer message. Yields event dicts."""
    async with AsyncSessionLocal() as db:
        conv = await db.get(SupportConversation, conv_id)
        if conv is None or conv.mode != "ai_active":
            return
        if not ai.available():
            msg = await core.add_message(db, conv, sender="system", body=(
                "AI support isn't available right now. You can talk to a person or create a ticket and we'll follow up."),
                meta={"offer_escalation": True, "offer_ticket": True})
            if msg:
                yield {"type": "message", "message": (await _messages_out(db, [msg], False))[0]}
            return
        if await ai.recent_usage(db, user_id) >= ai.settings.support_ai_hourly_limit:
            msg = await core.add_message(db, conv, sender="system", body=(
                "You've reached the limit for AI answers this hour. You can still talk to a person or create a ticket."),
                meta={"offer_escalation": True, "offer_ticket": True})
            if msg:
                yield {"type": "message", "message": (await _messages_out(db, [msg], False))[0]}
            return
        epoch = conv.epoch
        core.set_typing(conv.id, "ai")
        messages, arts = await ai.build_messages(db, conv)
        text, ok, err = "", True, None
        try:
            n = 0
            async for delta in ai.stream_reply(messages):
                text += delta
                n += 1
                yield {"type": "delta", "text": delta}
                if n % 15 == 0:  # a person took over mid-reply: stop now
                    await db.refresh(conv)
                    if conv.mode != "ai_active" or conv.epoch != epoch:
                        break
        except Exception as exc:
            ok, err = False, str(exc)[:200]
            log.warning("support_ai_failed", conversation_id=str(conv.id), error=err)
        finally:
            core.set_typing(conv.id, None)
        db.add(SupportAiUsage(org_id=conv.org_id, user_id=user_id, conversation_id=conv.id, model=ai.model(),
                              prompt_tokens=sum(len(m["content"]) for m in messages) // 4,
                              completion_tokens=len(text) // 4, ok=ok))
        await db.commit()
        if not ok or not text.strip():
            msg = await core.add_message(db, conv, sender="system", ai_epoch=epoch, body=(
                "Sorry — I couldn't answer that just now. You can talk to a person or create a ticket and we'll follow up."),
                meta={"offer_escalation": True, "offer_ticket": True})
        else:
            body, offer = ai.clean(text)
            meta = {"articles": [{"slug": a.slug, "title": a.title} for a in arts]}
            if offer:
                meta["offer_escalation"] = True
            msg = await core.add_message(db, conv, sender="ai", body=body, meta=meta, ai_epoch=epoch)
        if msg is None:
            yield {"type": "dropped"}  # a person took over while the AI was writing
            return
        yield {"type": "message", "message": (await _messages_out(db, [msg], False))[0]}


# ── Customer: state, conversations ────────────────────────────────────────────


@router.get("/state")
async def state(ctx: CtxDep, db: DbDep):
    convs = (await db.execute(select(SupportConversation).where(
        SupportConversation.org_id == ctx.org.id, SupportConversation.user_id == ctx.user.id))).scalars().all()
    tickets = (await db.execute(select(SupportTicket).where(
        SupportTicket.org_id == ctx.org.id, SupportTicket.user_id == ctx.user.id,
        SupportTicket.last_reply_by == "staff"))).scalars().all()
    unread_t = sum(1 for t in tickets if _ticket_out(t)["unread"])
    return {"unread": sum(1 for c in convs if c.last_seq > c.customer_read_seq) + unread_t,
            "staff_online": await core.staff_online(db), "ai_available": ai.available(),
            "user": {"name": ctx.user.full_name, "email": ctx.user.email}, "org": ctx.org.name}


@router.get("/conversations")
async def my_conversations(ctx: CtxDep, db: DbDep, limit: int = 30):
    rows = (await db.execute(select(SupportConversation).where(
        SupportConversation.org_id == ctx.org.id, SupportConversation.user_id == ctx.user.id)
        .order_by(SupportConversation.last_message_at.desc()).limit(min(limit, 100)))).scalars().all()
    return {"conversations": [await _conv_out(db, c) for c in rows]}


class StartIn(BaseModel):
    message: str = Field(default="", max_length=MAX_BODY)
    client_id: str | None = Field(default=None, max_length=64)


@router.post("/conversations", status_code=201)
async def start_conversation(body: StartIn, ctx: CtxDep, db: DbDep):
    c = SupportConversation(org_id=ctx.org.id, user_id=ctx.user.id, subject=core.preview(body.message)[:200])
    db.add(c)
    await db.commit()
    await db.refresh(c)
    await core.add_message(db, c, sender="system", body="Hey! Welcome to BlackSync Support. How can we help you today?")
    return await _conv_out(db, c)


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    c = await _my_conv(db, ctx, conv_id)
    msgs = (await db.execute(select(SupportMessage).where(
        SupportMessage.conversation_id == c.id, SupportMessage.internal.is_(False))
        .order_by(SupportMessage.seq.desc()).limit(200))).scalars().all()
    return {"conversation": await _conv_out(db, c), "messages": await _messages_out(db, list(reversed(msgs)), False)}


async def _poll(db, c: SupportConversation, after: int, wait: float, staff: bool):
    deadline = time.monotonic() + max(0.0, min(wait, POLL_MAX))
    seen_typing = core.typing(c.id)
    while True:
        await db.refresh(c)
        stmt = select(SupportMessage).where(SupportMessage.conversation_id == c.id, SupportMessage.seq > after)
        if not staff:
            stmt = stmt.where(SupportMessage.internal.is_(False))
        msgs = (await db.execute(stmt.order_by(SupportMessage.seq).limit(100))).scalars().all()
        if msgs or time.monotonic() >= deadline or core.typing(c.id) != seen_typing:
            return {"conversation": await _conv_out(db, c, staff=staff), "messages": await _messages_out(db, msgs, staff)}
        await db.commit()  # don't hold a transaction open while waiting
        await core.wait_for(f"conv:{c.id}", min(2.0, max(0.1, deadline - time.monotonic())))


@router.get("/conversations/{conv_id}/poll")
async def poll_conversation(conv_id: uuid.UUID, ctx: CtxDep, db: DbDep, after: int = 0, wait: float = 25):
    c = await _my_conv(db, ctx, conv_id)
    return await _poll(db, c, after, wait, staff=False)


class MessageIn(BaseModel):
    body: str = Field(default="", max_length=MAX_BODY)
    client_id: str | None = Field(default=None, max_length=64)
    attachments: list[str] = Field(default_factory=list)


@router.post("/conversations/{conv_id}/messages")
async def send_message(conv_id: uuid.UUID, body: MessageIn, ctx: CtxDep, db: DbDep, stream: bool = False):
    c = await _my_conv(db, ctx, conv_id)
    text = _clean_body(body.body)
    if not text and not body.attachments:
        raise HTTPException(status_code=400, detail="Type a message.")
    if c.mode == "resolved":
        await core.set_mode(db, c, "ai_active")  # writing again reopens the chat
    atts = await _claim_attachments(db, body.attachments, ctx.user, conversation_id=c.id)
    if not c.subject:
        c.subject = core.preview(text)[:200]
    msg = await core.add_message(db, c, sender="customer", body=text, author_id=ctx.user.id, attachments=atts,
                                 client_id=body.client_id)
    if msg is None:
        raise HTTPException(status_code=409, detail="Couldn't send — try again.")
    core.set_typing(c.id, None)
    first = (await _messages_out(db, [msg], False))[0]
    if c.mode in ("waiting_for_human", "human_active"):
        await core.notify(db, "customer_reply", f"{ctx.user.full_name or ctx.user.email} ({ctx.org.name}): {core.preview(text)}",
                          org_id=ctx.org.id, conversation_id=c.id, dedupe_key=f"reply:{c.id}", window=timedelta(minutes=5))
    if c.mode != "ai_active":
        return {"messages": [first]}
    if not stream:
        out = [first]
        async for ev in _ai_events(c.id, ctx.user.id):
            if ev["type"] == "message":
                out.append(ev["message"])
        return {"messages": out}

    async def gen():
        yield json.dumps({"type": "message", "message": first}) + "\n"
        async for ev in _ai_events(c.id, ctx.user.id):
            yield json.dumps(ev) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/conversations/{conv_id}/escalate")
async def escalate(conv_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    c = await _my_conv(db, ctx, conv_id)
    if c.mode == "resolved":
        await core.set_mode(db, c, "ai_active")
    await core.escalate(db, c, ctx.org, ctx.user)
    return await _conv_out(db, c)


class ReadIn(BaseModel):
    seq: int = Field(ge=0)


@router.post("/conversations/{conv_id}/read")
async def mark_read(conv_id: uuid.UUID, body: ReadIn, ctx: CtxDep, db: DbDep):
    c = await _my_conv(db, ctx, conv_id)
    c.customer_read_seq = max(c.customer_read_seq, min(body.seq, c.last_seq))
    await db.commit()
    return {"ok": True}


@router.post("/conversations/{conv_id}/typing")
async def customer_typing(conv_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    c = await _my_conv(db, ctx, conv_id)
    if c.mode in ("waiting_for_human", "human_active"):
        core.set_typing(c.id, "customer")
    return {"ok": True}


class ChatTicketIn(BaseModel):
    subject: str = Field(default="", max_length=200)
    category: str = "other"
    description: str = Field(default="", max_length=8000)


@router.post("/conversations/{conv_id}/ticket", status_code=201)
async def ticket_from_chat(conv_id: uuid.UUID, body: ChatTicketIn, ctx: CtxDep, db: DbDep):
    c = await _my_conv(db, ctx, conv_id)
    if c.ticket_id:
        t = await db.get(SupportTicket, c.ticket_id)
        if t:
            return _ticket_out(t)
    if body.category not in TICKET_CATEGORIES:
        raise HTTPException(status_code=400, detail="Pick a category.")
    t = await core.create_ticket(db, org=ctx.org, user=ctx.user, subject=body.subject.strip() or c.subject or "Support request",
                                 description=body.description, category=body.category, conversation=c)
    return _ticket_out(t)


# ── Customer: tickets ─────────────────────────────────────────────────────────


@router.get("/tickets")
async def my_tickets(ctx: CtxDep, db: DbDep, limit: int = 50):
    stmt = select(SupportTicket).where(SupportTicket.org_id == ctx.org.id)
    if not ctx.can_manage:
        stmt = stmt.where(SupportTicket.user_id == ctx.user.id)
    rows = (await db.execute(stmt.order_by(SupportTicket.updated_at.desc()).limit(min(limit, 100)))).scalars().all()
    users = await _names(db, [x for t in rows for x in (t.user_id, t.assigned_to)])
    return {"tickets": [_ticket_out(t, users) for t in rows]}


class TicketIn(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=3, max_length=8000)
    category: str = "other"
    attachments: list[str] = Field(default_factory=list)


@router.post("/tickets", status_code=201)
async def create_ticket(body: TicketIn, ctx: CtxDep, db: DbDep):
    if body.category not in TICKET_CATEGORIES:
        raise HTTPException(status_code=400, detail="Pick a category.")
    atts = await _claim_attachments(db, body.attachments, ctx.user)
    t = await core.create_ticket(db, org=ctx.org, user=ctx.user, subject=body.subject.strip(), description=body.description.strip(),
                                 category=body.category, attachments=atts)
    for a in atts:
        row = await db.get(SupportAttachment, uuid.UUID(a))
        row.ticket_id = t.id
    await db.commit()
    return _ticket_out(t)


@router.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    t = await _my_ticket(db, ctx, ticket_id)
    if t.user_id == ctx.user.id:
        t.customer_read_at = now()
        await db.commit()
    users = await _names(db, [t.user_id, t.assigned_to])
    return {"ticket": {**_ticket_out(t, users), "attachments": await _att_list(db, t.attachments or [])},
            "replies": await _replies_out(db, t, staff=False)}


class ReplyIn(BaseModel):
    body: str = Field(default="", max_length=8000)
    attachments: list[str] = Field(default_factory=list)


@router.post("/tickets/{ticket_id}/replies", status_code=201)
async def reply_ticket(ticket_id: uuid.UUID, body: ReplyIn, ctx: CtxDep, db: DbDep):
    t = await _my_ticket(db, ctx, ticket_id)
    text = body.body.replace("\x00", "").strip()
    if not text and not body.attachments:
        raise HTTPException(status_code=400, detail="Write a reply.")
    atts = await _claim_attachments(db, body.attachments, ctx.user, ticket_id=t.id)
    await core.add_ticket_reply(db, t, author=ctx.user, kind="customer", body=text, attachments=atts)
    return await get_ticket(ticket_id, ctx, db)


# ── Attachments ───────────────────────────────────────────────────────────────


def _sniff(data: bytes) -> str | None:
    for sig, ctype in _IMAGE_SIGS.items():
        if data.startswith(sig):
            return ctype
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def _store_upload(db, file: UploadFile, user: User, org_id) -> dict:
    data = await file.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise HTTPException(status_code=413, detail="Screenshots can be up to 5 MB.")
    ctype = _sniff(data)
    if not ctype:  # check the bytes, not the name or the browser's claim
        raise HTTPException(status_code=400, detail="Attach a PNG, JPG, GIF or WebP image.")
    name = re.sub(r"[^\w.\- ]", "_", (file.filename or "screenshot"))[:120] or "screenshot"
    row = SupportAttachment(org_id=org_id, uploader_id=user.id, filename=name, content_type=ctype, size=len(data), data=data)
    db.add(row)
    await db.commit()
    return {"id": str(row.id), "filename": name, "content_type": ctype, "size": len(data)}


@router.post("/attachments", status_code=201)
async def upload(ctx: CtxDep, db: DbDep, file: UploadFile = File(...)):
    recent = (await db.execute(select(func.count()).select_from(SupportAttachment).where(
        SupportAttachment.uploader_id == ctx.user.id, SupportAttachment.created_at >= now() - timedelta(hours=1)))).scalar_one()
    if recent >= 30:
        raise HTTPException(status_code=429, detail="Too many uploads — try again later.")
    return await _store_upload(db, file, ctx.user, ctx.org.id)


def _file_response(att: SupportAttachment) -> Response:
    return Response(content=att.data, media_type=att.content_type, headers={
        "Content-Disposition": f'inline; filename="{att.filename}"', "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=3600", "Content-Security-Policy": "default-src 'none'"})


@router.get("/attachments/{att_id}")
async def get_attachment(att_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    att = await db.get(SupportAttachment, att_id)
    ok = False
    if att:
        if att.uploader_id == ctx.user.id:
            ok = True
        elif att.conversation_id:
            c = await db.get(SupportConversation, att.conversation_id)
            ok = bool(c and c.org_id == ctx.org.id and c.user_id == ctx.user.id)
        elif att.ticket_id:
            t = await db.get(SupportTicket, att.ticket_id)
            ok = bool(t and t.org_id == ctx.org.id and (t.user_id == ctx.user.id or ctx.can_manage))
    if not ok:
        raise HTTPException(status_code=404, detail="File not found")
    return _file_response(att)


# ── Help center (published articles only) ────────────────────────────────────


def _article_out(a: KbArticle, full: bool = False) -> dict:
    out = {"id": str(a.id), "slug": a.slug, "title": a.title, "category": a.category, "summary": a.summary,
           "published": a.published, "updated_at": iso(a.updated_at)}
    if full:
        out["body"] = a.body
    return out


@router.get("/articles")
async def articles(ctx: CtxDep, db: DbDep, q: str = "", category: str = ""):
    if q.strip():
        rows = await ai.search_articles(db, q, limit=10)
    else:
        stmt = select(KbArticle).where(KbArticle.published.is_(True))
        if category:
            stmt = stmt.where(KbArticle.category == category)
        rows = (await db.execute(stmt.order_by(KbArticle.category, KbArticle.title))).scalars().all()
    return {"articles": [_article_out(a) for a in rows], "categories": list(KB_CATEGORIES)}


@router.get("/articles/{slug}")
async def article(slug: str, ctx: CtxDep, db: DbDep):
    a = (await db.execute(select(KbArticle).where(KbArticle.slug == slug, KbArticle.published.is_(True)))).scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="Article not found")
    return _article_out(a, full=True)


# ══ Staff (BlackSync platform admins with the admin portal unlocked) ═════════


FILTERS = {
    "all": None, "waiting": ("waiting_for_human",), "human": ("human_active",), "ai": ("ai_active",), "resolved": ("resolved",),
}


@admin_router.get("/summary")
async def staff_summary(admin: AdminDep, db: DbDep):
    await core.mark_present(db, admin.id)
    counts = dict((await db.execute(select(SupportConversation.mode, func.count()).group_by(SupportConversation.mode))).all())
    open_t = (await db.execute(select(func.count()).select_from(SupportTicket).where(
        SupportTicket.status.in_(("open", "in_progress", "waiting_for_customer"))))).scalar_one()
    unread_n = (await db.execute(select(func.count()).select_from(SupportNotification).where(
        SupportNotification.read_at.is_(None)))).scalar_one()
    return {"counts": {"waiting": counts.get("waiting_for_human", 0), "human": counts.get("human_active", 0),
                       "ai": counts.get("ai_active", 0), "resolved": counts.get("resolved", 0),
                       "all": sum(counts.values()), "open_tickets": open_t},
            "unread_notifications": unread_n, "ai_available": ai.available(), "ai_model": ai.model()}


@admin_router.get("/poll")
async def staff_poll(admin: AdminDep, db: DbDep, since: float = 0, wait: float = 25):
    """Wakes when anything in support changes; the inbox then refreshes what it shows."""
    await core.mark_present(db, admin.id)
    await db.commit()
    newest = (await db.execute(select(func.max(SupportConversation.updated_at)))).scalar_one()
    stamp = core.aware(newest).timestamp() if newest else 0
    if stamp <= since:
        await core.wait_for("staff", max(0.0, min(wait, POLL_MAX)))
    return {"at": time.time()}


@admin_router.get("/conversations")
async def staff_conversations(admin: AdminDep, db: DbDep, filter: str = "all", q: str = "", page: int = 1, per_page: int = 30):
    stmt = select(SupportConversation)
    if filter == "open_tickets":
        stmt = stmt.join(SupportTicket, SupportTicket.id == SupportConversation.ticket_id).where(
            SupportTicket.status.in_(("open", "in_progress", "waiting_for_customer")))
    elif FILTERS.get(filter):
        stmt = stmt.where(SupportConversation.mode.in_(FILTERS[filter]))
    q = q.strip()
    if q:
        like = f"%{q.lower()}%"
        conds = [
            SupportConversation.org_id.in_(select(Organization.id).where(func.lower(Organization.name).like(like))),
            SupportConversation.user_id.in_(select(User.id).where(or_(func.lower(User.email).like(like),
                                                                      func.lower(User.first_name + " " + User.last_name).like(like)))),
            SupportConversation.id.in_(select(SupportMessage.conversation_id).where(func.lower(SupportMessage.body).like(like))),
        ]
        if q.lstrip("#").isdigit():
            conds.append(SupportConversation.ticket_id.in_(select(SupportTicket.id).where(SupportTicket.number == int(q.lstrip("#")))))
        stmt = stmt.where(or_(*conds))
    per_page = max(1, min(per_page, 100))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(SupportConversation.last_message_at.desc())
                             .offset((max(page, 1) - 1) * per_page).limit(per_page))).scalars().all()
    return {"conversations": [await _conv_out(db, c, staff=True) for c in rows], "total": total, "page": page}


async def _staff_conv(db, conv_id: uuid.UUID) -> SupportConversation:
    c = await db.get(SupportConversation, conv_id)
    if not c:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return c


@admin_router.get("/conversations/{conv_id}")
async def staff_conversation(conv_id: uuid.UUID, admin: AdminDep, db: DbDep):
    c = await _staff_conv(db, conv_id)
    msgs = (await db.execute(select(SupportMessage).where(SupportMessage.conversation_id == c.id)
                             .order_by(SupportMessage.seq.desc()).limit(300))).scalars().all()
    c.staff_read_seq = c.last_seq
    await db.commit()
    org = await db.get(Organization, c.org_id)
    ticket = await db.get(SupportTicket, c.ticket_id) if c.ticket_id else None
    from app.services import entitlements

    plan = (await entitlements.effective(db, org)) if org else None
    return {"conversation": await _conv_out(db, c, staff=True), "messages": await _messages_out(db, list(reversed(msgs)), True),
            "org": {"id": str(org.id), "name": org.name, "status": org.status, "credits": org.credits_balance,
                    "plan": plan["plan_name"] if plan else None} if org else None,
            "ticket": _ticket_out(ticket, staff=True) if ticket else None}


@admin_router.get("/conversations/{conv_id}/poll")
async def staff_conversation_poll(conv_id: uuid.UUID, admin: AdminDep, db: DbDep, after: int = 0, wait: float = 25):
    c = await _staff_conv(db, conv_id)
    out = await _poll(db, c, after, wait, staff=True)
    c.staff_read_seq = max(c.staff_read_seq, c.last_seq)
    await db.commit()
    return out


def _first(u: User) -> str:
    return u.first_name or "A BlackSync team member"


class AsIn(BaseModel):
    # Team name to appear as ("Send as"); empty = the staff member's own first name.
    as_name: str | None = Field(default=None, max_length=80)


async def _persona(db, as_name: str | None) -> str | None:
    name = (as_name or "").strip()
    if not name:
        return None
    from app.services.billing import settings_store

    allowed = [p.strip() for p in (await settings_store.get(db, "support_personas") or []) if isinstance(p, str)]
    if name not in allowed:
        raise HTTPException(status_code=400, detail="Pick one of the team names.")
    return name


async def _set_alias(db, c: SupportConversation, alias: str | None) -> None:
    if c.agent_alias != alias:
        c.agent_alias = alias
        await db.commit()


@admin_router.post("/conversations/{conv_id}/takeover")
async def takeover(conv_id: uuid.UUID, admin: AdminDep, db: DbDep, body: AsIn | None = None):
    c = await _staff_conv(db, conv_id)
    alias = await _persona(db, body.as_name if body else None)
    if c.mode == "human_active" and c.assigned_to == admin.id and c.agent_alias == alias:
        return await _conv_out(db, c, staff=True)
    await core.set_mode(db, c, "human_active", assigned_to=admin.id)  # AI stops: any reply in flight is dropped
    await _set_alias(db, c, alias)
    await core.add_message(db, c, sender="system", body=f"{alias or _first(admin)} from BlackSync joined the chat.")
    return await _conv_out(db, c, staff=True)


@admin_router.post("/conversations/{conv_id}/return-to-ai")
async def return_to_ai(conv_id: uuid.UUID, admin: AdminDep, db: DbDep):
    c = await _staff_conv(db, conv_id)
    await core.set_mode(db, c, "ai_active")
    await core.add_message(db, c, sender="system", body="You're chatting with BlackSync AI again. Ask for a person any time.")
    return await _conv_out(db, c, staff=True)


@admin_router.post("/conversations/{conv_id}/resolve")
async def resolve(conv_id: uuid.UUID, admin: AdminDep, db: DbDep):
    c = await _staff_conv(db, conv_id)
    await core.set_mode(db, c, "resolved")
    await core.add_message(db, c, sender="system", body="This conversation was marked resolved. Write here any time to pick it back up.")
    return await _conv_out(db, c, staff=True)


@admin_router.post("/conversations/{conv_id}/reopen")
async def reopen(conv_id: uuid.UUID, admin: AdminDep, db: DbDep, body: AsIn | None = None):
    c = await _staff_conv(db, conv_id)
    alias = await _persona(db, body.as_name if body else None)
    await core.set_mode(db, c, "human_active", assigned_to=admin.id)
    await _set_alias(db, c, alias)
    await core.add_message(db, c, sender="system", body=f"{alias or _first(admin)} from BlackSync reopened this conversation.")
    return await _conv_out(db, c, staff=True)


class AssignIn(BaseModel):
    user_id: uuid.UUID | None = None


async def _staff_user(db, user_id: uuid.UUID | None) -> User | None:
    if user_id is None:
        return None
    u = await db.get(User, user_id)
    if not u or not u.is_superadmin:
        raise HTTPException(status_code=400, detail="Assign to a BlackSync team member.")
    return u


@admin_router.post("/conversations/{conv_id}/assign")
async def assign(conv_id: uuid.UUID, body: AssignIn, admin: AdminDep, db: DbDep):
    c = await _staff_conv(db, conv_id)
    u = await _staff_user(db, body.user_id)
    c.assigned_to = u.id if u else None
    c.updated_at = now()
    await db.commit()
    core.wake_conversation(c.id)
    return await _conv_out(db, c, staff=True)


class StaffMessageIn(BaseModel):
    body: str = Field(default="", max_length=MAX_BODY)
    internal: bool = False
    client_id: str | None = Field(default=None, max_length=64)
    attachments: list[str] = Field(default_factory=list)
    as_name: str | None = Field(default=None, max_length=80)


@admin_router.post("/conversations/{conv_id}/messages", status_code=201)
async def staff_message(conv_id: uuid.UUID, body: StaffMessageIn, admin: AdminDep, db: DbDep):
    c = await _staff_conv(db, conv_id)
    text = _clean_body(body.body)
    if not text and not body.attachments:
        raise HTTPException(status_code=400, detail="Type a message.")
    alias = await _persona(db, body.as_name)
    if not body.internal and c.mode != "human_active":
        # Replying is taking over: the AI must not answer alongside a person.
        await core.set_mode(db, c, "human_active", assigned_to=c.assigned_to or admin.id)
        await _set_alias(db, c, alias)
        await core.add_message(db, c, sender="system", body=f"{alias or _first(admin)} from BlackSync joined the chat.")
    elif not body.internal:
        await _set_alias(db, c, alias)
    atts = await _claim_attachments(db, body.attachments, admin, conversation_id=c.id)
    msg = await core.add_message(db, c, sender="agent", body=text, author_id=admin.id, internal=body.internal,
                                 attachments=atts, client_id=body.client_id, display_name=alias)
    core.set_typing(c.id, None)
    c.staff_read_seq = c.last_seq
    await db.commit()
    return (await _messages_out(db, [msg], True))[0]


@admin_router.post("/conversations/{conv_id}/typing")
async def staff_typing(conv_id: uuid.UUID, admin: AdminDep, db: DbDep):
    c = await _staff_conv(db, conv_id)
    if c.mode == "human_active":
        core.set_typing(c.id, "agent")
    return {"ok": True}


class StaffTicketIn(BaseModel):
    subject: str = Field(default="", max_length=200)
    category: str = "other"
    priority: str = "normal"
    description: str = Field(default="", max_length=8000)


@admin_router.post("/conversations/{conv_id}/ticket", status_code=201)
async def staff_ticket_from_chat(conv_id: uuid.UUID, body: StaffTicketIn, admin: AdminDep, db: DbDep):
    c = await _staff_conv(db, conv_id)
    if c.ticket_id and (t := await db.get(SupportTicket, c.ticket_id)):
        return _ticket_out(t, staff=True)
    if body.category not in TICKET_CATEGORIES or body.priority not in TICKET_PRIORITIES:
        raise HTTPException(status_code=400, detail="Pick a category and priority.")
    org = await db.get(Organization, c.org_id)
    user = await db.get(User, c.user_id) if c.user_id else None
    t = await core.create_ticket(db, org=org, user=user, subject=body.subject.strip() or c.subject or "Support request",
                                 description=body.description, category=body.category, priority=body.priority,
                                 conversation=c, created_by_staff=admin)
    t.assigned_to = admin.id
    await db.commit()
    return _ticket_out(t, staff=True)


@admin_router.post("/attachments", status_code=201)
async def staff_upload(admin: AdminDep, db: DbDep, file: UploadFile = File(...)):
    return await _store_upload(db, file, admin, None)


@admin_router.get("/attachments/{att_id}")
async def staff_attachment(att_id: uuid.UUID, admin: AdminDep, db: DbDep):
    att = await db.get(SupportAttachment, att_id)
    if not att:
        raise HTTPException(status_code=404, detail="File not found")
    return _file_response(att)


# ── Staff: tickets ────────────────────────────────────────────────────────────


@admin_router.get("/tickets")
async def staff_tickets(admin: AdminDep, db: DbDep, status: str = "", q: str = "", page: int = 1, per_page: int = 30):
    stmt = select(SupportTicket)
    if status == "active":
        stmt = stmt.where(SupportTicket.status.in_(("open", "in_progress", "waiting_for_customer")))
    elif status in TICKET_STATUSES:
        stmt = stmt.where(SupportTicket.status == status)
    q = q.strip()
    if q:
        like = f"%{q.lower()}%"
        conds = [func.lower(SupportTicket.subject).like(like), func.lower(SupportTicket.description).like(like),
                 SupportTicket.org_id.in_(select(Organization.id).where(func.lower(Organization.name).like(like))),
                 SupportTicket.user_id.in_(select(User.id).where(func.lower(User.email).like(like)))]
        if q.lstrip("#").isdigit():
            conds.append(SupportTicket.number == int(q.lstrip("#")))
        stmt = stmt.where(or_(*conds))
    per_page = max(1, min(per_page, 100))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(SupportTicket.updated_at.desc()).offset((max(page, 1) - 1) * per_page)
                             .limit(per_page))).scalars().all()
    users = await _names(db, [x for t in rows for x in (t.user_id, t.assigned_to)])
    orgs = {o.id: o for o in (await db.execute(select(Organization).where(Organization.id.in_({t.org_id for t in rows})))).scalars()} if rows else {}
    return {"tickets": [_ticket_out(t, users, orgs.get(t.org_id), staff=True) for t in rows], "total": total, "page": page}


async def _staff_ticket(db, ticket_id: uuid.UUID) -> SupportTicket:
    t = await db.get(SupportTicket, ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return t


@admin_router.get("/tickets/{ticket_id}")
async def staff_ticket(ticket_id: uuid.UUID, admin: AdminDep, db: DbDep):
    t = await _staff_ticket(db, ticket_id)
    users = await _names(db, [t.user_id, t.assigned_to])
    org = await db.get(Organization, t.org_id)
    return {"ticket": {**_ticket_out(t, users, org, staff=True), "attachments": await _att_list(db, t.attachments or [])},
            "replies": await _replies_out(db, t, staff=True)}


class TicketPatch(BaseModel):
    status: str | None = None
    priority: str | None = None
    category: str | None = None
    assigned_to: uuid.UUID | None = None
    unassign: bool = False


@admin_router.patch("/tickets/{ticket_id}")
async def staff_update_ticket(ticket_id: uuid.UUID, body: TicketPatch, admin: AdminDep, db: DbDep):
    t = await _staff_ticket(db, ticket_id)
    changes = []
    if body.status is not None:
        if body.status not in TICKET_STATUSES:
            raise HTTPException(status_code=400, detail="Unknown status.")
        if body.status != t.status:
            changes.append(f"Status: {t.status.replace('_', ' ')} → {body.status.replace('_', ' ')}")
            t.status = body.status
    if body.priority is not None:
        if body.priority not in TICKET_PRIORITIES:
            raise HTTPException(status_code=400, detail="Unknown priority.")
        t.priority = body.priority
    if body.category is not None:
        if body.category not in TICKET_CATEGORIES:
            raise HTTPException(status_code=400, detail="Unknown category.")
        t.category = body.category
    if body.unassign:
        t.assigned_to = None
    elif body.assigned_to is not None:
        t.assigned_to = (await _staff_user(db, body.assigned_to)).id
    t.updated_at = now()
    await db.commit()
    for ch in changes:  # status changes show in the customer's ticket history
        await core.add_ticket_reply(db, t, author=None, kind="system", body=ch)
    return await staff_ticket(ticket_id, admin, db)


class StaffReplyIn(BaseModel):
    body: str = Field(min_length=1, max_length=8000)
    internal: bool = False
    attachments: list[str] = Field(default_factory=list)
    status: str | None = None
    as_name: str | None = Field(default=None, max_length=80)


@admin_router.post("/tickets/{ticket_id}/replies", status_code=201)
async def staff_reply(ticket_id: uuid.UUID, body: StaffReplyIn, admin: AdminDep, db: DbDep):
    t = await _staff_ticket(db, ticket_id)
    alias = await _persona(db, body.as_name)
    atts = await _claim_attachments(db, body.attachments, admin, ticket_id=t.id)
    await core.add_ticket_reply(db, t, author=admin, kind="staff", body=body.body.strip(), internal=body.internal,
                                attachments=atts, display_name=alias)
    if body.status and body.status in TICKET_STATUSES and not body.internal:
        t.status = body.status
        await db.commit()
    if not t.assigned_to:
        t.assigned_to = admin.id
        await db.commit()
    return await staff_ticket(ticket_id, admin, db)


# ── Staff: notifications, team, AI usage ──────────────────────────────────────


@admin_router.get("/notifications")
async def notifications(admin: AdminDep, db: DbDep, limit: int = 30):
    rows = (await db.execute(select(SupportNotification).order_by(SupportNotification.created_at.desc())
                             .limit(min(limit, 100)))).scalars().all()
    return {"notifications": [{"id": str(n.id), "kind": n.kind, "text": n.text, "read": n.read_at is not None,
                               "conversation_id": str(n.conversation_id) if n.conversation_id else None,
                               "ticket_id": str(n.ticket_id) if n.ticket_id else None, "created_at": iso(n.created_at)}
                              for n in rows]}


@admin_router.post("/notifications/read")
async def notifications_read(admin: AdminDep, db: DbDep):
    for n in (await db.execute(select(SupportNotification).where(SupportNotification.read_at.is_(None)))).scalars():
        n.read_at = now()
    await db.commit()
    return {"ok": True}


@admin_router.get("/staff")
async def staff_list(admin: AdminDep, db: DbDep):
    from app.services.billing import settings_store

    rows = (await db.execute(select(User).where(User.is_superadmin.is_(True)).order_by(User.first_name))).scalars().all()
    return {"staff": [{"id": str(u.id), "name": u.full_name or u.email, "email": u.email} for u in rows],
            "me": str(admin.id), "me_name": admin.first_name or admin.full_name or admin.email,
            "personas": await settings_store.get(db, "support_personas") or []}


class PersonasIn(BaseModel):
    personas: list[str] = Field(max_length=30)


@admin_router.put("/personas")
async def set_personas(body: PersonasIn, admin: AdminDep, db: DbDep):
    """The team names staff can send as. Names already used on old messages stay as they are."""
    from app.services.billing import settings_store

    names = list(dict.fromkeys(n.strip()[:80] for n in body.personas if n and n.strip()))
    await settings_store.set_value(db, "support_personas", names, admin.id, reason="Support team names")
    await db.commit()
    return {"personas": names}


@admin_router.get("/usage")
async def ai_usage(admin: AdminDep, db: DbDep, days: int = 30):
    since = now() - timedelta(days=max(1, min(days, 365)))
    row = (await db.execute(select(func.count(), func.coalesce(func.sum(SupportAiUsage.prompt_tokens), 0),
                                   func.coalesce(func.sum(SupportAiUsage.completion_tokens), 0))
                            .where(SupportAiUsage.created_at >= since))).one()
    failed = (await db.execute(select(func.count()).select_from(SupportAiUsage).where(
        SupportAiUsage.created_at >= since, SupportAiUsage.ok.is_(False)))).scalar_one()
    return {"days": days, "replies": row[0], "failed": failed, "prompt_tokens_est": int(row[1]),
            "completion_tokens_est": int(row[2]), "model": ai.model(), "enabled": ai.available()}


# ── Staff: help center ────────────────────────────────────────────────────────


class ArticleIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    category: str = "getting_started"
    summary: str = Field(default="", max_length=300)
    body: str = Field(min_length=10, max_length=20000)
    published: bool = False
    slug: str | None = Field(default=None, max_length=120)


def _slugify(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")[:100] or "article"


@admin_router.get("/articles")
async def staff_articles(admin: AdminDep, db: DbDep, q: str = ""):
    if q.strip():
        rows = await ai.search_articles(db, q, limit=50, published_only=False)
    else:
        rows = (await db.execute(select(KbArticle).order_by(KbArticle.category, KbArticle.title))).scalars().all()
    return {"articles": [_article_out(a, full=True) for a in rows], "categories": list(KB_CATEGORIES)}


@admin_router.post("/articles", status_code=201)
async def create_article(body: ArticleIn, admin: AdminDep, db: DbDep):
    if body.category not in KB_CATEGORIES:
        raise HTTPException(status_code=400, detail="Pick a category.")
    slug = _slugify(body.slug or body.title)
    base, n = slug, 2
    while (await db.execute(select(KbArticle.id).where(KbArticle.slug == slug))).first():
        slug, n = f"{base}-{n}", n + 1
    a = KbArticle(slug=slug, title=body.title.strip(), category=body.category, summary=body.summary.strip(),
                  body=body.body.strip(), published=body.published, created_by=admin.id)
    db.add(a)
    await db.commit()
    return _article_out(a, full=True)


class ArticlePatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    category: str | None = None
    summary: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, min_length=10, max_length=20000)
    published: bool | None = None


@admin_router.patch("/articles/{article_id}")
async def update_article(article_id: uuid.UUID, body: ArticlePatch, admin: AdminDep, db: DbDep):
    a = await db.get(KbArticle, article_id)
    if not a:
        raise HTTPException(status_code=404, detail="Article not found")
    data = body.model_dump(exclude_none=True)
    if "category" in data and data["category"] not in KB_CATEGORIES:
        raise HTTPException(status_code=400, detail="Pick a category.")
    for k, v in data.items():
        setattr(a, k, v.strip() if isinstance(v, str) else v)
    await db.commit()
    return _article_out(a, full=True)


@admin_router.delete("/articles/{article_id}", status_code=204)
async def delete_article(article_id: uuid.UUID, admin: AdminDep, db: DbDep):
    a = await db.get(KbArticle, article_id)
    if a:
        await db.delete(a)
        await db.commit()

