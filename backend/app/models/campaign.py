"""
Campaign model — a batch of leads to dial with a shared ICP.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, JSON, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning organization (sub-account).
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )


    # ── Identity ──────────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    icp_description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # ── Status ────────────────────────────────────────────────────────────────
    # draft | running | paused | completed | cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    # "outbound" dials a contact list; "inbound" answers calls to one of the account's numbers.
    direction: Mapped[str | None] = mapped_column(String(16), nullable=True, default="outbound")
    phone_number_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # Why the system paused it ("credits"); None when a person paused it or it's running.
    pause_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # ── Agent that places this campaign's calls ───────────────────────────────
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Calls this campaign may have in flight at once.
    max_concurrent_calls: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1)

    # ── Calling rules (NULL = default) ───────────────────────────────────────
    # Local "HH:MM" window the queue may dial in (default 09:00–17:00).
    call_window_start: Mapped[str | None] = mapped_column(String(5), nullable=True)
    call_window_end: Mapped[str | None] = mapped_column(String(5), nullable=True)
    # Weekdays allowed, 0=Mon … 6=Sun (default Mon–Fri).
    call_days: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # IANA time zone the window is in (default America/New_York).
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Automatic retries for unanswered calls: total tries per contact (default 1 = no retry).
    max_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_delay_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Custom retry schedule: minutes to wait before each retry, in order (e.g. [15, 20, 1440, 2880]).
    # When set, it decides the number of tries (len + 1) and each wait; NULL = the single delay above.
    retry_schedule: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Optional outbound caller-ID pool. NULL preserves the existing single-number behavior.
    number_rotation_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    caller_number_pool: Mapped[list | None] = mapped_column(JSON, nullable=True)
    retry_caller_policy: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Warm-up pacing: dial slowly with random gaps and rest pauses so a fresh
    # number doesn't register as spam. NULL = off (normal dialing).
    warmup_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Seconds between calls (NULL = random 180-300, i.e. ~1 call per 3-5 minutes).
    warmup_min_gap_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warmup_max_gap_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Calls before a longer rest pause (NULL = 10), and how long that rest lasts (NULL = 15 min).
    warmup_batch_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warmup_rest_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    caller_rotation_cursor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Rotation: most calls each number may place in a rolling 24 h (NULL = 75).
    max_calls_per_number_day: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Counters ──────────────────────────────────────────────────────────────
    total_targets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_dialed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_qualified: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_booked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    leads = relationship("Lead", back_populates="campaign", lazy="noload")
    call_logs = relationship("CallLog", back_populates="campaign", lazy="noload")

    def __repr__(self) -> str:
        return f"<Campaign id={self.id} name={self.name!r} status={self.status!r}>"
