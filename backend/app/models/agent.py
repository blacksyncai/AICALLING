"""
Agent model — a user-configurable AI voice agent (prompt, voice, knowledge,
actions, post-call analysis). Campaigns and calls reference an agent.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.agent.voices import DEFAULT_VOICE_ID
from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning organization (sub-account).
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )


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
    voice_id: Mapped[str] = mapped_column(String(128), nullable=False, default=DEFAULT_VOICE_ID)
    voice_speed: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    background_audio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Actions ───────────────────────────────────────────────────────────────
    enable_booking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    calcom_event_type_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    transfer_number: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    max_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=600)
    # Caller ID for this agent's calls (one of the account's numbers); blank = account default.
    caller_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Record phone calls (None = on when recording storage is configured).
    record_calls: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # ── Post-call analysis ────────────────────────────────────────────────────
    # Fields the analyzer extracts from every transcript, e.g.
    # [{"name": "budget", "description": "Monthly budget mentioned"}]
    extraction_fields: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Outcome labels the analyzer picks from, e.g. ["interested", "not_interested"].
    success_criteria: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # ── Built with AI ─────────────────────────────────────────────────────────
    # {"industry", "use_case", "direction", "style", "draft_id",
    #  "sections": {"identity": str, "reason": str, ...}} — see app/agent/builder docs.
    builder: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Whether the agent says it's an AI assistant when asked / at the start of calls.
    ai_disclosure: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    def __repr__(self) -> str:
        return f"<Agent id={self.id} name={self.name!r}>"
