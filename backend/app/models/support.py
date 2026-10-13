"""
Customer support — in-app chat (AI first, then a BlackSync person), tickets, the help center and
staff notifications. Everything belongs to one organization; only BlackSync staff see across them.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _org_fk():
    return mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)


def _user_fk(nullable: bool = True):
    return mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=nullable)


MODES = ("ai_active", "waiting_for_human", "human_active", "resolved")


class SupportConversation(Base):
    __tablename__ = "support_conversations"
    __table_args__ = (Index("ix_support_conv_mode_last", "mode", "last_message_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = _org_fk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # ai_active | waiting_for_human | human_active | resolved
    mode: Mapped[str] = mapped_column(String(24), nullable=False, default="ai_active")
    subject: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    assigned_to: Mapped[uuid.UUID | None] = _user_fk()
    # The team name the customer sees for the person helping them ("Send as"), if not their own.
    agent_alias: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Bumped whenever a person takes over (or the chat leaves AI mode): an AI reply started under an
    # older epoch is dropped instead of appearing after the human joined.
    epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Sequence of the newest message — allocated atomically with each insert.
    last_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    last_preview: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    customer_read_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    staff_read_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class SupportMessage(Base):
    __tablename__ = "support_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_support_msg_seq"),
        UniqueConstraint("conversation_id", "client_id", name="uq_support_msg_client"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("support_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    # customer | ai | agent | system
    sender: Mapped[str] = mapped_column(String(12), nullable=False)
    author_id: Mapped[uuid.UUID | None] = _user_fk()
    # Name shown to the customer for a staff message ("Send as"); None = the author's own first name.
    display_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attachments: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Staff-only note (never sent to the customer).
    internal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # UI hints: {"offer_escalation": true, "offer_ticket": true, "articles": [{slug, title}]}
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Sent by the client to make retries idempotent.
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


TICKET_CATEGORIES = ("technical", "agent_setup", "telephony", "campaigns", "billing", "integrations", "feature_request", "other")
TICKET_STATUSES = ("open", "in_progress", "waiting_for_customer", "resolved", "closed")
TICKET_PRIORITIES = ("low", "normal", "high", "urgent")


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    __table_args__ = (Index("ix_support_ticket_status_updated", "status", "updated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    org_id: Mapped[uuid.UUID] = _org_fk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(24), nullable=False, default="other")
    priority: Mapped[str] = mapped_column(String(12), nullable=False, default="normal")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    assigned_to: Mapped[uuid.UUID | None] = _user_fk()
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    attachments: Mapped[list | None] = mapped_column(JSON, nullable=True)
    customer_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reply_by: Mapped[str | None] = mapped_column(String(12), nullable=True)  # customer | staff
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class TicketReply(Base):
    __tablename__ = "support_ticket_replies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id: Mapped[uuid.UUID | None] = _user_fk()
    # customer | staff | system
    author_kind: Mapped[str] = mapped_column(String(12), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    internal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attachments: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class SupportAttachment(Base):
    """A screenshot uploaded to support. Kept in the database (small images only) — no extra storage service."""

    __tablename__ = "support_attachments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    uploader_id: Mapped[uuid.UUID | None] = _user_fk()
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[str] = mapped_column(String(40), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Set when the file is attached, so the customer who can see that chat/ticket can see the file.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


KB_CATEGORIES = ("getting_started", "agent_builder", "outbound_campaigns", "phone_numbers", "call_transfers",
                 "credits_billing", "crm_integrations", "account_settings", "troubleshooting")


class KbArticle(Base):
    __tablename__ = "support_kb_articles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="getting_started", index=True)
    summary: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_by: Mapped[uuid.UUID | None] = _user_fk()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class SupportNotification(Base):
    """Something BlackSync staff should look at. `dedupe_key` keeps repeats from piling up."""

    __tablename__ = "support_notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # escalation | new_ticket | customer_reply | ticket_reopened
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    org_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    text: Mapped[str] = mapped_column(String(300), nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)


class SupportAiUsage(Base):
    """One row per AI support reply — for rate limits and cost tracking (never calling credits)."""

    __tablename__ = "support_ai_usage"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)


class SupportPresence(Base):
    """When each staff member last had the support inbox open — "is anyone available?" is honest."""

    __tablename__ = "support_presence"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
