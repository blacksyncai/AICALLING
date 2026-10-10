"""
Agent builder — the organization's reusable business profile and knowledge base
(built from its website, uploads and manual edits), its revision history, and
saved progress of the "Build with AI" wizard.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BusinessProfile(Base):
    """One per organization; shared by every agent the organization builds."""

    __tablename__ = "business_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    industry: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    website: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # idle | analyzing | ready | limited | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="idle")
    progress_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Pages read during the last analysis: [{"url", "title"}]
    pages: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # {"sections": [{"key", "title", "items": [{"id", "text", "source_url", "origin", "needs_review"}]}]}
    knowledge: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Proposed changes from a rescan, awaiting review: [{"id", "section", "action": "add"|"remove", "item"}]
    pending_changes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Re-scan the website every N days (None = only when asked).
    auto_refresh_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class KnowledgeRevision(Base):
    """A snapshot of the knowledge base, saved before each change."""

    __tablename__ = "knowledge_revisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    knowledge: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)


class AgentDraft(Base):
    """Saved progress of the Build-with-AI wizard, so people can leave and resume."""

    __tablename__ = "agent_drafts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Set once the draft has been turned into an agent.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
