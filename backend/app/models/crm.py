"""
CRM and app connections (Close, Follow Up Boss, HubSpot, Pipedrive, HighLevel, Salesforce…).

A connection is either native (the account pastes an API key, stored Fernet-encrypted)
or through Nango (OAuth handled by Nango; we keep only the Nango connection id).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CrmConnection(Base):
    __tablename__ = "crm_connections"
    __table_args__ = (UniqueConstraint("org_id", "provider", name="uq_crm_org_provider"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    # "api_key" (native) | "nango" (OAuth via Nango) | "webhook" (e.g. Slack incoming webhook)
    method: Mapped[str] = mapped_column(String(16), nullable=False, default="api_key")
    # Fernet-encrypted API key / webhook URL. Never returned by the API.
    secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Non-secret connection details: {"location_id", "nango_connection_id", "nango_integration", "spreadsheet_id"…}
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Who/what it's connected as ("Acme Realty · jo@acme.com").
    account_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # {"log_calls": bool, "create_contacts": bool, "only_connected": bool,
    #  "speed_to_lead_agent_id": str|None, "speed_to_lead_since": iso str}
    settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="connected")  # connected | error
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class CrmSyncLog(Base):
    """One line per push/import/lead event, shown on the integration's activity list."""

    __tablename__ = "crm_sync_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("crm_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    call_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # call | import | new_lead | test
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # ok | error
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)


class CrmScan(Base):
    """A Radar scan of a connected CRM: people grouped into plays (see services/crm/radar.py)."""

    __tablename__ = "crm_scans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("crm_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    result: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)
