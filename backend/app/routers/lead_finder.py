"""
Lead Finder router — property-owner lookups (DataSkip): single addresses and
bulk CSVs of addresses, paid with lead-lookup credits (separate from calling
credits), lookup history, exports and "Save as lead".

Everything is scoped to the caller's organization. Contact details only leave
the server in responses to that organization's signed-in members.
"""

from __future__ import annotations

import asyncio
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select, update

from app.config import settings
from app.models.lead import Lead
from app.models.lead_finder import LookupBatch, PropertyLookup
from app.services import lead_finder as lf
from app.services.billing import lookups as pay
from app.services.auth import Context, CtxDep, DbDep
from app.services.contacts import normalize_phone

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/lead-finder", tags=["lead_finder"])

BATCH_STALE = timedelta(minutes=10)


class LookupRequest(BaseModel):
    street: str = Field(default="", max_length=300)
    city: str = Field(default="", max_length=120)
    state: str = Field(default="", max_length=40)
    zip: str = Field(default="", max_length=12)
    # The per-lookup price the customer confirmed (needed once the free lookups are used up).
    expected_price_cents: int | None = None


class BatchStart(BaseModel):
    expected_price_cents: int | None = None


class ParseRequest(BaseModel):
    text: str = Field(max_length=400)


class BatchUpload(BaseModel):
    filename: str = Field(default="addresses.csv", max_length=255)
    text: str = Field(max_length=lf.MAX_CSV_BYTES)


def _iso(d: datetime | None) -> str | None:
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()


def lookup_to_dict(r: PropertyLookup, full: bool = False) -> dict:
    d = {
        "id": str(r.id),
        "address": {"street": r.street, "city": r.city, "state": r.state, "zip": r.zip},
        "status": r.status,
        "found": r.found,
        "owner_name": r.owner_name if r.scrubbed_at is None else None,
        "lead_id": str(r.lead_id) if r.lead_id else None,
        "deleted": r.scrubbed_at is not None,
        "batch_id": str(r.batch_id) if r.batch_id else None,
        "row": r.row_number,
        "phones": len((r.result or {}).get("phones") or []) if r.scrubbed_at is None else 0,
        "error": r.error if r.status == "failed" else None,
        "created_at": _iso(r.created_at),
    }
    if full:
        d["result"] = r.result if r.scrubbed_at is None else None
    return d


def batch_to_dict(b: LookupBatch, valid: int | None = None) -> dict:
    return {
        "id": str(b.id), "filename": b.filename, "status": b.status,
        "total_rows": b.total_rows, "valid": valid if valid is not None else len(b.rows or []),
        "invalid": b.invalid or [], "processed": b.processed, "matched": b.matched, "no_match": b.no_match,
        "failed": b.failed, "cached": b.cached, "credits_used": b.credits_used, "error": b.error,
        "pay_source": b.pay_source, "unit_cents": b.unit_cents, "charged_cents": b.charged_cents or 0,
        "created_at": _iso(b.created_at), "finished_at": _iso(b.finished_at),
    }


async def usage_payload(db, ctx: Context) -> dict:
    await db.refresh(ctx.org, ["lead_credits_balance", "lead_credits_unlimited", "lead_finder_enabled"])
    st = await pay.status(db, ctx.org)
    return {
        "enabled": lf.enabled(ctx.org),
        "configured": bool(settings.skiptrace_api_key),
        "credits": lf.credits_of(ctx.org),
        "unlimited": lf.unlimited(ctx.org),
        "retention_days": settings.lead_finder_retention_days,
        "free_daily": st["free_daily"], "free_remaining": st["free_remaining"],
        "balance_cents": st["balance_cents"], "price_cents": st["price_cents"],
        "paid_enabled": st["paid_enabled"], "policy": st["policy"],
    }


