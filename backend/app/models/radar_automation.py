"""Organization-scoped Radar rules, evidence and durable execution records."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


def now():
    return datetime.now(timezone.utc)


class RadarPond(Base):
    __tablename__ = "radar_ponds"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_radar_pond_name"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RadarPondMember(Base):
    __tablename__ = "radar_pond_members"
    __table_args__ = (UniqueConstraint("pond_id", "lead_id", "phone", name="uq_radar_pond_member"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    pond_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("radar_ponds.id", ondelete="CASCADE"), index=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("leads.id", ondelete="CASCADE"))
    phone: Mapped[str] = mapped_column(String(50))
    call_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("call_logs.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RadarVerification(Base):
    __tablename__ = "radar_verifications"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    call_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("call_logs.id", ondelete="CASCADE"), unique=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    phone: Mapped[str] = mapped_column(String(50))
    expected_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="unverified")
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RadarAutomation(Base):
    __tablename__ = "radar_automations"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("crm_connections.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    request: Mapped[str] = mapped_column(Text, default="")
    spec: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RadarExecution(Base):
    __tablename__ = "radar_executions"
    __table_args__ = (UniqueConstraint("automation_id", "version", "call_id", name="uq_radar_execution"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    automation_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("radar_automations.id", ondelete="CASCADE"))
    call_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("call_logs.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    # Immutable rule snapshot. Edits pause the rule and don't rewrite queued work.
    spec: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
