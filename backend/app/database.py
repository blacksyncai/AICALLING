"""
Async SQLAlchemy database setup.

Works with Postgres (asyncpg) in production and SQLite (aiosqlite) for
zero-setup local testing.
"""

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
if not DATABASE_URL.startswith("sqlite"):
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
    if sync_conn.dialect.name == "postgresql" and "call_logs" in existing_tables:
        for stmt in (
            "ALTER TABLE call_logs ALTER COLUMN lead_id DROP NOT NULL",
            "ALTER TABLE call_logs ALTER COLUMN outcome TYPE varchar(32) USING outcome::text",
            "ALTER TABLE call_logs ALTER COLUMN status TYPE varchar(32) USING status::text",
            "ALTER TABLE leads ALTER COLUMN status TYPE varchar(32) USING status::text",
            "ALTER TABLE campaigns ALTER COLUMN status TYPE varchar(32) USING status::text",
        ):
            sync_conn.execute(text(stmt))


async def create_all_tables() -> None:
    """Create tables (and add new columns) on startup."""
    # Import models so metadata is populated
    from app.models import account, agent, builder, call_log, campaign, lead  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
