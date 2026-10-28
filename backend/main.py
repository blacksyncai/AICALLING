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
    number_registration, account, activity, admin, agent_builder, agents, analytics, auth, billing, business_profile, calendar, calls, onboarding, campaigns, contacts, crm, integrations, radar, radar_automations, internal, lead_finder, meetings, phone_numbers, speech,
    public_api, search, support,
    settings as settings_router,
)

log = structlog.get_logger(__name__)


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("pounce_starting", environment=settings.environment)
    await create_all_tables()
    log.info("database_tables_ready")
    try:
        from app.database import AsyncSessionLocal as _S
        from app.services.support.kb_seed import seed as _seed_help
        async with _S() as _db:
            await _seed_help(_db)
    except Exception as exc:
        log.warning("help_center_seed_failed", error=str(exc)[:200])
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
    from app.services.crm.automations import start_worker
    radar_task = start_worker() if settings.run_startup_jobs else asyncio.create_task(asyncio.sleep(0))
    from app.services import phone_pack
    pack_task = phone_pack.start_worker() if settings.run_startup_jobs else asyncio.create_task(asyncio.sleep(0))
    from app.services.call_alerts import start_worker as start_alerts
    alert_task = start_alerts() if settings.run_startup_jobs else asyncio.create_task(asyncio.sleep(0))
    from app.services.outbound_call import fix_mislabeled_outcomes
    from app.services.outbound_call import repair_contact_statuses

    async def _repairs():
        await fix_mislabeled_outcomes()
        await repair_contact_statuses()

    repair_task = asyncio.create_task(_repairs() if settings.run_startup_jobs else asyncio.sleep(0))
    if settings.run_startup_jobs:
        from app.agent.templates import refresh_welcome_agents
        try:
            log.info("welcome_agents_refreshed", count=await refresh_welcome_agents())
        except Exception as exc:
            log.warning("welcome_agents_refresh_failed", error=str(exc))
    if settings.run_startup_jobs and settings.livekit_ready:
        from app.services.telephony import sync_inbound_numbers
        try:
            log.info("inbound_numbers_synced", count=await sync_inbound_numbers())
        except Exception as exc:
            log.warning("inbound_numbers_sync_failed", error=str(exc))
    if settings.run_startup_jobs and settings.livekit_ready and settings.bandwidth_ready:
        # Bandwidth hands answered calls to LiveKit: keep its inbound trunk + routing in place.
        try:
            from sqlalchemy import select as _select

            from app.database import AsyncSessionLocal
            from app.models.billing import PhoneNumber
            from app.services import bandwidth

            async with AsyncSessionLocal() as db:
                bw = (await db.execute(_select(PhoneNumber.number).where(
                    PhoneNumber.status == "active", PhoneNumber.carrier == "bandwidth"))).scalars().all()
            await bandwidth.ensure_bridge_trunk(list(bw) or await bandwidth.list_numbers())
            log.info("bandwidth_bridge_ready", numbers=len(bw))
        except Exception as exc:
            log.warning("bandwidth_bridge_failed", error=str(exc)[:200])
    if settings.run_startup_jobs:
        # Older Lead Finder contacts named the data vendor in their note; customers shouldn't see it.
        try:
            from sqlalchemy import update as _update

            from app.database import AsyncSessionLocal
            from app.models.lead import Lead
            async with AsyncSessionLocal() as db:
                await db.execute(_update(Lead).where(Lead.notes == "Saved from Lead Finder (DataSkip).")
                                 .values(notes="Saved from Lead Finder."))
                await db.commit()
        except Exception as exc:
            log.warning("lead_note_cleanup_failed", error=str(exc)[:200])
    from app.services.outbound_call import start_orphan_sweeper
    sweeper_task = start_orphan_sweeper() if settings.run_startup_jobs else asyncio.create_task(asyncio.sleep(0))
    from app.services.entitlements import start_expiry_sweeper
    expiry_task = start_expiry_sweeper() if settings.run_startup_jobs else asyncio.create_task(asyncio.sleep(0))
    from app.services.onboarding_emails import start_sweeper as start_followup_sweeper
    followup_task = start_followup_sweeper() if settings.run_startup_jobs else asyncio.create_task(asyncio.sleep(0))
    if settings.run_startup_jobs:
        from app.routers.campaigns import resume_running_campaigns
        try:
            await resume_running_campaigns()
        except Exception as exc:
            log.warning("campaign_resume_failed", error=str(exc)[:200])
    from app.services import twilio_recordings
    rec_task =(twilio_recordings.start_sweeper() if settings.run_startup_jobs and settings.recording_via_twilio
                else asyncio.create_task(asyncio.sleep(0)))
    from app.services.number_registration import start_worker as start_registration_worker
    registration_task = start_registration_worker() if settings.run_startup_jobs and settings.number_registration_worker_enabled else asyncio.create_task(asyncio.sleep(0))
    from app.services.caller_reputation import start_sweeper as start_reputation_sweeper
    reputation_task = start_reputation_sweeper() if settings.run_startup_jobs else asyncio.create_task(asyncio.sleep(0))
    from app.services.billing.subscriptions import start_helcim_sweeper
    helcim_task = start_helcim_sweeper() if settings.run_startup_jobs else asyncio.create_task(asyncio.sleep(0))
    from app.services.plivo_inventory import start_worker as start_plivo_inventory
    inventory_task = start_plivo_inventory() if settings.run_startup_jobs and settings.plivo_inventory_sync_enabled else asyncio.create_task(asyncio.sleep(0))
    yield
    inventory_task.cancel()
    helcim_task.cancel()
    reputation_task.cancel()
    registration_task.cancel()
    rec_task.cancel()
    followup_task.cancel()
    expiry_task.cancel()
    sweeper_task.cancel()
    refresh_task.cancel()
    crm_task.cancel()
    radar_task.cancel()
    pack_task.cancel()
    alert_task.cancel()
    repair_task.cancel()
    log.info("pounce_shutting_down")


