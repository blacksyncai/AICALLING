"""Persisted, immutable CRM assistant proposals and execution receipts."""
import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.models.radar_automation import now

class CrmCommand(Base):
    __tablename__ = "crm_assistant_commands"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("crm_connections.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    account_label: Mapped[str] = mapped_column(String(255), default="")
    connection_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    spec: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RadarConversation(Base):
    """Private conversation, isolated by workspace, user and CRM connection."""
    __tablename__ = "radar_conversations"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("crm_connections.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    connection_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    drafts: Mapped[list] = mapped_column(JSON, default=list)
    title: Mapped[str] = mapped_column(String(120), default="New conversation")
    messages: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
