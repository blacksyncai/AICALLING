"""
Lead Finder router — single-address property-owner lookups (DataSkip), the
organization's daily allowance, lookup history and "Save as lead".

Everything is scoped to the caller's organization. Contact details only leave
the server in responses to that organization's signed-in members.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select, update

from app.config import settings
from app.models.lead import Lead
from app.models.lead_finder import PropertyLookup
from app.services import lead_finder as lf
from app.services.auth import Context, CtxDep, DbDep
from app.services.contacts import normalize_phone

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/lead-finder", tags=["lead_finder"])


class LookupRequest(BaseModel):
    street: str = Field(default="", max_length=300)
    city: str = Field(default="", max_length=120)
    state: str = Field(default="", max_length=40)
    zip: str = Field(default="", max_length=12)


class ParseRequest(BaseModel):
    text: str = Field(max_length=400)


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
        "created_at": _iso(r.created_at),
    }
    if full:
        d["result"] = r.result if r.scrubbed_at is None else None
    return d


async def usage_payload(db, ctx: Context) -> dict:
    limit = lf.daily_limit(ctx.org)
    used = await lf.used_today(db, ctx.org.id)
    return {
        "enabled": lf.enabled(ctx.org),
        "configured": bool(settings.skiptrace_api_key),
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "resets_at": lf.next_reset().isoformat(),
        "retention_days": settings.lead_finder_retention_days,
    }


async def _purge_expired(db, org_id) -> None:
    """Retention: scrub contact data from lookups older than the configured period (usage rows stay)."""
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


def _error(exc: lf.LookupError_, usage: dict | None = None) -> JSONResponse:
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
    body = {"detail": exc.message, "code": exc.code}
    if usage is not None:
        body["usage"] = usage
    return JSONResponse(status_code=exc.status, content=body, headers=headers)


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/usage")
async def get_usage(ctx: CtxDep, db: DbDep):
    return await usage_payload(db, ctx)


@router.post("/parse")
async def parse_address(body: ParseRequest, _: CtxDep):
    """Split a pasted full address into fields. Free — never calls DataSkip."""
    return lf.parse_full_address(body.text)


@router.post("/lookups")
async def create_lookup(body: LookupRequest, ctx: CtxDep, db: DbDep):
    """Look up one address. Cached results are returned free; new ones use one unit of today's allowance."""
    if not lf.enabled(ctx.org):
        raise HTTPException(status_code=403, detail="Lead Finder isn't enabled for this account.")
    try:
        addr = lf.validate_address(body.street, body.city, body.state, body.zip)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    key = lf.address_key(addr["street"], addr["city"], addr["state"], addr["zip"])

    await _purge_expired(db, ctx.org.id)
    cached = (await db.execute(select(PropertyLookup).where(
        PropertyLookup.org_id == ctx.org.id, PropertyLookup.address_key == key,
        PropertyLookup.status == "completed", PropertyLookup.scrubbed_at.is_(None),
    ).order_by(PropertyLookup.created_at.desc()).limit(1))).scalar_one_or_none()
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
        row = await lf.reserve(db, ctx.org, ctx.user.id, addr, key)
    except lf.LookupError_ as exc:
        return _error(exc, await usage_payload(db, ctx))

    try:
        data = await lf.call_dataskip(addr)
    except lf.LookupError_ as exc:
        # Release the reservation: provider failures never use the allowance.
        row.status, row.error_code, row.error = "failed", exc.code, exc.message
        row.completed_at = datetime.now(timezone.utc)
        await db.commit()
        log.warning("lead_finder_lookup_failed", org_id=str(ctx.org.id), lookup_id=str(row.id), code=exc.code)
        return _error(exc, await usage_payload(db, ctx))
    except Exception:
        row.status, row.error_code, row.error = "failed", "internal", "Unexpected error"
        await db.commit()
        log.exception("lead_finder_lookup_crashed", org_id=str(ctx.org.id), lookup_id=str(row.id))
        raise HTTPException(status_code=502, detail="Something went wrong with the lookup. Please try again.")

    found = data.get("found") is True
    result = lf.normalize_result(data) if found else None
    try:
        charged = float(data.get("charged") or 0)
    except (TypeError, ValueError):
        charged = 0.0
    row.status, row.found, row.charged = "completed", found, charged
    row.result = result
    row.owner_name = (result["contact"]["full_name"] or None) if result else None
    row.completed_at = datetime.now(timezone.utc)
    await db.commit()
    log.info("lead_finder_lookup", org_id=str(ctx.org.id), user_id=str(ctx.user.id), lookup_id=str(row.id),
             found=found, charged=charged, phones=len(result["phones"]) if result else 0)
    return {"lookup": lookup_to_dict(row, full=True), "cached": False, "usage": await usage_payload(db, ctx)}


