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
    agents, analytics, calls, campaigns, leads, live, orange_slice, runs, settings as settings_router,
    twiml, webhook,
)

log = structlog.get_logger(__name__)


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("pounce_starting", environment=settings.environment)
    await create_all_tables()
    log.info("database_tables_ready")
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await agents.seed_default_agent(db)
    yield
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

app.include_router(agents.router)
app.include_router(analytics.router)
app.include_router(calls.router)
app.include_router(settings_router.router)
app.include_router(campaigns.router)
app.include_router(leads.router)
app.include_router(live.router)
app.include_router(orange_slice.router)
app.include_router(runs.router)
app.include_router(twiml.router)
app.include_router(webhook.router)


# ── Internal call outcome endpoint (used by agent fire-and-forget) ────────────
# Mounted under webhook router as POST /api/webhook/calls/{call_log_id}/outcome
# See app/routers/webhook.py


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
