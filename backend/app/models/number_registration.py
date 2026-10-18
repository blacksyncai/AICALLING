"""Durable caller identity authorization, outbox and provider receipts."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


def now(): return datetime.now(timezone.utc)


class RegistrationAuthorization(Base):
    __tablename__ = 'registration_authorizations'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    caller_name: Mapped[str] = mapped_column(String(15))
    legal_name: Mapped[str] = mapped_column(String(255))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    providers: Mapped[list] = mapped_column(JSON, default=list)
    fees_authorized: Mapped[list] = mapped_column(JSON, default=list)
    authorized_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('users.id'))
    evidence: Mapped[str] = mapped_column(Text)
    terms_version: Mapped[str] = mapped_column(String(32), default='caller-registration-v1')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProviderBusiness(Base):
    __tablename__ = 'registration_businesses'
    __table_args__ = (UniqueConstraint('org_id', 'provider', name='uq_registration_business'),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default='verification_required')
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class NumberRegistration(Base):
    __tablename__ = 'number_registrations'
    __table_args__ = (UniqueConstraint('phone_number_id', 'assignment_key', 'provider', name='uq_number_registration_assignment'),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    phone_number_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('phone_numbers.id', ondelete='CASCADE'), index=True)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    assignment_key: Mapped[str] = mapped_column(String(64))
    number: Mapped[str] = mapped_column(String(20))
    carrier: Mapped[str] = mapped_column(String(32))
    carrier_number_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider: Mapped[str] = mapped_column(String(32))
    authorization_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey('registration_authorizations.id'), nullable=True)
    caller_name: Mapped[str] = mapped_column(String(15), default='')
    # register | remove. Leased rows survive process crashes; intent survives lost HTTP responses.
    phase: Mapped[str] = mapped_column(String(16), default='register')
    status: Mapped[str] = mapped_column(String(32), default='queued', index=True)
    prerequisite: Mapped[str] = mapped_column(Text, default='')
    request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    previous_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    submission_intent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removal_intent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RegistrationReceipt(Base):
    __tablename__ = 'registration_receipts'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    registration_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('number_registrations.id', ondelete='CASCADE'), index=True)
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(Text)
    http_status: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
