"""
BlackSync — AI voice-agent platform API (FastAPI).

Start with:
    uvicorn main:app --reload --port 8000

Agent worker is a SEPARATE process:
    python agent_worker.py dev
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import create_all_tables
from app.routers import (
    account, admin, agent_builder, agents, analytics, auth, business_profile, calls, campaigns, contacts, integrations, internal, meetings,
    public_api, search,
    settings as settings_router,
)

log = structlog.get_logger(__name__)


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("pounce_starting", environment=settings.environment)
    await create_all_tables()
    log.info("database_tables_ready")
    from app.database import AsyncSessionLocal
    from app.services.accounts import bootstrap
    from app.services.auth import load_signing_key
    async with AsyncSessionLocal() as db:
        await load_signing_key(db)
        await bootstrap(db)
    from app.routers.business_profile import start_refresh_loop
    refresh_task = start_refresh_loop()
    yield
    refresh_task.cancel()
    log.info("pounce_shutting_down")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="BlackSync API",
    description="Build, test and deploy AI voice agents that call your leads.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

for r in (auth, account, admin, agents, agent_builder, business_profile, calls, campaigns, contacts, meetings, analytics, integrations, public_api, search,
          settings_router, internal):
    app.include_router(r.router)


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health", tags=["infra"])
async def health():
    return {
        "status": "ok",
        "service": "blacksync-api",
        "environment": settings.environment,
        "demo_mode": settings.demo_mode,
        "voice_ready": settings.voice_ready,
        "phone_ready": settings.phone_ready,
    }


@app.get("/", tags=["infra"])
async def root():
    return {"message": "BlackSync API — AI voice agents", "docs": "/docs"}
