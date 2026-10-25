"""Every email the platform sends through Resend, with what happened to it (Resend webhook events)."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EmailMessage(Base):
    __tablename__ = "email_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    resend_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    notification_key: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    from_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    to_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)  # lower-cased
    subject: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # welcome | catchup | walkthrough | platform_invite | team_invite | support | auth | signup_alert | other
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="other", index=True)
    # sent → delivered → opened → clicked; or bounced / complained / delayed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="sent")
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    open_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    click_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bounced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    complained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
