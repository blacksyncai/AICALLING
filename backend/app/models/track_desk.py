"""
Track Desk: check calls for freight brokers.

A broker (an account) imports its active loads. On a schedule the account's check-call agent calls each load's
driver (or texts, in quiet hours or when the load is set to text only), asks where they are, whether they're
loaded and their ETA, and logs the answer on the load. The board scores every load (on time / at risk / late /
unresponsive) and the broker is alerted only on exceptions.

Every row carries org_id: a broker only ever sees its own loads, drivers, check-ins and alerts.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TrackDeskSettings(Base):
    """One per account: how often to check, quiet hours, who gets alerts, which agent and number call."""

    __tablename__ = "track_desk_settings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    broker_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False, default="Alex")
    # The check-call agent (created with the settings; editable like any agent).
    agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    caller_number: Mapped[str] = mapped_column(String(32), nullable=False, default="")  # blank = account default
    time_zone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/Chicago")
    check_interval_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=3)  # en-route, 2-4
    quiet_start_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=22)  # driver local time
    quiet_end_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    call_late_loads_in_quiet_hours: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sms_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # every load texts, never calls
    alert_emails: Mapped[list | None] = mapped_column(JSON, nullable=True)
    alert_phone: Mapped[str] = mapped_column(String(32), nullable=False, default="")  # texts the broker
    # Secret in the inbound-text webhook URL (the texting provider posts driver replies there).
    sms_token: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    plan: Mapped[str] = mapped_column(String(32), nullable=False, default="pilot")
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Shown in the app: None follows the account's industry (freight/logistics on), True/False set in Settings.
    enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class FreightLoad(Base):
    __tablename__ = "freight_loads"
    __table_args__ = (
        UniqueConstraint("org_id", "external_id", name="uq_freight_load_external"),
        Index("ix_freight_loads_org_status", "org_id", "status"),
        Index("ix_freight_loads_due", "status", "next_check_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)  # the broker's load number
    driver_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    driver_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    pickup_city: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    pickup_state: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    pickup_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pickup_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_city: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    delivery_state: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    delivery_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    shipper_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    broker_reference: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    commodity: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    trailer: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # active (on time) | at_risk | late | unresponsive | delivered | cancelled
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    sms_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    do_not_call: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # driver asked us to stop
    last_location: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    loaded: Mapped[str] = mapped_column(String(8), nullable=False, default="unknown")  # yes | no | unknown
    last_eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_eta_text: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    delay_reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_check_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="pickup")
    # Milestone checks already made: pickup, pre_delivery, delivery.
    milestones: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # The check round in progress: {"phase", "check_id", "kind", "until", "retried"} (see services/track_desk).
    round_state: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    unresponsive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class CheckCall(Base):
    """One attempt to reach a driver (a call, a text sent, a text reply, or a check-in the broker typed)."""

    __tablename__ = "check_calls"
    __table_args__ = (Index("ix_check_calls_load_time", "load_id", "attempted_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
                                              index=True)
    load_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("freight_loads.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="en_route")  # pickup|en_route|pre_delivery|delivery|manual
    channel: Mapped[str] = mapped_column(String(8), nullable=False, default="call")  # call | sms | manual
    # dialing (waiting for the call to end) | answered | no_answer | voicemail | failed | sms_sent | sms_reply | manual
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="dialing")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    call_log_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("call_logs.id", ondelete="SET NULL"),
                                                          nullable=True)
    location_text: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    loaded: Mapped[str] = mapped_column(String(8), nullable=False, default="unknown")
    eta_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    eta_text: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    delay_reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    driver_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")  # the text sent or received
    confidence: Mapped[str] = mapped_column(String(8), nullable=False, default="")  # high | medium | low
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entered_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")  # manual check-ins


class TrackAlert(Base):
    __tablename__ = "track_alerts"
    __table_args__ = (Index("ix_track_alerts_org_open", "org_id", "acknowledged_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    load_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("freight_loads.id", ondelete="CASCADE"), nullable=False,
                                               index=True)
    # late | at_risk | unresponsive | driver_requested_human | dnc | needs_review
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    delivered_via: Mapped[list | None] = mapped_column(JSON, nullable=True)  # ["in_app", "email", "sms"]
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")
