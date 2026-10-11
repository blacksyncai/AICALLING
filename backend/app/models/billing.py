"""
Billing & usage — Stripe mapping, purchases, credit lots, call usage, the
lead-lookup USD balance, auto-recharge, phone numbers, platform pricing and the
admin audit trail.

Ledgers are append-only: balances change only through a ledger row
(CreditTransaction for calling credits, LookupBalanceTransaction for the
lookup balance), and Stripe is the source of truth for money that moved.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _org_fk():
    return mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)


class BillingCustomer(Base):
    """One Stripe customer per organization."""

    __tablename__ = "billing_customers"

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    stripe_customer_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class BillingSubscription(Base):
    """Mirror of the organization's Stripe subscription (written by webhooks and plan changes)."""

    __tablename__ = "billing_subscriptions"

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    stripe_subscription_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # Our plan key (solo, teams…) or None for a Stripe price we don't manage (shown read-only).
    plan_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    price_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="incomplete")
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Subscription item carrying additional phone numbers (quantity = billable numbers).
    phone_item_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    phone_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class Purchase(Base):
    """A one-time payment: calling-credit pack, lookup funds, or an auto-recharge."""

    __tablename__ = "billing_purchases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = _org_fk()
    # credit_pack | lookup_funds | auto_recharge
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    pack_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="usd")
    credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # pending | paid | failed | canceled | refunded | partially_refunded | disputed
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    refunded_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # What a refund/dispute couldn't take back because it was already used.
    unrecovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Credits (or cents, for lookup funds) taken back when a dispute opened — restored if it's won.
    dispute_taken: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StripeEvent(Base):
    """Every Stripe webhook event we've accepted — the primary key deduplicates retries."""

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    org_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="received")  # received | processed | failed | ignored
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CreditLot(Base):
    """A batch of calling credits with its own price and expiry. Usage consumes lots (soonest expiry first)."""

    __tablename__ = "credit_lots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = _org_fk()
    # purchased | auto_recharge | included | grant | legacy
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    credits_granted: Mapped[int] = mapped_column(Integer, nullable=False)
    credits_remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    # What the customer paid for this lot (None for included/granted credits).
    amount_paid_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    purchase_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("billing_purchases.id", ondelete="SET NULL"), nullable=True)
    stripe_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # None = never expires (purchased credits). Included credits expire at the end of their billing cycle.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)


class CallUsage(Base):
    """Exactly one usage record per billed call (unique call_id = no double deductions)."""

    __tablename__ = "call_usage"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = _org_fk()
    call_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("call_logs.id", ondelete="CASCADE"), nullable=False, unique=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    voice_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    connected_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    credit_rate: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # Exact usage in thousandths of a credit, before rounding.
    credits_exact_milli: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    credits_deducted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Credits owed that the balance couldn't cover (never taken below zero).
    shortfall: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)


class LookupBalanceTransaction(Base):
    """Lead-lookup prepaid balance ledger, in cents. Restricted to lead-data purchases."""

    __tablename__ = "lookup_balance_transactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = _org_fk()
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)  # + credit, − debit
    balance_after_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    # funding | lookup | refund | dispute | dispute_won | adjustment
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stripe_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    purchase_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("billing_purchases.id", ondelete="SET NULL"), nullable=True)
    lookup_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)


class AutoRecharge(Base):
    """Optional automatic repurchase of a calling-credit pack (off by default)."""

    __tablename__ = "auto_recharge"

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pack_key: Mapped[str] = mapped_column(String(64), nullable=False, default="credits_500")
    threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    monthly_limit_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=50000)
    # Explicit customer authorization to charge the saved payment method.
    authorized_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pending_purchase_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class PhoneNumber(Base):
    """A phone number assigned to an organization — bought through Twilio or imported from it."""

    __tablename__ = "phone_numbers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = _org_fk()
    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    # active | released
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # Twilio IncomingPhoneNumber SID (PN…); "purchased" numbers are released back to
    # Twilio on removal, "imported" ones (already owned) are only unassigned.
    provider_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_default: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PhoneNumberRequest(Base):
    """A customer's request for another number — never billed until an admin assigns a real number."""

    __tablename__ = "phone_number_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = _org_fk()
    area_code: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")  # open | fulfilled | declined
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class PlatformSetting(Base):
    """Admin-controlled platform settings (pricing, policies), JSON values."""

    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | str | int | float | None] = mapped_column(JSON, nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class BillingAudit(Base):
    """Every manual balance adjustment or pricing change made by a BlackSync admin."""

    __tablename__ = "billing_audit"
    __table_args__ = (UniqueConstraint("id", name="uq_billing_audit_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    admin_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    # calling_credits | lookup_balance | pricing | phone_numbers
    target: Mapped[str] = mapped_column(String(24), nullable=False)
    previous: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    adjustment: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    new: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)
