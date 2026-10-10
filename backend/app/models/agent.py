"""
Agent model — a user-configurable AI voice agent (prompt, voice, knowledge,
actions, post-call analysis). Campaigns and calls reference an agent.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # ── Identity ──────────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    template: Mapped[str] = mapped_column(String(64), nullable=False, default="blank")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    # ── Conversation ──────────────────────────────────────────────────────────
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Spoken verbatim when the call connects. Supports {{name}}, {{company}} … vars.
    first_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    knowledge_base: Mapped[str] = mapped_column(Text, nullable=False, default="")
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")

    # ── Model / voice ─────────────────────────────────────────────────────────
    llm_model: Mapped[str] = mapped_column(String(64), nullable=False, default="gpt-4.1-mini")
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    voice_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="a167e0f3-df7e-4d52-a9c3-f949145efdab"
    )
    voice_speed: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    background_audio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Actions ───────────────────────────────────────────────────────────────
    enable_booking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    calcom_event_type_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    transfer_number: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    max_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=600)

    # ── Post-call analysis ────────────────────────────────────────────────────
    # Fields the analyzer extracts from every transcript, e.g.
    # [{"name": "budget", "description": "Monthly budget mentioned"}]
    extraction_fields: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Outcome labels the analyzer picks from, e.g. ["interested", "not_interested"].
    success_criteria: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    def __repr__(self) -> str:
        return f"<Agent id={self.id} name={self.name!r}>"