@router.get("/lookups")
async def list_lookups(ctx: CtxDep, db: DbDep, limit: int = 25):
    await _purge_expired(db, ctx.org.id)
    rows = (await db.execute(select(PropertyLookup).where(
        PropertyLookup.org_id == ctx.org.id, PropertyLookup.status == "completed",
    ).order_by(PropertyLookup.created_at.desc()).limit(max(1, min(limit, 100))))).scalars().all()
    return {"items": [lookup_to_dict(r) for r in rows]}


@router.get("/lookups/{lookup_id}")
async def get_lookup(lookup_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    """A stored result. Never calls DataSkip and never uses allowance."""
    return lookup_to_dict(await _get_lookup(db, ctx, lookup_id), full=True)


@router.delete("/lookups/{lookup_id}", status_code=204)
async def delete_lookup(lookup_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    """Delete the stored contact details. The usage record stays, so this doesn't restore allowance."""
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
    res = r.result
    c, phones, emails = res["contact"], res["phones"], res["emails"]
    prop = c["property"] if c["property"]["address"] else {"address": r.street, "city": r.city, "state": r.state, "zip": r.zip}
    name = c["full_name"] or one_name(c) or "Property owner"
    numbers = [normalize_phone(p["number"]) for p in phones]
    key = r.address_key

    # Duplicate check: same org and any shared phone, or same property address and owner name.
    conds = [Lead.phone.in_([n for n in numbers if n])] if any(numbers) else []
    candidates = (await db.execute(select(Lead).where(Lead.org_id == ctx.org.id, or_(
        *(conds or [Lead.id.is_(None)]), Lead.intent_source == "dataskip")))).scalars().all()
    existing = None
    for lead in candidates:
        e = lead.enrichment or {}
        if lead.phone and lead.phone in numbers:
            existing = lead
            break
        if e.get("address_key") == key and (lead.name or "").lower() == name.lower():
            existing = lead
            break

    primary = lf.primary_phone(phones)
    enrichment = {
        "source": "dataskip", "lookup_id": str(r.id), "address_key": key,
        "looked_up_at": _iso(r.completed_at or r.created_at), "saved_at": datetime.now(timezone.utc).isoformat(),
        "phones": [{"number": p["number"], "type": p["type"], "dnc": p["dnc"]} for p in phones],
        "emails": emails, "property": prop, "mailing": c["mailing"],
    }
    custom = {"first_name": c["first_name"], "last_name": c["last_name"],
              "property_address": lf.one_line(prop), "mailing_address": lf.one_line(c["mailing"])}
    custom = {k: v for k, v in custom.items() if v}
    created = existing is None
    if existing:
        lead = existing
        lead.enrichment = {**(lead.enrichment or {}), **enrichment}
        lead.custom_fields = {**(lead.custom_fields or {}), **custom}
        if not lead.email and emails:
            lead.email = emails[0]
        # Keep DNC indicators: if this lead's number is DNC-listed, never dial it.
        if any(p["dnc"] and normalize_phone(p["number"]) == lead.phone for p in phones):
            lead.do_not_call = True
    else:
        lead = Lead(
            id=uuid.uuid4(), org_id=ctx.org.id, name=name[:255], company="",
            phone=primary["number"] if primary else "", email=emails[0] if emails else "",
            status="new", intent_source="dataskip", tags=["lead-finder"], custom_fields=custom,
            enrichment=enrichment,
            # No number that isn't DNC-listed → never dialed by campaigns.
            do_not_call=primary is None,
            notes="Saved from Lead Finder (DataSkip)." + (" All returned numbers are DNC-listed." if phones and primary is None else ""),
        )
        db.add(lead)
    await db.flush()
    r.lead_id = lead.id
    await db.commit()
    log.info("lead_finder_saved", org_id=str(ctx.org.id), lookup_id=str(r.id), lead_id=str(lead.id), created=created)
    return {"lead_id": str(lead.id), "created": created}


def one_name(c: dict) -> str:
    return " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x)
