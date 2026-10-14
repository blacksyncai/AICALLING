"""
An account's own texting (SMS) provider: Twilio or Telnyx credentials the customer pastes in, so their
agents can send texts from the customer's own number and sender registration.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MessagingConnection(Base):
    __tablename__ = "messaging_connections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)  # twilio | telnyx
    # Twilio Account SID (not secret, shown masked). Empty for Telnyx.
    account_sid: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # Fernet-encrypted Twilio auth token / Telnyx API key. Never returned by the API.
    secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_number: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    messaging_profile_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")  # Telnyx, optional
    account_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
