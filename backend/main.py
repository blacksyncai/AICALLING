"""
BlackSync — AI voice-agent platform API (FastAPI).

Start with:
    uvicorn main:app --reload --port 8000

Agent worker is a SEPARATE process:
    python agent_worker.py dev
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import create_all_tables
from app.routers import (
    account, activity, admin, agent_builder, agents, analytics, auth, billing, business_profile, calendar, calls, onboarding, campaigns, contacts, crm, integrations, radar, internal, lead_finder, meetings, phone_numbers, speech,
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
    from app.services import secret_store
    async with AsyncSessionLocal() as db:
        await secret_store.load_all(db)
    from app.services.playbooks import seed_playbooks
    async with AsyncSessionLocal() as db:
        try:
            await seed_playbooks(db)
        except Exception as exc:  # never block startup on the reference library
            log.warning("playbook_seed_failed", error=str(exc))
    from app.routers.business_profile import start_refresh_loop
    refresh_task = start_refresh_loop()
    from app.services.crm.sync import start_poll_loop
    crm_task = start_poll_loop()
    from app.services.outbound_call import fix_mislabeled_outcomes
    repair_task = asyncio.create_task(fix_mislabeled_outcomes() if settings.run_startup_jobs else asyncio.sleep(0))
    if settings.run_startup_jobs:
        from app.agent.templates import refresh_welcome_agents
        try:
            log.info("welcome_agents_refreshed", count=await refresh_welcome_agents())
        except Exception as exc:
            log.warning("welcome_agents_refresh_failed", error=str(exc))
    from app.services.outbound_call import start_orphan_sweeper
    sweeper_task = start_orphan_sweeper() if settings.run_startup_jobs else asyncio.create_task(asyncio.sleep(0))
    yield
    sweeper_task.cancel()
    refresh_task.cancel()
    crm_task.cancel()
    repair_task.cancel()
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

for r in (auth, account, activity, admin, agents, agent_builder, billing, business_profile, calendar, calls, onboarding, campaigns, contacts, lead_finder, meetings, phone_numbers, speech, analytics, crm, radar, integrations, public_api, search,
          settings_router, internal):
    app.include_router(r.router)
app.include_router(phone_numbers.admin_router)
app.include_router(billing.admin_router)


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
