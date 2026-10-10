"""
Business profile router — the organization's reusable business profile and
knowledge base (website analysis, rescans with reviewable changes, uploads,
manual edits and revision history). See docs/agent-builder.md.

Scheduled refresh: profiles with `auto_refresh_days` set are rescanned in the
background (changes land in `pending_changes`, never auto-applied). The loop is
started from main.py's lifespan:

    from app.routers.business_profile import start_refresh_loop
    refresh_task = start_refresh_loop()   # after bootstrap, before `yield`
    yield
    refresh_task.cancel()
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.builder import BusinessProfile, KnowledgeRevision
from app.services import website
from app.services.auth import CtxDep, DbDep
from app.services.knowledge import (
    clean_text, copy_knowledge, counts, empty_knowledge, get_profile, iter_items, new_item_id,
    normalize_knowledge,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/business-profile", tags=["business_profile"])

PROGRESS_LABELS = (
    "Exploring your website",
    "Understanding your business",
    "Identifying services and team details",
    "Preparing your knowledge base",
)
STALE_ANALYSIS = timedelta(minutes=5)
REFRESH_INTERVAL_S = 6 * 60 * 60
MAX_UPLOAD_CHARS = 200_000
NO_KEY_MSG = "Website analysis needs the OpenAI key to be configured."
JOB_FAILED_MSG = "Something went wrong while analyzing your website. Please try again."

_tasks: set[asyncio.Task] = set()


# ── Schemas ───────────────────────────────────────────────────────────────────


class ProfilePatch(BaseModel):
    name: str | None = None
    industry: str | None = None
    website: str | None = None
    description: str | None = None
    auto_refresh_days: int | None = None


class AnalyzeIn(BaseModel):
    website: str | None = None


class KnowledgeIn(BaseModel):
    sections: list[dict] = []


class UploadIn(BaseModel):
    filename: str = ""
    text: str = ""


class ChangeIds(BaseModel):
    ids: list[str] = []


# ── Helpers ───────────────────────────────────────────────────────────────────


def _aware(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _iso(d: datetime | None) -> str | None:
    d = _aware(d)
    return d.isoformat() if d else None


def profile_to_dict(p: BusinessProfile | None) -> dict:
    if p is None:
        return {
            "exists": False, "name": "", "industry": "", "website": "", "description": "",
            "status": "idle", "progress_step": None, "progress_label": None, "error": None,
            "pages": [], "knowledge": empty_knowledge(), "pending_changes": [],
            "auto_refresh_days": None, "scanned_at": None, "item_count": 0, "review_count": 0,
        }
    knowledge = normalize_knowledge(p.knowledge)
    item_count, review_count = counts(knowledge)
    step = p.progress_step if p.status == "analyzing" else None
    return {
        "exists": True,
        "name": p.name or "",
        "industry": p.industry or "",
        "website": p.website or "",
        "description": p.description or "",
        "status": p.status or "idle",
        "progress_step": step,
        "progress_label": PROGRESS_LABELS[step] if step is not None and 0 <= step < len(PROGRESS_LABELS) else None,
        "error": p.error,
        "pages": [{"url": pg.get("url", ""), "title": pg.get("title", "")} for pg in (p.pages or []) if isinstance(pg, dict)],
        "knowledge": knowledge,
        "pending_changes": list(p.pending_changes or []),
        "auto_refresh_days": p.auto_refresh_days,
        "scanned_at": _iso(p.scanned_at),
        "item_count": item_count,
        "review_count": review_count,
    }


async def _get_or_create(db, org_id: uuid.UUID) -> BusinessProfile:
    p = await get_profile(db, org_id)
    if p is None:
        p = BusinessProfile(org_id=org_id, knowledge=empty_knowledge(), pending_changes=[], pages=[])
        db.add(p)
        await db.flush()
    return p


def _save_revision(db, org_id: uuid.UUID, summary: str, knowledge: dict | None, user_id: uuid.UUID | None) -> None:
    db.add(KnowledgeRevision(org_id=org_id, summary=summary[:500], knowledge=copy_knowledge(knowledge),
                             created_by=user_id))


def _is_running(p: BusinessProfile) -> bool:
    if p.status != "analyzing":
        return False
    started = _aware(p.updated_at)
    return started is not None and datetime.now(timezone.utc) - started < STALE_ANALYSIS


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _validate_site(url: str) -> str:
    normalized = website.normalize_url(url)
    if not normalized:
        raise HTTPException(status_code=400, detail="Enter a website address like example.com.")
    if website.obviously_private(normalized):
        raise HTTPException(status_code=400, detail=website.MSG_NOT_PUBLIC)
    return normalized


# ── Background job ────────────────────────────────────────────────────────────


async def _set_step(org_id: uuid.UUID, step: int) -> None:
    async with AsyncSessionLocal() as db:
        p = await get_profile(db, org_id)
        if p and p.status == "analyzing":
            p.progress_step = step
            p.updated_at = datetime.now(timezone.utc)
            await db.commit()


async def run_analysis(org_id: uuid.UUID, mode: str = "analyze", user_id: uuid.UUID | None = None) -> None:
    """Crawl + extract. mode "analyze" replaces website facts; "rescan" proposes changes."""
    try:
        async with AsyncSessionLocal() as db:
            p = await get_profile(db, org_id)
            if p is None:
                return
            url = p.website

        await _set_step(org_id, 0)
        crawl = await website.crawl(url)

        profile_facts: dict = {}
        sections: dict[str, list[dict]] | None = None
        if crawl.pages and any(pg["text"] for pg in crawl.pages):
            await _set_step(org_id, 1)
            profile_facts, sections = await website.extract_facts(crawl.pages)
            await _set_step(org_id, 2)
            if not any(sections.values()) and crawl.status == "ready":
                crawl.status, crawl.error = "limited", website.MSG_LIMITED
        elif crawl.status == "ready":
            crawl.status, crawl.error = "limited", website.MSG_LIMITED
        await _set_step(org_id, 3)

        async with AsyncSessionLocal() as db:
            p = await get_profile(db, org_id)
            if p is None:
                return
            now = datetime.now(timezone.utc)
            if crawl.status == "failed":
                p.status, p.error, p.progress_step = "failed", crawl.error, None
                await db.commit()
                return
            p.pages = [{"url": pg["url"], "title": pg["title"]} for pg in crawl.pages]
            if sections is not None:
                if mode == "rescan":
                    p.pending_changes = website.diff_changes(p.knowledge, sections)
                else:
                    _save_revision(db, org_id, "Before website analysis", p.knowledge, user_id)
                    p.knowledge = website.replace_website_items(p.knowledge, sections)
                    p.pending_changes = []
                    if not p.name and profile_facts.get("name"):
                        p.name = profile_facts["name"][:255]
                    if not p.description and profile_facts.get("description"):
                        p.description = profile_facts["description"]
            p.status = crawl.status
            p.error = crawl.error
            p.progress_step = None
            p.scanned_at = now
            await db.commit()
    except Exception as exc:
        log.exception("business_profile_analysis_failed", org_id=str(org_id), error=str(exc)[:300])
        try:
            async with AsyncSessionLocal() as db:
                p = await get_profile(db, org_id)
                if p:
                    p.status, p.error, p.progress_step = "failed", JOB_FAILED_MSG, None
                    await db.commit()
        except Exception:
            pass


async def _start(db, ctx, mode: str) -> dict:
    if not settings.openai_api_key:
        raise HTTPException(status_code=400, detail=NO_KEY_MSG)
    p = await _get_or_create(db, ctx.org.id)
    if not p.website:
        raise HTTPException(status_code=400, detail="Add your website address first.")
    if _is_running(p):
        return profile_to_dict(p)
    p.status, p.progress_step, p.error = "analyzing", 0, None
    p.updated_at = datetime.now(timezone.utc)
    await db.commit()
    _spawn(run_analysis(ctx.org.id, mode, ctx.user.id))
    return profile_to_dict(p)


# ── Scheduled refresh ─────────────────────────────────────────────────────────


async def refresh_due_profiles() -> int:
    """Rescan profiles whose auto-refresh interval has passed. Returns how many were rescanned."""
    if not settings.openai_api_key:
        return 0
    now = datetime.now(timezone.utc)
    due: list[uuid.UUID] = []
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(BusinessProfile).where(BusinessProfile.auto_refresh_days.is_not(None), BusinessProfile.website != "")
        )).scalars().all()
        for p in rows:
            if _is_running(p) or not p.auto_refresh_days:
                continue
            scanned = _aware(p.scanned_at)
            if scanned is None or now - scanned >= timedelta(days=p.auto_refresh_days):
                p.status, p.progress_step, p.error = "analyzing", 0, None
                p.updated_at = now
                due.append(p.org_id)
        await db.commit()
    for org_id in due:
        await run_analysis(org_id, "rescan")
    return len(due)


async def _refresh_loop() -> None:
    while True:
        try:
            await asyncio.sleep(60)
            await refresh_due_profiles()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("knowledge_refresh_failed", error=str(exc)[:300])
        try:
            await asyncio.sleep(REFRESH_INTERVAL_S - 60)
        except asyncio.CancelledError:
            raise


def start_refresh_loop() -> asyncio.Task:
    """Start the every-6-hours auto-refresh loop (call from the app lifespan)."""
    task = asyncio.create_task(_refresh_loop())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("")
async def get_business_profile(ctx: CtxDep, db: DbDep):
    return profile_to_dict(await get_profile(db, ctx.org.id))


@router.put("")
async def update_business_profile(body: ProfilePatch, ctx: CtxDep, db: DbDep):
    fields = body.model_dump(exclude_unset=True)
    if "auto_refresh_days" in fields and fields["auto_refresh_days"] not in (None, 7, 30):
        raise HTTPException(status_code=400, detail="Auto-refresh must be off, weekly (7) or monthly (30).")
    p = await _get_or_create(db, ctx.org.id)
    if fields.get("name") is not None:
        p.name = clean_text(fields["name"], 255)
    if fields.get("industry") is not None:
        p.industry = clean_text(fields["industry"], 64)
    if fields.get("description") is not None:
        p.description = (fields["description"] or "").strip()[:5000]
    if fields.get("website") is not None:
        raw = fields["website"].strip()
        p.website = _validate_site(raw) if raw else ""
    if "auto_refresh_days" in fields:
        p.auto_refresh_days = fields["auto_refresh_days"]
    await db.commit()
    return profile_to_dict(p)


@router.post("/analyze")
async def analyze(body: AnalyzeIn, ctx: CtxDep, db: DbDep):
    if body.website is not None and body.website.strip():
        site = _validate_site(body.website)
        if not settings.openai_api_key:
            raise HTTPException(status_code=400, detail=NO_KEY_MSG)
        p = await _get_or_create(db, ctx.org.id)
        if not _is_running(p):
            p.website = site
    return await _start(db, ctx, "analyze")


@router.post("/rescan")
async def rescan(ctx: CtxDep, db: DbDep):
    return await _start(db, ctx, "rescan")


@router.put("/knowledge")
async def save_knowledge(body: KnowledgeIn, ctx: CtxDep, db: DbDep):
    p = await _get_or_create(db, ctx.org.id)
    previous = {item["id"]: item for _, item in iter_items(normalize_knowledge(p.knowledge))}
    out = empty_knowledge()
    by_key = {s["key"]: s for s in out["sections"]}
    seen: set[str] = set()
    for sec in body.sections:
        if not isinstance(sec, dict) or sec.get("key") not in by_key or not isinstance(sec.get("items"), list):
            continue
        for raw in sec["items"]:
            if not isinstance(raw, dict):
                continue
            text = clean_text(raw.get("text"))
            if not text:
                continue
            item_id = raw.get("id") if isinstance(raw.get("id"), str) else None
            prev = previous.get(item_id) if item_id else None
            if not item_id or item_id in seen or len(item_id) > 64:
                item_id = new_item_id()
            seen.add(item_id)
            if prev and prev["text"] == text:
                item = {**prev, "id": item_id, "needs_review": bool(raw.get("needs_review", prev["needs_review"]))}
            else:
                item = {"id": item_id, "text": text, "source_url": prev.get("source_url") if prev else None,
                        "origin": "manual", "needs_review": False}
            by_key[sec["key"]]["items"].append(item)
    _save_revision(db, ctx.org.id, "Edited knowledge base", p.knowledge, ctx.user.id)
    p.knowledge = out
    await db.commit()
    return profile_to_dict(p)


@router.post("/knowledge/upload")
async def upload_knowledge(body: UploadIn, ctx: CtxDep, db: DbDep):
    text = body.text or ""
    if len(text) > MAX_UPLOAD_CHARS:
        raise HTTPException(status_code=400, detail="That file is too large. Upload up to 200,000 characters of text.")
    if not text.strip():
        raise HTTPException(status_code=400, detail="That file doesn't contain any text.")
    filename = clean_text(body.filename, 200) or "document"
    sections = await website.extract_upload(filename, text)
    p = await _get_or_create(db, ctx.org.id)
    _save_revision(db, ctx.org.id, f"Before uploading {filename}", p.knowledge, ctx.user.id)
    knowledge = copy_knowledge(p.knowledge)
    existing = {website.norm_text(i["text"]) for _, i in iter_items(knowledge)}
    for sec in knowledge["sections"]:
        for item in sections.get(sec["key"], []):
            nt = website.norm_text(item["text"])
            if nt and nt not in existing:
                existing.add(nt)
                sec["items"].append(item)
    p.knowledge = knowledge
    await db.commit()
    return profile_to_dict(p)


def _select_changes(p: BusinessProfile, ids: list[str]) -> tuple[list[dict], list[dict]]:
    pending = list(p.pending_changes or [])
    if not ids:
        return pending, []
    wanted = set(ids)
    return [c for c in pending if c.get("id") in wanted], [c for c in pending if c.get("id") not in wanted]


@router.post("/changes/apply")
async def apply_changes(body: ChangeIds, ctx: CtxDep, db: DbDep):
    p = await _get_or_create(db, ctx.org.id)
    chosen, rest = _select_changes(p, body.ids)
    if chosen:
        _save_revision(db, ctx.org.id, f"Applied {len(chosen)} website update{'s' if len(chosen) != 1 else ''}",
                       p.knowledge, ctx.user.id)
        p.knowledge = website.apply_changes(p.knowledge, chosen)
    p.pending_changes = rest
    await db.commit()
    return profile_to_dict(p)


@router.post("/changes/dismiss")
async def dismiss_changes(body: ChangeIds, ctx: CtxDep, db: DbDep):
    p = await _get_or_create(db, ctx.org.id)
    _, rest = _select_changes(p, body.ids)
    p.pending_changes = rest
    await db.commit()
    return profile_to_dict(p)


@router.get("/revisions")
async def list_revisions(ctx: CtxDep, db: DbDep):
    rows = (await db.execute(
        select(KnowledgeRevision).where(KnowledgeRevision.org_id == ctx.org.id)
        .order_by(KnowledgeRevision.created_at.desc()).limit(30)
    )).scalars().all()
    return {"revisions": [{"id": str(r.id), "summary": r.summary, "created_at": _iso(r.created_at)} for r in rows]}


@router.post("/revisions/{revision_id}/restore")
async def restore_revision(revision_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    rev = await db.get(KnowledgeRevision, revision_id)
    if not rev or rev.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Revision not found")
    p = await _get_or_create(db, ctx.org.id)
    _save_revision(db, ctx.org.id, "Before restoring an earlier version", p.knowledge, ctx.user.id)
    p.knowledge = copy_knowledge(rev.knowledge)
    await db.commit()
    return profile_to_dict(p)
