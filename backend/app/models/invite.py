"""Platform invites an admin emailed to people who don't have a BlackSync account yet."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PlatformInvite(Base):
    __tablename__ = "platform_invites"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)  # lower-cased
    first_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    inviter_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    send_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
