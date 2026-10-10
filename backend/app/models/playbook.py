"""
Agent generation support data:

- Playbook / PlaybookVersion — the platform's internal reference library of
  proven agent scripts (admin-managed, never visible to customers). Each version
  keeps the original script verbatim plus the transferable pattern card the
  generator is allowed to read, and the client-specific terms that must never
  appear in another customer's agent.
- ReferenceDocument — scripts and notes a customer uploads or pastes while
  building an agent. Always scoped to one organization.
- AgentVersion — snapshots of an agent's prompt (generated, edited, restored).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Playbook(Base):
    __tablename__ = "playbooks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Retrieval tags: {"verticals": [...], "directions": [...], "goals": [...], "styles": [...]}
    tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Inactive playbooks stay archived but are never offered to the generator.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class PlaybookVersion(Base):
    __tablename__ = "playbook_versions"
    __table_args__ = (UniqueConstraint("playbook_id", "version", name="uq_playbook_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    playbook_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("playbooks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # The source script exactly as supplied. Archived for admins; never sent to the generator.
    original_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Transferable methods only (no client names, offers, URLs or IDs) — what the generator reads.
    patterns: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Client-specific names, places, URLs and identifiers that must never leak into other agents.
    private_terms: Mapped[list | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class ReferenceDocument(Base):
    __tablename__ = "reference_documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("agent_drafts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # pdf | docx | txt | paste
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="paste")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class AgentVersion(Base):
    __tablename__ = "agent_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # generated | edited | improved | regenerated | restored
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="edited")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    first_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sections: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)
