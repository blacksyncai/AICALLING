"""
Lead Finder — property-owner lookups (DataSkip skip tracing).

One PropertyLookup row per attempted lookup (single or part of a bulk batch).
Lookups are paid with lead-lookup credits (LeadCreditTransaction ledger,
separate from calling credits): 1 credit per owner found; no-match and failed
lookups are free. Deleting a result scrubs the contact data but keeps the row.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid
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
    # queued (bulk, waiting) | reserved (in flight) | completed | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="reserved")
    found: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # How this lookup was paid: free (daily allowance) | credit (prepaid lookup credit) | balance (USD) | unlimited | cache.
    pay_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # What the customer was charged from the lookup balance, in cents (0 = free / released).
    charge_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Amount DataSkip charged, as returned by the API (USD).
    charged: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Normalized result: {"contact": {...}, "phones": [...], "emails": [...]}; NULL once deleted/expired.
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Sanitized failure reason for admins: invalid_request | auth | balance | rate_limited | provider_error | network
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("leads.id", ondelete="SET NULL"), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lookup_batches.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Position in the uploaded CSV (bulk only) and credits this lookup used (0 or 1).
    row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credits: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    scrubbed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LookupBatch(Base):
    """A bulk CSV of addresses: parsed into a draft, then run in the background."""

    __tablename__ = "lookup_batches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # draft (parsed, not started) | running | done | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    # Draft only: the valid parsed addresses [{"row", "street", "city", "state", "zip", "key"}].
    rows: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Rows that couldn't be used: [{"row", "reason"}] (no address data).
    invalid: Mapped[list | None] = mapped_column(JSON, nullable=True)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_match: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    credits_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # credit | balance | unlimited — and, for balance, the confirmed price per lookup and total charged.
    pay_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    unit_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    charged_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    charged: Mapped[float | None] = mapped_column(Float, nullable=True, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LeadCreditTransaction(Base):
    """Lead-lookup credit ledger (separate from calling credits)."""

    __tablename__ = "lead_credit_transactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Positive adds credits, negative spends them.
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    # grant | usage | adjustment
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    lookup_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("property_lookups.id", ondelete="SET NULL"), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("lookup_batches.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)
