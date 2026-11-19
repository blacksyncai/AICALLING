"""
Track Desk API: the broker's live load board, load timelines, alerts, imports, stats and settings, plus the
webhook the account's texting provider posts driver replies to. Everything is scoped to the caller's account.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.models.call_log import CallLog
from app.models.track_desk import CheckCall, FreightLoad, TrackAlert, TrackDeskSettings
from app.services import track_desk as td
from app.services.auth import CtxDep, DbDep, ManagerDep

router = APIRouter(prefix="/api/track-desk", tags=["track-desk"])


async def _load(db, org_id, load_id: uuid.UUID) -> FreightLoad:
    load = await db.get(FreightLoad, load_id)
    if load is None or load.org_id != org_id:
        raise HTTPException(404, "Load not found.")
    return load


def _now() -> datetime:
    return datetime.now(timezone.utc)


FREIGHT = ("freight", "logistics", "trucking", "broker", "dispatch", "transport")


def _freight(org) -> bool:
    industry = (org.industry or "").lower()
    return any(w in industry for w in FREIGHT)


async def _enabled_json(db, org) -> dict:
    choice = await db.scalar(select(TrackDeskSettings.enabled).where(TrackDeskSettings.org_id == org.id))
    return {"enabled": _freight(org) if choice is None else bool(choice), "freight_account": _freight(org)}


@router.get("/enabled")
async def enabled(ctx: CtxDep, db: DbDep):
    """Whether this account shows Track Desk: on for freight/logistics accounts, else only when turned on in Settings."""
    return await _enabled_json(db, ctx.org)


class EnabledIn(BaseModel):
    enabled: bool


@router.put("/enabled")
async def set_enabled(body: EnabledIn, ctx: ManagerDep, db: DbDep):
    cfg = await td.get_settings(db, ctx.org)
    cfg.enabled = body.enabled
    if not body.enabled:
        cfg.paused = True  # hidden means no calls either
    elif cfg.paused and cfg.enabled:
        cfg.paused = False
    await db.commit()
    return await _enabled_json(db, ctx.org)


# ── Board ─────────────────────────────────────────────────────────────────────

@router.get("/loads")
async def list_loads(ctx: CtxDep, db: DbDep, status: str = Query("open"), q: str = Query("", max_length=80),
                     limit: int = Query(500, ge=1, le=1000)):
    stmt = select(FreightLoad).where(FreightLoad.org_id == ctx.org.id)
    if status == "open":
        stmt = stmt.where(FreightLoad.status.in_(td.OPEN))
    elif status != "all":
        stmt = stmt.where(FreightLoad.status == status)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(FreightLoad.external_id.ilike(like), FreightLoad.driver_name.ilike(like),
                              FreightLoad.pickup_city.ilike(like), FreightLoad.delivery_city.ilike(like),
                              FreightLoad.driver_phone.ilike(like), FreightLoad.shipper_name.ilike(like)))
    loads = (await db.execute(stmt.order_by(FreightLoad.updated_at.desc()).limit(limit))).scalars().all()
    far = datetime.max.replace(tzinfo=timezone.utc)
    loads = sorted(loads, key=lambda l: (td.SORT.get(l.status, 9), td._aware(l.delivery_start) or far))
    counts = dict((await db.execute(select(FreightLoad.status, func.count()).where(FreightLoad.org_id == ctx.org.id)
                                    .group_by(FreightLoad.status))).all())
    return {"items": [td.board_json(l) for l in loads], "counts": counts,
            "open_alerts": await db.scalar(select(func.count()).select_from(TrackAlert).where(
                TrackAlert.org_id == ctx.org.id, TrackAlert.acknowledged_at.is_(None))) or 0}


@router.get("/loads/{load_id}")
async def get_load(load_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    load = await _load(db, ctx.org.id, load_id)
    checks = (await db.execute(select(CheckCall).where(CheckCall.load_id == load.id)
                               .order_by(CheckCall.attempted_at.desc()))).scalars().all()
    alerts = (await db.execute(select(TrackAlert).where(TrackAlert.load_id == load.id)
                               .order_by(TrackAlert.sent_at.desc()))).scalars().all()
    calls = {c.id: c for c in (await db.execute(select(CallLog).where(
        CallLog.id.in_([c.call_log_id for c in checks if c.call_log_id])))).scalars()} if any(c.call_log_id for c in checks) else {}
    timeline = []
    for c in checks:
        item = td.check_json(c)
        call = calls.get(c.call_log_id)
        if call is not None:
            item["transcript"] = [t for t in (call.transcript or []) if t.get("role") in ("user", "assistant")]
            item["has_recording"] = bool(call.recording_key)
            item["duration_sec"] = call.duration_seconds
        timeline.append(item)
    return {"load": td.board_json(load), "timeline": timeline, "alerts": [td.alert_json(a, load) for a in alerts]}


class LoadEdit(BaseModel):
    driver_name: str | None = Field(None, max_length=255)
    driver_phone: str | None = Field(None, max_length=32)
    notes: str | None = Field(None, max_length=4000)
    sms_only: bool | None = None


@router.patch("/loads/{load_id}")
async def edit_load(load_id: uuid.UUID, body: LoadEdit, ctx: CtxDep, db: DbDep):
    load = await _load(db, ctx.org.id, load_id)
    if body.driver_phone is not None:
        phone = td._phone(body.driver_phone)
        if not phone:
            raise HTTPException(400, "That driver phone isn't a valid number.")
        if phone != load.driver_phone:
            load.driver_phone, load.do_not_call, load.unresponsive = phone, False, False
    for k in ("driver_name", "notes", "sms_only"):
        if getattr(body, k) is not None:
            setattr(load, k, getattr(body, k))
    cfg = await td.get_settings(db, ctx.org)
    if load.status not in td.CLOSED and load.next_check_at is None and not load.do_not_call:
        load.next_check_at, load.next_check_kind = td.plan_next_check(load, cfg, _now())
    await db.commit()
    return td.board_json(load)


@router.post("/loads/{load_id}/check-now")
async def check_now(load_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    load = await _load(db, ctx.org.id, load_id)
    if load.status in td.CLOSED:
        raise HTTPException(400, f"This load is {load.status}.")
    if load.do_not_call:
        raise HTTPException(400, "The driver asked not to be contacted about this load.")
    if load.round_state:
        raise HTTPException(409, "A check is already in progress on this load.")
    cfg = await td.get_settings(db, ctx.org)
    check = await td.start_round(db, ctx.org, cfg, load, _now(), kind="manual")
    await db.commit()
    return {"check": td.check_json(check), "load": td.board_json(load)}


async def _close(db, ctx, load_id, status: str):
    load = await _load(db, ctx.org.id, load_id)
    load.status, load.round_state, load.next_check_at, load.next_check_kind = status, None, None, ""
    if status == "delivered":
        load.delivered_at = load.delivered_at or _now()
    await db.commit()
    return td.board_json(load)


@router.post("/loads/{load_id}/mark-delivered")
async def mark_delivered(load_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    return await _close(db, ctx, load_id, "delivered")


@router.post("/loads/{load_id}/mark-cancelled")
async def mark_cancelled(load_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    return await _close(db, ctx, load_id, "cancelled")


@router.post("/loads/{load_id}/reopen")
async def reopen(load_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    load = await _load(db, ctx.org.id, load_id)
    cfg = await td.get_settings(db, ctx.org)
    load.status, load.delivered_at = "active", None
    await td.rescore(db, ctx.org, cfg, load, _now())
    await db.commit()
    return td.board_json(load)


class ManualCheckIn(BaseModel):
    location_text: str = Field("", max_length=255)
    eta: datetime | None = None
    loaded: str = Field("unknown", pattern="^(yes|no|unknown)$")
    delay_reason: str = Field("", max_length=255)
    notes: str = Field("", max_length=2000)
    delivered: bool = False


@router.post("/loads/{load_id}/manual-check-in")
async def manual_check_in(load_id: uuid.UUID, body: ManualCheckIn, ctx: CtxDep, db: DbDep):
    load = await _load(db, ctx.org.id, load_id)
    if load.status in td.CLOSED:
        raise HTTPException(400, f"This load is {load.status}.")
    cfg = await td.get_settings(db, ctx.org)
    now = _now()
    eta = td._aware(body.eta).astimezone(timezone.utc) if body.eta else None
    check = CheckCall(org_id=ctx.org.id, load_id=load.id, kind="manual", channel="manual", outcome="manual",
                      attempted_at=now, entered_by=ctx.user.email or "")
    db.add(check)
    await db.flush()
    info = td.CheckIn(location=body.location_text.strip(), loaded=body.loaded, eta=eta, delay_reason=body.delay_reason,
                      notes=body.notes, delivered=body.delivered, confidence="high")
    if not info.useful:
        raise HTTPException(400, "Add a location, an ETA or the loaded status.")
    load.round_state = None  # the broker's update ends any round in progress
    await td.apply_checkin(db, ctx.org, cfg, load, check, info, now, "")
    await db.commit()
    return td.board_json(load)


# ── Import ────────────────────────────────────────────────────────────────────

@router.post("/loads/import")
async def import_loads(ctx: CtxDep, db: DbDep, request: Request):
    """A CSV file (multipart field "file", optional "dry_run"), or a JSON load / list of loads.

    dry_run only reports what would be imported (the preview before importing).
    """
    cfg = await td.get_settings(db, ctx.org)
    dry_run = request.query_params.get("dry_run") in ("1", "true")
    if "multipart/form-data" in (request.headers.get("content-type") or ""):
        form = await request.form()
        upload = form.get("file")
        dry_run = dry_run or str(form.get("dry_run") or "").lower() in ("1", "true")
        if upload is None or isinstance(upload, str):
            raise HTTPException(400, "Attach the CSV as the file field.")
        raw = await upload.read()
        if len(raw) > 5_000_000:
            raise HTTPException(413, "That file is over 5 MB.")
        mapping = None
        if form.get("mapping"):
            import json

            try:
                mapping = {k: v for k, v in json.loads(str(form.get("mapping"))).items() if k in td._COLUMNS and v}
            except (ValueError, AttributeError) as exc:
                raise HTTPException(400, "The column mapping isn't valid.") from exc
        report = td.parse_loads_csv(raw.decode("utf-8-sig", errors="replace"), cfg.time_zone, mapping or None)
    else:
        try:
            records = td.json_rows((await request.body()).decode() or "[]")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        report = td.parse_rows(records, cfg.time_zone)
    if not report.rows and not report.errors:
        raise HTTPException(400, "No loads found. The first row must be the column headers.")
    mapped = dict(report.mapping)
    missing_cols = [td._LABELS[f] for f in td.REQUIRED if f not in mapped]
    if dry_run:
        dates = ("pickup_start", "pickup_end", "delivery_start", "delivery_end")
        return {"dry_run": True, "valid": len(report.rows), "errors": report.errors, "mapping": mapped,
                "fields": {f: {"label": td._LABELS.get(f, f.replace("_", " ")), "required": f in td.REQUIRED}
                           for f in td._COLUMNS},
                "missing_columns": missing_cols,
                "preview": [{**r, **{k: td._iso(r[k]) for k in dates}} for r in report.rows[:10]]}
    result = await td.import_loads(db, ctx.org, cfg, report)
    await td.ensure_agent(db, ctx.org, cfg)
    await db.commit()
    return {**result, "mapping": mapped}


@router.post("/loads")
async def add_loads(ctx: CtxDep, db: DbDep, request: Request):
    """One load (or a list) as JSON, for a TMS or a script. Same fields as the CSV columns."""
    return await import_loads(ctx, db, request)


# ── Alerts ────────────────────────────────────────────────────────────────────

@router.get("/alerts")
async def list_alerts(ctx: CtxDep, db: DbDep, include_acknowledged: bool = False, limit: int = Query(200, le=500)):
    stmt = select(TrackAlert, FreightLoad).join(FreightLoad, FreightLoad.id == TrackAlert.load_id).where(
        TrackAlert.org_id == ctx.org.id)
    if not include_acknowledged:
        stmt = stmt.where(TrackAlert.acknowledged_at.is_(None))
    rows = (await db.execute(stmt.order_by(TrackAlert.sent_at.desc()).limit(limit))).all()
    return {"items": [td.alert_json(a, l) for a, l in rows]}


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge(alert_id: uuid.UUID, ctx: CtxDep, db: DbDep):
    alert = await db.get(TrackAlert, alert_id)
    if alert is None or alert.org_id != ctx.org.id:
        raise HTTPException(404, "Alert not found.")
    alert.acknowledged_at, alert.acknowledged_by = _now(), ctx.user.email or ""
    await db.commit()
    return td.alert_json(alert)


@router.post("/alerts/acknowledge-all")
async def acknowledge_all(ctx: CtxDep, db: DbDep):
    rows = (await db.execute(select(TrackAlert).where(TrackAlert.org_id == ctx.org.id,
                                                      TrackAlert.acknowledged_at.is_(None)))).scalars().all()
    for a in rows:
        a.acknowledged_at, a.acknowledged_by = _now(), ctx.user.email or ""
    await db.commit()
    return {"acknowledged": len(rows)}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def stats(ctx: CtxDep, db: DbDep, week: str | None = Query(None, description="Any date in the week, YYYY-MM-DD")):
    cfg = await td.get_settings(db, ctx.org)
    ref = datetime.fromisoformat(week).replace(tzinfo=td._zone(cfg.time_zone)) if week else _now()
    start = td.week_start(ref, cfg.time_zone)
    end = start + timedelta(days=7)
    in_week = (CheckCall.org_id == ctx.org.id, CheckCall.attempted_at >= start, CheckCall.attempted_at < end)
    attempts = dict((await db.execute(select(CheckCall.outcome, func.count()).where(*in_week)
                                      .group_by(CheckCall.outcome))).all())
    calls = sum(v for k, v in attempts.items() if k in ("answered", "no_answer", "voicemail", "failed"))
    answered_calls = attempts.get("answered", 0)
    texts_sent = attempts.get("sms_sent", 0)
    replies = attempts.get("sms_reply", 0)
    checkins = await db.scalar(select(func.count()).select_from(CheckCall).where(
        *in_week, CheckCall.outcome.in_(("answered", "sms_reply", "manual")),
        or_(CheckCall.location_text != "", CheckCall.eta_at.isnot(None), CheckCall.eta_text != "",
            CheckCall.loaded != "unknown"))) or 0
    automated = await db.scalar(select(func.count()).select_from(CheckCall).where(
        *in_week, CheckCall.outcome.in_(("answered", "sms_reply")))) or 0
    tracked = await db.scalar(select(func.count(func.distinct(CheckCall.load_id))).where(*in_week)) or 0
    alerts = dict((await db.execute(select(TrackAlert.kind, func.count()).where(
        TrackAlert.org_id == ctx.org.id, TrackAlert.sent_at >= start, TrackAlert.sent_at < end)
        .group_by(TrackAlert.kind))).all())
    # Late loads we flagged before their delivery window closed: the broker heard first.
    early = await db.scalar(select(func.count(func.distinct(TrackAlert.load_id))).select_from(TrackAlert)
                            .join(FreightLoad, FreightLoad.id == TrackAlert.load_id).where(
        TrackAlert.org_id == ctx.org.id, TrackAlert.kind == "late", TrackAlert.sent_at >= start,
        TrackAlert.sent_at < end, or_(FreightLoad.delivery_end.is_(None), TrackAlert.sent_at < FreightLoad.delivery_end))) or 0
    delivered = await db.scalar(select(func.count()).select_from(FreightLoad).where(
        FreightLoad.org_id == ctx.org.id, FreightLoad.delivered_at >= start, FreightLoad.delivered_at < end)) or 0
    attempts_total = calls + texts_sent
    return {
        "week_start": start.isoformat(), "week_end": end.isoformat(),
        "loads_tracked": tracked, "loads_added": await td.loads_this_week(db, ctx.org.id, cfg.time_zone, ref),
        "loads_delivered": delivered, "check_ins": checkins, "calls": calls, "calls_answered": answered_calls,
        "texts_sent": texts_sent, "text_replies": replies, "attempts": attempts_total,
        "answer_rate": round((answered_calls + replies) / attempts_total, 3) if attempts_total else None,
        "late_flagged": alerts.get("late", 0), "late_flagged_early": early,
        "unresponsive": alerts.get("unresponsive", 0), "at_risk": alerts.get("at_risk", 0),
        "hours_saved": round(automated * 5 / 60, 1),  # ~5 minutes of someone dialing per automated check-in
        "plan": cfg.plan, "plan_limit": td.plan_limit(cfg),
    }


# ── Settings ──────────────────────────────────────────────────────────────────

def _settings_json(cfg: TrackDeskSettings, has_texting: bool) -> dict:
    from app.config import settings

    base = (settings.app_url or "https://blacksync.si").rstrip("/")
    return {
        "broker_name": cfg.broker_name, "agent_name": cfg.agent_name, "agent_id": str(cfg.agent_id) if cfg.agent_id else None,
        "caller_number": cfg.caller_number, "timezone": cfg.time_zone, "check_interval_hours": cfg.check_interval_hours,
        "quiet_start_hour": cfg.quiet_start_hour, "quiet_end_hour": cfg.quiet_end_hour,
        "call_late_loads_in_quiet_hours": cfg.call_late_loads_in_quiet_hours, "sms_only": cfg.sms_only,
        "alert_emails": cfg.alert_emails or [], "alert_phone": cfg.alert_phone, "plan": cfg.plan,
        "plans": td.PLANS, "plan_limit": td.plan_limit(cfg), "paused": cfg.paused, "texting_connected": has_texting,
        "sms_webhook_url": f"{base}/api/track-desk/sms/{cfg.sms_token}",
    }


@router.get("/settings")
async def get_settings(ctx: CtxDep, db: DbDep):
    cfg = await td.get_settings(db, ctx.org)
    await db.commit()
    return _settings_json(cfg, await td._sms_connection(db, ctx.org.id) is not None)


class SettingsIn(BaseModel):
    broker_name: str | None = Field(None, max_length=255)
    agent_name: str | None = Field(None, max_length=64)
    caller_number: str | None = Field(None, max_length=32)
    timezone: str | None = Field(None, max_length=64)
    check_interval_hours: int | None = Field(None, ge=2, le=4)
    quiet_start_hour: int | None = Field(None, ge=0, le=23)
    quiet_end_hour: int | None = Field(None, ge=0, le=23)
    call_late_loads_in_quiet_hours: bool | None = None
    sms_only: bool | None = None
    alert_emails: list[str] | None = Field(None, max_length=10)
    alert_phone: str | None = Field(None, max_length=32)
    paused: bool | None = None


@router.patch("/settings")
async def update_settings(body: SettingsIn, ctx: ManagerDep, db: DbDep):
    from app.services import telephony

    cfg = await td.get_settings(db, ctx.org)
    data = body.model_dump(exclude_none=True)
    if "timezone" in data:
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(data["timezone"])
        except Exception as exc:
            raise HTTPException(400, "Unknown time zone.") from exc
        cfg.time_zone = data.pop("timezone")
    if data.get("caller_number"):
        number = td._phone(data["caller_number"])
        if not number or not any(n.number == number for n in await telephony.active_numbers(db, ctx.org.id)):
            raise HTTPException(400, "Pick one of this account's phone numbers.")
        data["caller_number"] = number
    if data.get("alert_phone"):
        data["alert_phone"] = td._phone(data["alert_phone"]) or ""
        if not data["alert_phone"]:
            raise HTTPException(400, "That alert phone isn't a valid number.")
    if "alert_emails" in data:
        data["alert_emails"] = [e.strip().lower() for e in data["alert_emails"] if "@" in e][:10]
    for k, v in data.items():
        setattr(cfg, k, v)
    agent = await td.ensure_agent(db, ctx.org, cfg)
    agent.caller_number = cfg.caller_number or None
    await db.commit()
    return _settings_json(cfg, await td._sms_connection(db, ctx.org.id) is not None)


# ── Driver text replies (the texting provider's inbound webhook) ──────────────

@router.post("/sms/{token}", include_in_schema=False)
async def sms_reply(token: str, request: Request, db: DbDep):
    """Twilio (form post: From, Body) or Telnyx (JSON event: data.payload.from.phone_number, text)."""
    from fastapi.responses import Response

    if len(token) < 16:
        raise HTTPException(404)
    cfg = (await db.execute(select(TrackDeskSettings).where(TrackDeskSettings.sms_token == token))).scalar_one_or_none()
    if cfg is None:
        raise HTTPException(404)
    sender, body = "", ""
    if "json" in (request.headers.get("content-type") or ""):
        event = await request.json()
        data = (event or {}).get("data") or {}
        payload = data.get("payload") or {}
        if data.get("event_type") not in (None, "message.received"):
            return {"ok": True}  # delivery receipts and the like
        sender = ((payload.get("from") or {}).get("phone_number")) or ""
        body = payload.get("text") or ""
    else:
        form = await request.form()
        sender, body = str(form.get("From") or ""), str(form.get("Body") or "")
    if sender and body.strip():
        load = await td.on_text_reply(db, cfg, sender, body)
        await db.commit()
        td.log.info("track_desk_sms_reply", matched=load is not None)
    # Twilio wants TwiML back; an empty response sends no auto-reply.
    return Response('<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")
