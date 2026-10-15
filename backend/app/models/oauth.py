"""OAuth for the BlackSync connector (MCP) used by ChatGPT, Claude and other AI assistants.

BlackSync is both the authorization server and the resource server: clients register (dynamically or with a
client metadata document), the user approves access on blacksync.si, and the assistant gets short-lived access
tokens plus rotating refresh tokens. Only SHA-256 hashes of codes, tokens and client secrets are stored.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class OAuthClient(Base):
    __tablename__ = "oauth_clients"

    # A random id (dynamic registration) or the https URL of the client's metadata document.
    client_id: Mapped[str] = mapped_column(String(300), primary_key=True)
    client_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    redirect_uris: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # none | client_secret_post | client_secret_basic
    auth_method: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    secret_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="dcr")  # dcr | cimd
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class OAuthCode(Base):
    __tablename__ = "oauth_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(300), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    org_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    redirect_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    code_challenge: Mapped[str] = mapped_column(String(128), nullable=False)
    scope: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    resource: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OAuthToken(Base):
    """One connection (grant): the current access token and refresh token for a user + client."""

    __tablename__ = "oauth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    client_id: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    client_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # The account the user picked; empty until they have one (they can create it from the assistant).
    org_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    scope: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    resource: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    access_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    access_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    refresh_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The refresh token this one replaced: a retry with it (lost response) is answered once more, briefly.
    prev_refresh_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
