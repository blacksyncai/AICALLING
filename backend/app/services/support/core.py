"""
Support conversations: messages, modes (AI → waiting → human → resolved), tickets and staff
notifications.

Ordering and the human takeover race:
  every message gets its sequence number from one atomic UPDATE on the conversation row. An AI
  reply is only saved when that UPDATE also matches mode == ai_active and the epoch the AI started
  under; taking over bumps the epoch, so a slow AI reply is dropped rather than appearing after a
  person joined.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Organization, User
from app.models.support import (
    SupportConversation, SupportMessage, SupportNotification, SupportPresence, SupportTicket, TicketReply,
)

log = structlog.get_logger(__name__)

UNAVAILABLE = "Our support team isn't available right now. I can create a support ticket so someone can follow up."
STAFF_ONLINE_WINDOW = timedelta(minutes=3)


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


def iso(d: datetime | None) -> str | None:
    d = aware(d)
    return d.isoformat() if d else None


# ── Wake-ups for long polling (one process; the poll also re-checks the database) ──

_waiters: dict[str, set[asyncio.Event]] = defaultdict(set)
_typing: dict[uuid.UUID, tuple[str, datetime]] = {}


def wake(key: str) -> None:
    for ev in list(_waiters.get(key, ())):
        ev.set()


def wake_conversation(conv_id: uuid.UUID) -> None:
    wake(f"conv:{conv_id}")
    wake("staff")


async def wait_for(key: str, timeout: float) -> None:
    ev = asyncio.Event()
    _waiters[key].add(ev)
    try:
        await asyncio.wait_for(ev.wait(), timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        _waiters[key].discard(ev)
        if not _waiters[key]:
            _waiters.pop(key, None)


def set_typing(conv_id: uuid.UUID, who: str | None) -> None:
    if who:
        _typing[conv_id] = (who, now())
    else:
        _typing.pop(conv_id, None)
    wake_conversation(conv_id)


def typing(conv_id: uuid.UUID) -> str | None:
    who = _typing.get(conv_id)
    if not who:
        return None
    # The AI clears its own flag; a person's lasts a few seconds after their last keystroke.
    if who[0] != "ai" and now() - who[1] > timedelta(seconds=6):
        return None
    return who[0]


# ── Messages ──────────────────────────────────────────────────────────────────


def preview(text: str) -> str:
    return " ".join((text or "").split())[:160]


async def add_message(db: AsyncSession, conv: SupportConversation, *, sender: str, body: str,
                      author_id: uuid.UUID | None = None, internal: bool = False, attachments: list | None = None,
                      meta: dict | None = None, client_id: str | None = None,
                      ai_epoch: int | None = None) -> SupportMessage | None:
    """Append a message with the next sequence number and commit. With `ai_epoch`, only while the chat
    is still AI-handled under that epoch (else None: the reply is dropped)."""
    if client_id:
        dup = (await db.execute(select(SupportMessage).where(
            SupportMessage.conversation_id == conv.id, SupportMessage.client_id == client_id))).scalar_one_or_none()
        if dup:
            return dup
    stmt = update(SupportConversation).where(SupportConversation.id == conv.id)
    if ai_epoch is not None:
        stmt = stmt.where(SupportConversation.mode == "ai_active", SupportConversation.epoch == ai_epoch)
    values: dict = {"last_seq": SupportConversation.last_seq + 1}
    if not internal:
        values.update(last_message_at=now(), last_preview=preview(body or ("[screenshot]" if attachments else "")))
    seq = (await db.execute(stmt.values(**values).returning(SupportConversation.last_seq))).scalar_one_or_none()
    if seq is None:
        await db.rollback()
        return None
    msg = SupportMessage(conversation_id=conv.id, seq=seq, sender=sender, author_id=author_id, body=body,
                         internal=internal, attachments=attachments or None, meta=meta, client_id=client_id)
    db.add(msg)
    if sender == "customer":
        conv.customer_read_seq = seq  # the sender has read up to their own message
    try:
        await db.commit()
    except IntegrityError:  # the same client_id raced in twice
        await db.rollback()
        return (await db.execute(select(SupportMessage).where(
            SupportMessage.conversation_id == conv.id, SupportMessage.client_id == client_id))).scalar_one_or_none()
    await db.refresh(conv)
    wake_conversation(conv.id)
    return msg


async def set_mode(db: AsyncSession, conv: SupportConversation, mode: str, *, assigned_to: uuid.UUID | None = None,
                   keep_assignee: bool = True) -> None:
    """Change mode and bump the epoch, so any AI reply already in flight is discarded."""
    values: dict = {"mode": mode, "epoch": SupportConversation.epoch + 1, "updated_at": now()}
    if assigned_to is not None or not keep_assignee:
        values["assigned_to"] = assigned_to
    await db.execute(update(SupportConversation).where(SupportConversation.id == conv.id).values(**values))
    await db.commit()
    await db.refresh(conv)
    _typing.pop(conv.id, None)
    wake_conversation(conv.id)


async def staff_online(db: AsyncSession) -> bool:
    since = now() - STAFF_ONLINE_WINDOW
    return bool((await db.execute(select(func.count()).select_from(SupportPresence)
                                  .where(SupportPresence.seen_at >= since))).scalar_one())


async def mark_present(db: AsyncSession, user_id: uuid.UUID) -> None:
    row = await db.get(SupportPresence, user_id)
    if row is None:
        db.add(SupportPresence(user_id=user_id, seen_at=now()))
    else:
        row.seen_at = now()
    await db.commit()


# ── Notifications (in-app for staff, optional email) ──────────────────────────


async def notify(db: AsyncSession, kind: str, text: str, *, org_id=None, conversation_id=None, ticket_id=None,
                 dedupe_key: str | None = None, window: timedelta = timedelta(minutes=30), email_subject: str | None = None) -> bool:
    """Record a staff notification unless the same thing was notified within `window`. Commits."""
    if dedupe_key:
        recent = (await db.execute(select(SupportNotification.id).where(
            SupportNotification.dedupe_key == dedupe_key, SupportNotification.created_at >= now() - window).limit(1))).first()
        if recent:
            return False
    db.add(SupportNotification(kind=kind, text=text[:300], org_id=org_id, conversation_id=conversation_id,
                               ticket_id=ticket_id, dedupe_key=dedupe_key))
    await db.commit()
    wake("staff")
    if email_subject:
        _email_staff(email_subject, text, conversation_id=conversation_id, ticket_id=ticket_id)
    return True


def _email_staff(subject: str, text: str, *, conversation_id=None, ticket_id=None) -> None:
    import html

    from app.config import settings
    from app.services.email import send_email

    to = (settings.support_notify_email or "").strip()
    if not settings.support_email_notifications or not to:
        return
    base = (settings.app_url or "").rstrip("/")
    link = f"{base}/admin/support" + (f"?c={conversation_id}" if conversation_id else f"?t={ticket_id}" if ticket_id else "")
    body = (f"<p>{html.escape(text)}</p>"
            f"<p><a href=\"{html.escape(link)}\">Open the BlackSync support inbox</a></p>")

    async def go():
        try:
            await send_email(to, f"[BlackSync Support] {subject}", body)
        except Exception as exc:  # never let email break support
            log.warning("support_email_failed", error=str(exc)[:200])

    try:
        asyncio.get_running_loop().create_task(go())
    except RuntimeError:
        pass


# ── Escalation ────────────────────────────────────────────────────────────────


async def escalate(db: AsyncSession, conv: SupportConversation, org: Organization, user: User | None,
                   reason: str = "") -> SupportMessage | None:
    """Customer wants a person. Honest about availability; staff are notified either way."""
    if conv.mode in ("waiting_for_human", "human_active"):
        return None
    await set_mode(db, conv, "waiting_for_human")
    online = await staff_online(db)
    text = ("Thanks — I've let the BlackSync team know. Someone will join this chat shortly, and you'll see their name here."
            if online else UNAVAILABLE)
    msg = await add_message(db, conv, sender="system", body=text, meta=None if online else {"offer_ticket": True})
    who = (user.full_name or user.email) if user else "A customer"
    await notify(db, "escalation", f"{who} ({org.name}) asked for a person: “{conv.last_preview or reason}”",
                 org_id=org.id, conversation_id=conv.id, dedupe_key=f"esc:{conv.id}:{conv.epoch}",
                 email_subject=f"{org.name} asked for a person")
    return msg


# ── Tickets ───────────────────────────────────────────────────────────────────


async def next_ticket_number(db: AsyncSession) -> int:
    top = (await db.execute(select(func.max(SupportTicket.number)))).scalar_one()
    return max(int(top or 1000), 1000) + 1


async def create_ticket(db: AsyncSession, *, org: Organization, user: User | None, subject: str, description: str,
                        category: str, priority: str = "normal", conversation: SupportConversation | None = None,
                        attachments: list | None = None, created_by_staff: User | None = None) -> SupportTicket:
    if conversation is not None:
        description = description.strip() + "\n\n— Chat history —\n" + await transcript(db, conversation)
    for _ in range(5):
        t = SupportTicket(number=await next_ticket_number(db), org_id=org.id, user_id=user.id if user else None,
                          subject=subject[:200], description=description, category=category, priority=priority,
                          conversation_id=conversation.id if conversation else None, attachments=attachments or None,
                          last_reply_at=now(), last_reply_by="staff" if created_by_staff else "customer")
        db.add(t)
        try:
            await db.commit()
            break
        except IntegrityError:  # two tickets took the same number — try the next one
            await db.rollback()
    else:
        raise RuntimeError("Couldn't allocate a ticket number")
    if conversation is not None:
        conversation.ticket_id = t.id
        await db.commit()
        await add_message(db, conversation, sender="system", body=f"Ticket #{t.number} was created for this conversation.",
                          meta={"ticket": {"id": str(t.id), "number": t.number}})
    if not created_by_staff:
        who = (user.full_name or user.email) if user else "A customer"
        await notify(db, "new_ticket", f"New ticket #{t.number} from {who} ({org.name}): {t.subject}",
                     org_id=org.id, ticket_id=t.id, dedupe_key=f"ticket:{t.id}", email_subject=f"Ticket #{t.number}: {t.subject}")
    return t


async def transcript(db: AsyncSession, conv: SupportConversation, limit: int = 60) -> str:
    rows = (await db.execute(select(SupportMessage).where(
        SupportMessage.conversation_id == conv.id, SupportMessage.internal.is_(False))
        .order_by(SupportMessage.seq.desc()).limit(limit))).scalars().all()
    label = {"customer": "Customer", "ai": "BlackSync AI", "agent": "BlackSync team", "system": "System"}
    return "\n".join(f"[{label.get(m.sender, m.sender)}] {m.body}" for m in reversed(rows) if m.body)


async def add_ticket_reply(db: AsyncSession, t: SupportTicket, *, author: User | None, kind: str, body: str,
                           internal: bool = False, attachments: list | None = None) -> TicketReply:
    r = TicketReply(ticket_id=t.id, author_id=author.id if author else None, author_kind=kind, body=body,
                    internal=internal, attachments=attachments or None)
    db.add(r)
    if not internal:
        t.last_reply_at, t.last_reply_by = now(), kind
        if kind == "customer" and t.status in ("waiting_for_customer", "resolved", "closed"):
            reopened = t.status in ("resolved", "closed")
            t.status = "open"
            if reopened:
                await db.commit()
                await notify(db, "ticket_reopened", f"Ticket #{t.number} was reopened by the customer: {t.subject}",
                             org_id=t.org_id, ticket_id=t.id, dedupe_key=f"reopen:{t.id}", window=timedelta(minutes=10),
                             email_subject=f"Ticket #{t.number} reopened")
        elif kind == "staff" and t.status == "open":
            t.status = "in_progress"
    t.updated_at = now()
    await db.commit()
    if kind == "customer" and not internal:
        await notify(db, "customer_reply", f"New reply on ticket #{t.number}: {preview(body)}", org_id=t.org_id,
                     ticket_id=t.id, dedupe_key=f"treply:{t.id}", window=timedelta(minutes=10))
    return r
