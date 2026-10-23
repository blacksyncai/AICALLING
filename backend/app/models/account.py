"""
Accounts — organizations (sub-accounts), their users and team invites, the
calling-credit ledger, and the API keys / outgoing webhooks each org owns.

Every agent, campaign, contact and call belongs to one organization; a user
can belong to several, and a platform super-admin can open any of them.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # active | suspended — a suspended org can sign in but not place calls.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # Calling credits. A call costs (connected seconds / 60) × the agent's credit rate — see services/billing/credits.py.
    credits_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # House accounts skip the credit check entirely.
    unlimited_credits: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # IANA time zone used for reports ("which day did this call happen on?").
    # NULL means the default, America/New_York (see app.services.reporting).
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Lead Finder on/off (NULL = on). lead_finder_daily_limit is unused (replaced by lookup credits); kept so old databases match.
    lead_finder_daily_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead_finder_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Flash-family models (app.agent.models.requires_unlock) unlocked for this account by the team.
    models_unlocked: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Free-trial onboarding answers: industry key (agent catalog) and {"goals", "team_size", ...}.
    industry: Mapped[str | None] = mapped_column(String(64), nullable=True)
    onboarding: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Lead-lookup credits — separate from calling credits. 1 credit = 1 property owner found.
    lead_credits_balance: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    lead_credits_unlimited: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    # Fraction of a calling credit (thousandths) carried to the next call, so per-second billing adds up exactly.
    credit_carry_milli: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    # Lead-lookup prepaid balance in cents (restricted to lead data; separate from calling credits).
    lookup_balance_cents: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    # Managed plan onboarding: needed (paid, not started) | scheduled | done. NULL = not a Managed account.
    managed_onboarding: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Billing country: "US" (default, Stripe) | "CA" | "OTHER" (Helcim for one-time purchases).
    billing_country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    last_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    # Empty for users who sign in through Clerk.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    clerk_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    # Platform admin: sees the admin portal and can open every organization.
    is_superadmin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # The organization the user is currently working in.
    active_org_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    # Bumped on password change so older session cookies stop working.
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Sign-up emails: the welcome email, then a walkthrough offer a day later (app/services/onboarding_emails.py).
    welcome_email_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    followup_email_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # "Your workspace is waiting" — sent by an admin to people who signed up before emails were set up.
    catchup_email_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


ROLES = ("owner", "admin", "member")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "org_id", name="uq_membership_user_org"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # owner | admin | member — owners and admins manage the team and org name.
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="member")
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Positive adds credits, negative spends them.
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    # Exact values in thousandths of a credit (per-second call billing). NULL on older rows.
    amount_milli: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    balance_after_milli: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # grant | usage | adjustment
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    call_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("call_logs.id", ondelete="SET NULL"), nullable=True)
    # Where the credits came from / went: purchase, lot and Stripe reference (NULL for older rows).
    purchase_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    lot_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    stripe_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # First characters of the key, shown in the UI so keys can be told apart.
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


WEBHOOK_EVENTS = ("call.completed", "meeting.booked", "contact.created")


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    url: Mapped[str] = mapped_column(Text, nullable=False)
    events: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Signs each delivery (X-BlackSync-Signature: sha256=<hmac of body>).
    secret: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class AppSecret(Base):
    """Small key/value store for generated platform secrets (e.g. the session signing key)."""

    __tablename__ = "app_secrets"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