# ── App ───────────────────────────────────────────────────────────────────────

from fastapi.responses import JSONResponse  # noqa: E402

from app.services.entitlements import PlanLimit  # noqa: E402

app = FastAPI(
    title="BlackSync API",
    description="Build, test and deploy AI voice agents that call your leads.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.exception_handler(PlanLimit)
async def _plan_limit(_request, exc: PlanLimit):
    """Something the account's plan doesn't include — a 402 with an upgrade suggestion the UI can show."""
    return JSONResponse(status_code=402, content={"detail": exc.detail()})


from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402
from fastapi.exception_handlers import http_exception_handler  # noqa: E402

from app.services.public_errors import public_detail  # noqa: E402


@app.exception_handler(StarletteHTTPException)
async def _public_http_error(request, exc: StarletteHTTPException):
    """Customers never see setting names or internal vendors in errors; we log the real text."""
    shown = public_detail(request.url.path, exc.detail)
    if shown != exc.detail:
        structlog.get_logger("errors").warning("error_hidden", path=request.url.path, detail=str(exc.detail)[:500])
        exc = StarletteHTTPException(status_code=exc.status_code, detail=shown, headers=exc.headers)
    return await http_exception_handler(request, exc)

# ── CORS ──────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

for r in (number_registration, auth, account, activity, admin, agents, agent_builder, billing, business_profile, calendar, calls, onboarding, campaigns, contacts, lead_finder, meetings, phone_numbers, speech, analytics, crm, radar, radar_automations, integrations, public_api, search, support,
          settings_router, internal):
    app.include_router(r.router)
app.include_router(phone_numbers.admin_router)
app.include_router(billing.admin_router)
app.include_router(support.admin_router)
from app.routers import admin_emails  # noqa: E402
app.include_router(admin_emails.router)
from app.routers import bandwidth_hooks  # noqa: E402
app.include_router(bandwidth_hooks.router)
from app.routers import resend_hooks  # noqa: E402
app.include_router(resend_hooks.router)
from app.routers import mcp, oauth  # noqa: E402
app.include_router(oauth.router)
app.include_router(oauth.well_known)
app.include_router(mcp.router)


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

from app.routers import call_alerts  # noqa: E402
app.include_router(call_alerts.router)
app.include_router(call_alerts.admin_router)
