"""
Async SQLAlchemy database setup.

Works with Postgres (asyncpg) in production and SQLite (aiosqlite) for
zero-setup local testing.
"""

import os
from collections.abc import AsyncGenerator

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def _normalize_url(url: str) -> str:
    # Hosted Postgres providers hand out postgres:// URLs; asyncpg needs the driver prefix.
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _normalize_url(settings.database_url)

_engine_kwargs: dict = {"echo": settings.sql_echo, "pool_pre_ping": True}
if os.environ.get("DB_NULL_POOL"):
    from sqlalchemy.pool import NullPool

    _engine_kwargs["poolclass"] = NullPool  # tests on Postgres: each event loop gets its own connections
elif not DATABASE_URL.startswith("sqlite"):
    _engine_kwargs.update(pool_size=10, max_overflow=20)

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an AsyncSession per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def _add_missing_columns(sync_conn) -> None:
    """
    Tiny forward-only migration: add any model column that an existing table is
    missing (e.g. a database created before agents became configurable).
    New columns are added as NULLable so existing rows stay valid.
    """
    insp = inspect(sync_conn)
    existing_tables = set(insp.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            col_type = col.type.compile(dialect=sync_conn.dialect)
            sync_conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {col_type}'))

    # create_all() only builds indexes together with brand-new tables, so add
    # report indexes to existing tables here (idempotent on SQLite and Postgres).
    if "call_logs" in existing_tables:
        sync_conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_call_logs_org_started ON call_logs (org_id, started_at)"
        ))

    # Pre-agent Postgres schemas used native enums + a required lead_id; relax
    # them so web/test calls (no lead) and the new outcome values fit.
    # Only when still needed: each ALTER takes an exclusive table lock, and running them on every boot
    # blocked (and once deadlocked) requests still being served by the previous instance during deploys.
    if sync_conn.dialect.name == "postgresql" and "call_logs" in existing_tables:
        cols = {t: {c["name"]: c for c in insp.get_columns(t)} for t in ("call_logs", "leads", "campaigns")
                if t in existing_tables}

        def is_varchar32(table: str, col: str) -> bool:
            c = cols.get(table, {}).get(col)
            return c is None or (getattr(c["type"], "length", None) == 32 and "CHAR" in str(c["type"]).upper())

        lead_id = cols["call_logs"].get("lead_id")
        if lead_id is not None and not lead_id["nullable"]:
            sync_conn.execute(text("ALTER TABLE call_logs ALTER COLUMN lead_id DROP NOT NULL"))
        for table, col in (("call_logs", "outcome"), ("call_logs", "status"), ("leads", "status"),
                           ("campaigns", "status")):
            if not is_varchar32(table, col):
                sync_conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE varchar(32) USING {col}::text"))


async def create_all_tables() -> None:
    """Create tables (and add new columns) on startup."""
    # Import models so metadata is populated
    from app.models import account, agent, billing, builder, calendar, call_log, campaign, crm, radar_automation, email_message, invite, lead, lead_finder, messaging, oauth, playbook, support  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
