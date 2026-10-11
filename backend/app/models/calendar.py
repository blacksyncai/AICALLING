"""A Google Calendar connected to an account (one per organization)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CalendarConnection(Base):
    __tablename__ = "calendar_connections"

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False, default="google")
    email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    calendar_id: Mapped[str] = mapped_column(String(255), nullable=False, default="primary")
    # Fernet-encrypted refresh token (SECRETS_ENCRYPTION_KEY); never returned by the API.
    refresh_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    connected_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