async def _purge_expired(db, org_id) -> None:
    """Retention: scrub contact data from lookups older than the configured period."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.lead_finder_retention_days)
    await db.execute(update(PropertyLookup).where(
        PropertyLookup.org_id == org_id, PropertyLookup.created_at < cutoff, PropertyLookup.scrubbed_at.is_(None),
        PropertyLookup.result.is_not(None),
    ).values(result=None, owner_name=None, scrubbed_at=datetime.now(timezone.utc)))
    await db.commit()


async def _get_lookup(db, ctx: Context, lookup_id: uuid.UUID) -> PropertyLookup:
    r = await db.get(PropertyLookup, lookup_id)
    if not r or r.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Lookup not found")
    return r


async def _get_batch(db, ctx: Context, batch_id: uuid.UUID) -> LookupBatch:
    b = await db.get(LookupBatch, batch_id)
    if not b or b.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Batch not found")
    return b


def _error(exc: lf.LookupError_, usage: dict | None = None) -> JSONResponse:
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
    body = {"detail": exc.message, "code": exc.code, **getattr(exc, "extra", {})}
    if usage is not None:
        body["usage"] = usage
    return JSONResponse(status_code=exc.status, content=body, headers=headers)


def _require_ready(ctx: Context) -> None:
    if not lf.enabled(ctx.org):
        raise HTTPException(status_code=403, detail="Lead Finder isn't enabled for this account.")


async def _cached(db, org_id, key: str) -> PropertyLookup | None:
    return (await db.execute(select(PropertyLookup).where(
        PropertyLookup.org_id == org_id, PropertyLookup.address_key == key,
        PropertyLookup.status == "completed", PropertyLookup.scrubbed_at.is_(None),
    ).order_by(PropertyLookup.created_at.desc()).limit(1))).scalar_one_or_none()


def _apply_result(row: PropertyLookup, data: dict) -> bool:
    """Store a provider result on a lookup row. Returns whether an owner was found."""
    found = data.get("found") is True
    result = lf.normalize_result(data) if found else None
    try:
        charged = float(data.get("charged") or 0)
    except (TypeError, ValueError):
        charged = 0.0
    row.status, row.found, row.charged, row.result = "completed", found, charged, result
    row.owner_name = (result["contact"]["full_name"] or None) if result else None
    row.completed_at = datetime.now(timezone.utc)
    return found


# ── Usage and parsing ─────────────────────────────────────────────────────────


@router.get("/usage")
async def get_usage(ctx: CtxDep, db: DbDep):
    return await usage_payload(db, ctx)


@router.post("/parse")
async def parse_address(body: ParseRequest, _: CtxDep):
    """Split a pasted full address into fields. Free — never calls DataSkip."""
    return lf.parse_full_address(body.text)


# ── Single lookups ────────────────────────────────────────────────────────────


@router.post("/lookups")
async def create_lookup(body: LookupRequest, ctx: CtxDep, db: DbDep):
    """Look up one address. Saved results are returned free; a new owner found uses 1 lookup credit."""
    _require_ready(ctx)
    try:
        addr = lf.validate_address(body.street, body.city, body.state, body.zip)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    key = lf.address_key(addr["street"], addr["city"], addr["state"], addr["zip"])

    await _purge_expired(db, ctx.org.id)
    cached = await _cached(db, ctx.org.id, key)
    if cached:
        return {"lookup": lookup_to_dict(cached, full=True), "cached": True, "usage": await usage_payload(db, ctx)}

    try:
        lf.throttle(ctx.user.id)
    except lf.LookupError_ as exc:
        return _error(exc)
    if not settings.skiptrace_api_key:
        log.warning("lead_finder_not_configured")
        return _error(lf.LookupError_(503, "auth", "Property lookup is temporarily unavailable. Please try again later."))

    try:
        row = await lf.start_lookup(db, ctx.org, ctx.user.id, addr, key, body.expected_price_cents)
    except lf.LookupError_ as exc:
        return _error(exc, await usage_payload(db, ctx))

    try:
        data = await lf.call_dataskip(addr)
    except lf.LookupError_ as exc:
        row.status, row.error_code, row.error = "failed", exc.code, exc.message
        row.completed_at = datetime.now(timezone.utc)
        await pay.release(db, ctx.org, row.pay_source, 1, row.charge_cents or 0)
        row.charge_cents = 0
        await db.commit()
        log.warning("lead_finder_lookup_failed", org_id=str(ctx.org.id), lookup_id=str(row.id), code=exc.code)
        return _error(exc, await usage_payload(db, ctx))
    except Exception:
        row.status, row.error_code, row.error = "failed", "internal", "Unexpected error"
        await pay.release(db, ctx.org, row.pay_source, 1, row.charge_cents or 0)
        row.charge_cents = 0
        await db.commit()
        log.exception("lead_finder_lookup_crashed", org_id=str(ctx.org.id), lookup_id=str(row.id))
        raise HTTPException(status_code=502, detail="Something went wrong with the lookup. Please try again.")

    found = _apply_result(row, data)
    policy = await pay.settings_store.get(db, "lookup_charge_policy")
    keep = 1 if pay.charged(policy, found) else 0
    row.charge_cents = await pay.settle(db, ctx.org, row.pay_source, row.charge_cents or 0, held=1, charge_n=keep,
                                        note="Property lookup", user_id=ctx.user.id,
                                        lookup_id=row.id)
    row.credits = keep if row.pay_source == "credit" else 0
    await db.commit()
    log.info("lead_finder_lookup", org_id=str(ctx.org.id), user_id=str(ctx.user.id), lookup_id=str(row.id),
             found=found, charged=row.charged)
    return {"lookup": lookup_to_dict(row, full=True), "cached": False, "usage": await usage_payload(db, ctx)}


@router.get("/lookups")
async def list_lookups(ctx: CtxDep, db: DbDep, limit: int = 25):
    """Recent single-address lookups (bulk results live under their batch)."""
    await _purge_expired(db, ctx.org.id)
    rows = (await db.execute(select(PropertyLookup).where(
        PropertyLookup.org_id == ctx.org.id, PropertyLookup.status == "completed", PropertyLookup.batch_id.is_(None),
    ).order_by(PropertyLookup.created_at.desc()).limit(max(1, min(limit, 100))))).scalars().all()
    return {"items": [lookup_to_dict(r) for r in rows]}


@router.get("/lookups/{lookup_id}")
async def get_lookup(lookup_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    """A stored result. Never calls DataSkip and never uses credits."""
    return lookup_to_dict(await _get_lookup(db, ctx, lookup_id), full=True)


@router.delete("/lookups/{lookup_id}", status_code=204)
async def delete_lookup(lookup_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    """Delete the stored contact details (credits already used aren't returned)."""
    r = await _get_lookup(db, ctx, lookup_id)
    r.result, r.owner_name, r.scrubbed_at = None, None, datetime.now(timezone.utc)
    await db.commit()
    log.info("lead_finder_lookup_deleted", org_id=str(ctx.org.id), user_id=str(ctx.user.id), lookup_id=str(r.id))


@router.post("/lookups/{lookup_id}/save")
async def save_as_lead(lookup_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    """Save the owner as a contact in this organization (deduplicated). Never starts a campaign."""
    r = await _get_lookup(db, ctx, lookup_id)
    if r.scrubbed_at is not None or not r.found or not r.result:
        raise HTTPException(status_code=400, detail="There's no owner information to save for this lookup.")
    lead, created = await save_lookup_as_lead(db, ctx.org.id, r)
    await db.commit()
    log.info("lead_finder_saved", org_id=str(ctx.org.id), lookup_id=str(r.id), lead_id=str(lead.id), created=created)
    return {"lead_id": str(lead.id), "created": created}


def one_name(c: dict) -> str:
    return " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x)


async def save_lookup_as_lead(db, org_id, r: PropertyLookup) -> tuple[Lead, bool]:
    """Create or update the contact for a found owner. Caller commits."""
    res = r.result
    c, phones, emails = res["contact"], res["phones"], res["emails"]
    prop = c["property"] if c["property"]["address"] else {"address": r.street, "city": r.city, "state": r.state, "zip": r.zip}
    name = c["full_name"] or one_name(c) or "Property owner"
    numbers = [normalize_phone(p["number"]) for p in phones]
    key = r.address_key

    # Duplicate check: same org and any shared phone, or same property address and owner name.
    conds = [Lead.phone.in_([n for n in numbers if n])] if any(numbers) else []
    candidates = (await db.execute(select(Lead).where(Lead.org_id == org_id, or_(
        *(conds or [Lead.id.is_(None)]), Lead.intent_source == "dataskip")))).scalars().all()
    existing = None
    for lead in candidates:
        e = lead.enrichment or {}
        if (lead.phone and lead.phone in numbers) or (e.get("address_key") == key and (lead.name or "").lower() == name.lower()):
            existing = lead
            break

    primary = lf.primary_phone(phones)
    enrichment = {
        "source": "dataskip", "lookup_id": str(r.id), "address_key": key,
        "looked_up_at": _iso(r.completed_at or r.created_at), "saved_at": datetime.now(timezone.utc).isoformat(),
        # DNC flags exactly as DataSkip reported them (true / false / null = not reported). Not applied automatically.
        "phones": [{"number": p["number"], "type": p["type"], "provider_dnc": p.get("dnc")} for p in phones],
        "emails": emails, "property": prop, "mailing": c["mailing"],
    }
    custom = {"first_name": c["first_name"], "last_name": c["last_name"],
              "property_address": lf.one_line(prop), "mailing_address": lf.one_line(c["mailing"])}
    custom = {k: v for k, v in custom.items() if v}
    if existing:
        existing.enrichment = {**(existing.enrichment or {}), **enrichment}
        existing.custom_fields = {**(existing.custom_fields or {}), **custom}
        if not existing.email and emails:
            existing.email = emails[0]
        lead, created = existing, False
    else:
        lead = Lead(
            id=uuid.uuid4(), org_id=org_id, name=name[:255], company="",
            phone=primary["number"] if primary else "", email=emails[0] if emails else "",
            status="new", intent_source="dataskip", tags=["lead-finder"], custom_fields=custom,
            enrichment=enrichment, notes="Saved from Lead Finder.",
        )
        db.add(lead)
        created = True
    await db.flush()
    r.lead_id = lead.id
    return lead, created


# ── Bulk CSV ──────────────────────────────────────────────────────────────────


@router.post("/batches", status_code=201)
async def upload_batch(body: BatchUpload, ctx: CtxDep, db: DbDep):
    """Parse a CSV of addresses into a draft and say what it will cost. Nothing is looked up yet."""
    _require_ready(ctx)
    try:
        valid, invalid, total = lf.parse_address_csv(body.text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not valid:
        raise HTTPException(status_code=400, detail="No usable addresses found. Each row needs a street with a house number, a city and a state.")
    await _purge_expired(db, ctx.org.id)
    cached = 0
    for row in valid:
        row["cached"] = (await _cached(db, ctx.org.id, row["key"])) is not None
        cached += row["cached"]
    b = LookupBatch(org_id=ctx.org.id, user_id=ctx.user.id, filename=body.filename[:255], status="draft",
                    rows=valid, invalid=invalid[:200], total_rows=total)
    db.add(b)
    await db.commit()
    usage = await usage_payload(db, ctx)
    new = len(valid) - cached
    by_credits = usage["unlimited"] or usage["credits"] >= new
    price = usage["price_cents"]
    by_balance = price is not None and usage["balance_cents"] >= new * price
    return {**batch_to_dict(b), "valid": len(valid), "cached_rows": cached, "new_rows": new,
            "max_credits": new, "usage": usage, "pay_with": "credits" if by_credits else "balance",
            "price_cents": price, "max_total_cents": new * price if price is not None and not by_credits else 0,
            "enough_credits": by_credits or by_balance}


@router.post("/batches/{batch_id}/start", status_code=202)
async def start_batch(batch_id: uuid.UUID, background: BackgroundTasks, ctx: CtxDep, db: DbDep,
                      body: BatchStart | None = None):
    """Reserve payment for every new address (worst case) and run the lookups in the background."""
    _require_ready(ctx)
    b = await _get_batch(db, ctx, batch_id)
    if b.status != "draft":
        return batch_to_dict(b)
    if not settings.skiptrace_api_key:
        raise HTTPException(status_code=503, detail="Property lookup is temporarily unavailable. Please try again later.")
    rows = b.rows or []
    new_rows = [r for r in rows if not (await _cached(db, ctx.org.id, r["key"]))]
    try:
        source, unit = await pay.choose_bulk(db, ctx.org, len(new_rows), body.expected_price_cents if body else None)
    except pay.PaymentNeeded as exc:
        detail = exc.message
        if exc.code == "insufficient_balance":
            detail = (f"This file needs up to ${exc.extra['needed_cents'] / 100:,.2f} and your lookup balance is "
                      f"${exc.extra['balance_cents'] / 100:,.2f}. Add funds under Billing & Usage, or upload fewer addresses.")
        elif exc.code == "paid_disabled":
            detail = "Bulk lookups need prepaid lookup credits or a lookup balance, and neither is available yet."
        return JSONResponse(status_code=402, content={"detail": detail, "code": exc.code, **exc.extra})
    b.pay_source, b.unit_cents, b.charged_cents = source, unit, 0
    now = datetime.now(timezone.utc)
    for r in rows:
        cached = await _cached(db, ctx.org.id, r["key"])
        row = PropertyLookup(org_id=ctx.org.id, user_id=ctx.user.id, lookup_date=lf.today_utc(), address_key=r["key"],
                             street=r["street"], city=r["city"], state=r["state"], zip=r["zip"], batch_id=b.id,
                             row_number=r["row"], status="queued", credits=0)
        if cached:  # reuse the saved result — free
            row.status, row.found, row.result, row.owner_name = "completed", cached.found, cached.result, cached.owner_name
            row.charged, row.completed_at = 0.0, now
            b.cached += 1
            b.processed += 1
            b.matched += 1 if cached.found else 0
            b.no_match += 0 if cached.found else 1
        db.add(row)
    b.status, b.rows = "running", None
    await db.commit()
    background.add_task(run_batch, b.id, ctx.org.id, ctx.user.id)
    log.info("lead_finder_batch_started", org_id=str(ctx.org.id), batch_id=str(b.id), rows=len(rows), held=len(new_rows))
    return batch_to_dict(b)


async def run_batch(batch_id: uuid.UUID, org_id: uuid.UUID, user_id) -> None:
    """Background job: DataSkip bulk lookups in chunks of 100. Never raises; unused credits are always returned."""
    from app.database import AsyncSessionLocal
    from app.models.account import Organization

    async with AsyncSessionLocal() as db:
        b = await db.get(LookupBatch, batch_id)
        org = await db.get(Organization, org_id)
        if not b or not org:
            return
        source, unit = b.pay_source or "credit", b.unit_cents or 0
        policy = await pay.settings_store.get(db, "lookup_charge_policy")
        try:
            while True:
                queued = (await db.execute(select(PropertyLookup).where(
                    PropertyLookup.batch_id == b.id, PropertyLookup.status == "queued")
                    .order_by(PropertyLookup.row_number).limit(lf.BULK_CHUNK))).scalars().all()
                if not queued:
                    break
                for r in queued:
                    r.status = "reserved"
                await db.commit()
                results, error = None, None
                for attempt in range(3):  # only 429s are retried — those requests weren't processed
                    try:
                        results = await lf.call_dataskip_bulk([{"street": r.street, "city": r.city, "state": r.state, "zip": r.zip}
                                                               for r in queued])
                        break
                    except lf.LookupError_ as exc:
                        error = exc
                        if exc.code != "rate_limited" or attempt == 2:
                            break
                        await asyncio.sleep(min(exc.retry_after or 30, 120))
                if results is None:
                    for r in queued:
                        r.status, r.error_code = "failed", error.code if error else "internal"
                        r.error = "Lookup failed — no credit used"
                    b.failed += len(queued)
                    b.processed += len(queued)
                    await pay.release(db, org, source, len(queued), unit)
                    await db.commit()
                    log.warning("lead_finder_batch_chunk_failed", batch_id=str(b.id), code=error.code if error else None)
                    if error and error.code in ("auth", "balance"):
                        await _fail_remaining(db, b, org, "Property lookup is temporarily unavailable.")
                        break
                    continue
                found_n = 0
                for r, data in zip(queued, results):
                    if not isinstance(data, dict):
                        r.status, r.error_code, r.error = "failed", "provider_error", "Lookup failed — no credit used"
                        b.failed += 1
                        continue
                    found = _apply_result(r, data)
                    found_n += found
                    b.matched += found
                    b.no_match += not found
                    b.charged = (b.charged or 0) + (r.charged or 0)
                b.processed += len(queued)
                charge_rows = [r for r in queued if r.status == "completed" and pay.charged(policy, bool(r.found))]
                cents = await pay.settle(db, org, source, unit, held=len(queued), charge_n=len(charge_rows),
                                         note=f"Bulk lookup: {b.filename}", user_id=user_id, batch_id=b.id)
                for r in charge_rows:
                    r.charge_cents, r.pay_source = unit if source == "balance" else 0, source
                    r.credits = 1 if source == "credit" else 0
                if source == "credit":
                    b.credits_used += len(charge_rows)
                b.charged_cents = (b.charged_cents or 0) + cents
                await db.commit()
            if b.status == "running":
                b.status = "done"
            b.finished_at = datetime.now(timezone.utc)
            await db.commit()
            log.info("lead_finder_batch_done", org_id=str(org_id), batch_id=str(b.id), matched=b.matched,
                     credits=b.credits_used, failed=b.failed)
        except Exception:
            log.exception("lead_finder_batch_crashed", batch_id=str(batch_id))
            await db.rollback()
            b = await db.get(LookupBatch, batch_id)
            org = await db.get(Organization, org_id)
            if b and org:
                await _fail_remaining(db, b, org, "The lookup stopped unexpectedly. Nothing was charged for unfinished addresses.")


async def _fail_remaining(db, b: LookupBatch, org, message: str) -> None:
    """Mark every unfinished row failed, return their held credits, close the batch."""
    left = (await db.execute(select(PropertyLookup).where(
        PropertyLookup.batch_id == b.id, PropertyLookup.status.in_(("queued", "reserved"))))).scalars().all()
    for r in left:
        r.status, r.error_code, r.error = "failed", "interrupted", "Lookup failed — no credit used"
    b.failed += len(left)
    b.processed += len(left)
    await pay.release(db, org, b.pay_source or "credit", len(left), b.unit_cents or 0)
    b.status, b.error, b.finished_at = "failed", message, datetime.now(timezone.utc)
    await db.commit()


async def _row_count(db, b: LookupBatch) -> int:
    from sqlalchemy import func

    if b.status == "draft":
        return len(b.rows or [])
    return (await db.execute(select(func.count()).select_from(PropertyLookup)
                             .where(PropertyLookup.batch_id == b.id))).scalar_one()


async def _check_stale(db, ctx: Context, b: LookupBatch) -> None:
    updated = b.updated_at if b.updated_at.tzinfo else b.updated_at.replace(tzinfo=timezone.utc)
    if b.status == "running" and datetime.now(timezone.utc) - updated > BATCH_STALE:
        await _fail_remaining(db, b, ctx.org, "The lookup was interrupted. Nothing was charged for unfinished addresses.")


@router.get("/batches")
async def list_batches(ctx: CtxDep, db: DbDep):
    rows = (await db.execute(select(LookupBatch).where(
        LookupBatch.org_id == ctx.org.id, LookupBatch.status != "draft",
    ).order_by(LookupBatch.created_at.desc()).limit(25))).scalars().all()
    for b in rows:
        await _check_stale(db, ctx, b)
    return {"items": [batch_to_dict(b, await _row_count(db, b)) for b in rows]}


@router.get("/batches/{batch_id}")
async def get_batch(batch_id: uuid.UUID, ctx: CtxDep, db: DbDep, offset: int = 0, limit: int = 50):
    b = await _get_batch(db, ctx, batch_id)
    await _check_stale(db, ctx, b)
    rows = (await db.execute(select(PropertyLookup).where(PropertyLookup.batch_id == b.id)
                             .order_by(PropertyLookup.row_number).offset(max(0, offset)).limit(max(1, min(limit, 200)))
                             )).scalars().all()
    return {**batch_to_dict(b, await _row_count(db, b)), "rows": [lookup_to_dict(r) for r in rows],
            "usage": await usage_payload(db, ctx)}


@router.delete("/batches/{batch_id}", status_code=204)
async def delete_batch(batch_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    """Delete a draft, or scrub the contact details of a finished batch."""
    b = await _get_batch(db, ctx, batch_id)
    if b.status == "running":
        raise HTTPException(status_code=409, detail="Wait for this batch to finish before deleting it.")
    if b.status == "draft":
        await db.delete(b)
    else:
        await db.execute(update(PropertyLookup).where(PropertyLookup.batch_id == b.id).values(
            result=None, owner_name=None, scrubbed_at=datetime.now(timezone.utc)))
    await db.commit()


@router.post("/batches/{batch_id}/save-leads")
async def save_batch_leads(batch_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    """Save every found owner in the batch to Contacts (deduplicated). Never starts a campaign."""
    b = await _get_batch(db, ctx, batch_id)
    rows = (await db.execute(select(PropertyLookup).where(
        PropertyLookup.batch_id == b.id, PropertyLookup.found.is_(True), PropertyLookup.scrubbed_at.is_(None),
        PropertyLookup.lead_id.is_(None)))).scalars().all()
    created = updated = 0
    for r in rows:
        if not r.result:
            continue
        _, new = await save_lookup_as_lead(db, ctx.org.id, r)
        created += new
        updated += not new
    await db.commit()
    log.info("lead_finder_batch_saved", org_id=str(ctx.org.id), batch_id=str(b.id), created=created, updated=updated)
    return {"created": created, "updated": updated}


@router.get("/batches/{batch_id}/export")
async def export_batch(batch_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    """Results as CSV for this organization's members."""
    b = await _get_batch(db, ctx, batch_id)
    rows = (await db.execute(select(PropertyLookup).where(PropertyLookup.batch_id == b.id)
                             .order_by(PropertyLookup.row_number))).scalars().all()
    out = io.StringIO()
    raw = csv.writer(out)

    class _Safe:  # stop spreadsheet formula injection from provider data
        @staticmethod
        def writerow(vals):
            raw.writerow([("'" + v) if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v for v in vals])

    w = _Safe()
    w.writerow(["row", "street", "city", "state", "zip", "status", "owner_full_name", "owner_first_name",
                "owner_last_name", "mailing_address", "phone_1", "phone_1_type", "phone_2", "phone_2_type",
                "phone_3", "phone_3_type", "email_1", "email_2", "provider_dnc_numbers"])
    for r in rows:
        res = r.result if r.scrubbed_at is None else None
        status = "failed" if r.status == "failed" else ("found" if r.found else "no_match") if r.status == "completed" else r.status
        if not res:
            w.writerow([r.row_number, r.street, r.city, r.state, r.zip, status] + [""] * 13)
            continue
        c, phones, emails = res["contact"], res["phones"], res["emails"]
        ph = []
        for p in phones[:3]:
            ph += [p["display"], p["type"]]
        ph += [""] * (6 - len(ph))
        w.writerow([r.row_number, r.street, r.city, r.state, r.zip, status, c["full_name"], c["first_name"],
                    c["last_name"], lf.one_line(c["mailing"]), *ph, *(emails[:2] + [""] * (2 - len(emails[:2]))),
                    " ".join(p["display"] for p in phones if p.get("dnc") is True)])
    log.info("lead_finder_batch_exported", org_id=str(ctx.org.id), user_id=str(ctx.user.id), batch_id=str(b.id))
    name = (b.filename.rsplit(".", 1)[0] or "lookup") + "-results.csv"
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
