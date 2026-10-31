"""Admin-managed presentation and verified custom hostnames for customer accounts."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, LargeBinary, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WhiteLabel(Base):
    __tablename__ = "white_labels"

    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    brand_name: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    brand_kit: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    inherit_parent: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=True)
    logo: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True, deferred=True
    )
    logo_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(253), unique=True, nullable=True)
    verification_token: Mapped[str | None] = mapped_column(String(80), nullable=True)
    dns_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    domain_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified_target: Mapped[str | None] = mapped_column(String(253), nullable=True)
