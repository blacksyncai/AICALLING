"""Workspace call-alert preferences and durable, recipient-scoped delivery queue."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

def now():
    return datetime.now(timezone.utc)

class CallAlertSettings(Base):
    __tablename__ = 'call_alert_settings'
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('organizations.id', ondelete='CASCADE'), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcomes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    user_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    agent_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    crm_base_url: Mapped[str] = mapped_column(String(300), default='', nullable=False)

class CallAlert(Base):
    __tablename__ = 'call_alerts'
    __table_args__ = (UniqueConstraint('call_id', 'user_id'),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('organizations.id', ondelete='CASCADE'), index=True, nullable=False)
    call_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('call_logs.id', ondelete='CASCADE'), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    automatic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default='queued', nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(Text, default='', nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    next_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
