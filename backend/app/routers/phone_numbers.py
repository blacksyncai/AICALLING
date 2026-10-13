"""
Phone numbers per account.

Customers see their numbers, pick the default caller ID, and either buy a number
(when self-serve is on) or request one. BlackSync admins search, buy, import and
release numbers for any account.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi.responses import JSONResponse
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.config import settings
from app.models.account import Organization
from app.models.billing import BillingAudit, PhoneNumber, PhoneNumberRequest
from app.services import telephony
from app.services.auth import AdminDep, CtxDep, DbDep, ManagerDep
from app.services.billing import settings_store

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/phone-numbers", tags=["phone numbers"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


class NumberPatch(BaseModel):
    label: str | None = Field(default=None, max_length=100)
    is_default: bool | None = None


class NumberRequestIn(BaseModel):
    area_code: str = Field(default="", max_length=8)
    note: str = Field(default="", max_length=500)


class PurchaseIn(BaseModel):
    number: str
    label: str = Field(default="", max_length=100)
    # The customer saw and accepted the $3.50/mo charge for a number beyond the plan's included ones.
    confirm_charge: bool = False


class AdminAssign(BaseModel):
    number: str
    mode: str = Field(pattern="^(purchase|import)$")
    label: str = Field(default="", max_length=100)
    request_id: uuid.UUID | None = None


class TelephonySettings(BaseModel):
    self_serve_numbers: bool | None = None
    max_numbers_per_org: int | None = Field(default=None, ge=0, le=100)


def _request_to_dict(r: PhoneNumberRequest) -> dict:
    return {"id": str(r.id), "area_code": r.area_code, "note": r.note, "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None}


def _err(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


async def _sync_billing(db, org_id: uuid.UUID) -> None:
    """Keep the additional-number add-on in step (never blocks the number change itself)."""
    from app.services.billing.subscriptions import sync_phone_quantity

    try:
        await sync_phone_quantity(db, org_id)
    except Exception as exc:
        log.error("phone_quantity_sync_failed", org_id=str(org_id), error=str(exc))


async def _own_number(db, org_id: uuid.UUID, number_id: uuid.UUID) -> PhoneNumber:
    row = await db.get(PhoneNumber, number_id)
    if not row or row.org_id != org_id or row.status != "active":
        raise HTTPException(status_code=404, detail="Number not found")
    return row


async def _room_for_another(db, org_id: uuid.UUID) -> None:
    limit = int(await settings_store.get(db, "max_numbers_per_org") or 0)
    if len(await telephony.active_numbers(db, org_id)) >= limit:
        raise HTTPException(status_code=400, detail=f"This account already has the maximum of {limit} numbers.")


# ── Customer ──────────────────────────────────────────────────────────────────


@router.get("")
async def my_numbers(ctx: CtxDep, db: DbDep):
    numbers = await telephony.active_numbers(db, ctx.org.id)
    requests = (await db.execute(
        select(PhoneNumberRequest).where(PhoneNumberRequest.org_id == ctx.org.id)
        .order_by(PhoneNumberRequest.created_at.desc()).limit(20)
    )).scalars().all()
    from app.services.billing.subscriptions import phone_summary

    cfg = await settings_store.get_all(db)
    pricing = await phone_summary(db, ctx.org.id)
    from app.services import entitlements

    pricing["included_on_plan"] = await entitlements.included_numbers(db, ctx.org)
    return {
        "pricing": pricing,
        "numbers": [telephony.number_to_dict(n) for n in numbers],
        "requests": [_request_to_dict(r) for r in requests],
        "self_serve": bool(cfg["self_serve_numbers"]) and settings.twilio_ready,
        "max_numbers": int(cfg["max_numbers_per_org"] or 0),
        "recordings_enabled": settings.recordings_ready,
    }


@router.patch("/{number_id}")
async def update_number(number_id: uuid.UUID, body: NumberPatch, ctx: ManagerDep, db: DbDep):
    row = await _own_number(db, ctx.org.id, number_id)
    if body.label is not None:
        row.label = body.label.strip()
    if body.is_default:
        await telephony.set_default(db, row)
    await db.commit()
    return telephony.number_to_dict(row)


@router.post("/requests", status_code=201)
async def request_number(body: NumberRequestIn, ctx: ManagerDep, db: DbDep):
    area = body.area_code.strip()
    if area and (not area.isdigit() or len(area) != 3):
        raise HTTPException(status_code=400, detail="Area code must be 3 digits.")
    open_count = (await db.execute(select(func.count()).select_from(PhoneNumberRequest).where(
        PhoneNumberRequest.org_id == ctx.org.id, PhoneNumberRequest.status == "open"))).scalar_one()
    if open_count >= 3:
        raise HTTPException(status_code=400, detail="You already have open requests — we'll get to them shortly.")
    req = PhoneNumberRequest(org_id=ctx.org.id, area_code=area, note=body.note.strip(), created_by=ctx.user.id)
    db.add(req)
    await db.commit()
    log.info("phone_number_requested", org_id=str(ctx.org.id), area_code=area)
    return _request_to_dict(req)


async def _require_self_serve(db) -> None:
    if not settings.twilio_ready or not await settings_store.get(db, "self_serve_numbers"):
        raise HTTPException(status_code=403, detail="Request a number and we'll set it up for you.")


@router.get("/available")
async def available_numbers(ctx: ManagerDep, db: DbDep, area_code: str = ""):
    await _require_self_serve(db)
    try:
        return {"numbers": await telephony.search_available(area_code.strip())}
    except (telephony.TelephonyError, ValueError) as exc:
        raise _err(exc)


@router.post("/purchase", status_code=201)
async def purchase_number(body: PurchaseIn, ctx: ManagerDep, db: DbDep):
    await _require_self_serve(db)
    await _room_for_another(db, ctx.org.id)
    from app.services.billing.subscriptions import phone_summary

    # No plan: buy the number on its own ($3.50/mo) through Stripe Checkout; it's bought once paid.
    if not (await phone_summary(db, ctx.org.id))["subscribed"]:
        from app.services.billing import purchases

        try:
            url = await purchases.checkout_phone_number(db, ctx.org, ctx.user.id, telephony.normalize(body.number))
        except purchases.BillingError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        return JSONResponse(status_code=200, content={"checkout_url": url})
    from app.services.billing import purchases
    from app.services.billing.subscriptions import charge_for_new_number

    summary = await phone_summary(db, ctx.org.id)
    extra = summary["active"] >= summary["included"]
    if extra and not body.confirm_charge:
        raise HTTPException(status_code=409, detail={
            "code": "confirm_charge", "unit_cents": summary["unit_cents"], "included": summary["included"],
            "message": f"Your plan includes {summary['included']} number{'s' if summary['included'] != 1 else ''}. "
                       f"This one is ${summary['unit_cents'] / 100:.2f}/month, charged now (prorated) and on each renewal."})
    try:
        charged = await charge_for_new_number(db, ctx.org.id) if extra else False
    except purchases.BillingError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    try:
        row = await telephony.purchase(db, ctx.org.id, body.number, body.label)
    except (telephony.TelephonyError, ValueError) as exc:
        if charged:
            await _sync_billing(db, ctx.org.id)  # the number wasn't bought — take the add-on back down
        raise _err(exc)
    await _sync_billing(db, ctx.org.id)
    return telephony.number_to_dict(row)


# ── Admin ─────────────────────────────────────────────────────────────────────


@admin_router.get("/telephony")
async def telephony_status(_: AdminDep, db: DbDep):
    """Twilio + recording setup, and every number in the Twilio account with who has it."""
    out: dict = {
        "twilio_ready": settings.twilio_ready, "recordings_ready": settings.recordings_ready,
        "trunk_sid": "", "trunk_error": "", "owned": [], "owned_error": "",
        "settings": {k: v for k, v in (await settings_store.get_all(db)).items()
                     if k in ("self_serve_numbers", "max_numbers_per_org")},
        "open_requests": [],
    }
    reqs = (await db.execute(
        select(PhoneNumberRequest, Organization.name).join(Organization, Organization.id == PhoneNumberRequest.org_id)
        .where(PhoneNumberRequest.status == "open").order_by(PhoneNumberRequest.created_at)
    )).all()
    out["open_requests"] = [{**_request_to_dict(r), "org_id": str(r.org_id), "org_name": name} for r, name in reqs]
    if not settings.twilio_ready:
        return out
    try:
        out["trunk_sid"] = await telephony.trunk_sid()
    except Exception as exc:
        out["trunk_error"] = str(exc)
    try:
        owned = await telephony.list_owned()
        assigned = {n.number: (n, name) for n, name in (await db.execute(
            select(PhoneNumber, Organization.name).join(Organization, Organization.id == PhoneNumber.org_id)
            .where(PhoneNumber.status == "active"))).all()}
        out["owned"] = [{
            **o, "on_trunk": bool(out["trunk_sid"]) and o["trunk_sid"] == out["trunk_sid"],
            "org_id": str(assigned[o["number"]][0].org_id) if o["number"] in assigned else None,
            "org_name": assigned[o["number"]][1] if o["number"] in assigned else None,
        } for o in owned]
    except Exception as exc:
        out["owned_error"] = str(exc)
    return out


@admin_router.patch("/telephony/settings")
async def update_telephony_settings(body: TelephonySettings, admin: AdminDep, db: DbDep):
    for key, value in body.model_dump(exclude_none=True).items():
        await settings_store.set_value(db, key, value, admin.id, reason="Phone number settings")
    await db.commit()
    return {k: v for k, v in (await settings_store.get_all(db)).items() if k in ("self_serve_numbers", "max_numbers_per_org")}


@admin_router.get("/phone-numbers/available")
async def admin_available(_: AdminDep, area_code: str = "", contains: str = ""):
    try:
        return {"numbers": await telephony.search_available(area_code.strip(), contains.strip())}
    except (telephony.TelephonyError, ValueError) as exc:
        raise _err(exc)


@admin_router.get("/orgs/{org_id}/phone-numbers")
async def admin_org_numbers(org_id: uuid.UUID, _: AdminDep, db: DbDep):
    if not await db.get(Organization, org_id):
        raise HTTPException(status_code=404, detail="Account not found")
    numbers = await telephony.active_numbers(db, org_id)
    reqs = (await db.execute(select(PhoneNumberRequest).where(
        PhoneNumberRequest.org_id == org_id, PhoneNumberRequest.status == "open"))).scalars().all()
    return {"numbers": [telephony.number_to_dict(n) for n in numbers],
            "requests": [_request_to_dict(r) for r in reqs], "twilio_ready": settings.twilio_ready}


@admin_router.post("/orgs/{org_id}/phone-numbers", status_code=201)
async def admin_assign(org_id: uuid.UUID, body: AdminAssign, admin: AdminDep, db: DbDep):
    if not await db.get(Organization, org_id):
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        if body.mode == "purchase":
            row = await telephony.purchase(db, org_id, body.number, body.label)
        else:
            row = await telephony.import_owned(db, org_id, body.number, body.label)
    except (telephony.TelephonyError, ValueError) as exc:
        raise _err(exc)
    if body.request_id:
        req = await db.get(PhoneNumberRequest, body.request_id)
        if req and req.org_id == org_id and req.status == "open":
            req.status = "fulfilled"
    db.add(BillingAudit(admin_id=admin.id, org_id=org_id, target="phone_numbers", previous="",
                        adjustment=body.mode, new=row.number, reason=f"Number {body.mode}d by admin"))
    await db.commit()
    await _sync_billing(db, org_id)
    return telephony.number_to_dict(row)


@admin_router.delete("/phone-numbers/{number_id}")
async def admin_release(number_id: uuid.UUID, admin: AdminDep, db: DbDep, return_to_twilio: bool = False):
    row = await db.get(PhoneNumber, number_id)
    if not row or row.status != "active":
        raise HTTPException(status_code=404, detail="Number not found")
    org_id, number = row.org_id, row.number
    try:
        await telephony.release(db, row, return_to_twilio=return_to_twilio)
    except telephony.TelephonyError as exc:
        raise _err(exc)
    db.add(BillingAudit(admin_id=admin.id, org_id=org_id, target="phone_numbers", previous=number,
                        adjustment="released" if return_to_twilio else "unassigned", new="",
                        reason="Released to Twilio" if return_to_twilio else "Unassigned by admin"))
    await db.commit()
    await _sync_billing(db, org_id)
    return {"ok": True}


@admin_router.post("/phone-number-requests/{request_id}/decline")
async def admin_decline(request_id: uuid.UUID, _: AdminDep, db: DbDep):
    req = await db.get(PhoneNumberRequest, request_id)
    if not req or req.status != "open":
        raise HTTPException(status_code=404, detail="Request not found")
    req.status = "declined"
    await db.commit()
    return _request_to_dict(req)
