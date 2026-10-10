"""
Lead Finder — property-owner lookups (DataSkip skip tracing).

One PropertyLookup row per attempted lookup. It doubles as the usage ledger:
rows in status "reserved" or "completed" count against the organization's
daily allowance; "failed" rows (provider errors, released reservations) don't.
Deleting a result scrubs the contact data but keeps the row, so deleting
history never gives back allowance.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PropertyLookup(Base):
    __tablename__ = "property_lookups"
    __table_args__ = (
        Index("ix_property_lookups_org_day", "org_id", "lookup_date"),
        Index("ix_property_lookups_org_key", "org_id", "address_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # UTC day the allowance was used ("YYYY-MM-DD").
    lookup_date: Mapped[str] = mapped_column(String(10), nullable=False)
    # Normalized "street|city|state|zip" — identifies a unique lookup for caching and quota.
    address_key: Mapped[str] = mapped_column(String(400), nullable=False)
    # The address as searched (street line only in `street`).
    street: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    city: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    state: Mapped[str] = mapped_column(String(2), nullable=False, default="")
    zip: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    # reserved (in flight) | completed | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="reserved")
    found: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Amount DataSkip charged, as returned by the API (USD).
    charged: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Normalized result: {"contact": {...}, "phones": [...], "emails": [...]}; NULL once deleted/expired.
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Sanitized failure reason for admins: invalid_request | auth | balance | rate_limited | provider_error | network
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("leads.id", ondelete="SET NULL"), nullable=True)
    scrubbed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
