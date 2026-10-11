"""
CallLog model — one record per call: campaign/phone outbound calls, browser
voice test calls, and text playground sessions alike.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Float, DateTime, ForeignKey, Index, Integer, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


# status:  initiated | ringing | connected | completed | failed | no_answer
# outcome: meeting_booked | qualified | not_qualified | interested | not_interested
#          | callback | transferred | voicemail | no_answer | completed | failed
#          | wrong_number | do_not_call
CALL_OUTCOMES = (
    "meeting_booked", "qualified", "not_qualified", "interested", "not_interested",
    "callback", "transferred", "voicemail", "no_answer", "completed", "failed",
    "wrong_number", "do_not_call",
)


class CallLog(Base):
    __tablename__ = "call_logs"
    # Dashboard reports read an org's calls by date range.
    __table_args__ = (Index("ix_call_logs_org_started", "org_id", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning organization (sub-account).
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )


    # ── Foreign Keys ──────────────────────────────────────────────────────────
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("leads.id", ondelete="CASCADE"), nullable=True, index=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # outbound (phone) | web (browser voice test)
    call_type: Mapped[str | None] = mapped_column(String(16), nullable=True, default="outbound")
    to_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # ── LiveKit ───────────────────────────────────────────────────────────────
    livekit_room_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # ── Status ────────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="initiated")

    # ── Results ───────────────────────────────────────────────────────────────
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # transcript: list of {"role": "assistant"|"user"|"tool", "text": str, "ts": float}
    transcript: Mapped[list | None] = mapped_column(JSON, nullable=True)

    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    meeting_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Scheduled demo time (spoken label) + the email the prospect gave on the call.
    agreed_meeting_time: Mapped[str | None] = mapped_column(Text, nullable=True)
    prospect_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── Post-call analysis ────────────────────────────────────────────────────
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(16), nullable=True)
    extracted_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Voice latency: {"turns": n, "avg_response": s, "avg_eou": s, "avg_llm_ttft": s, "avg_tts_ttfb": s}
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    # When the callee picked up (phone calls) — talk time and billing start here.
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Credits billed for this call (set once, so re-reported outcomes never double-bill).
    credits_charged: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Credits set aside when the call was dialed (released when it's billed), and the agent's burn rate then.
    credits_reserved: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credit_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    # When call.completed / meeting.booked webhooks went out (sent once per call).
    events_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    lead = relationship("Lead", back_populates="call_logs", lazy="noload")
    campaign = relationship("Campaign", back_populates="call_logs", lazy="noload")

    def __repr__(self) -> str:
        return f"<CallLog id={self.id} lead_id={self.lead_id} status={self.status!r}>"
