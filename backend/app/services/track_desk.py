"""
Track Desk: the check-call workflow for freight brokers (see app/models/track_desk.py).

One check round on a load:

    due ──► call the driver ──► answered: log location / loaded / ETA, score the load, plan the next check
                  │                 └─► "can't talk / text me": text the 3 questions now, wait for the reply
                  └─► no answer (voicemail left) ──► 15 min ──► text ──► 45 min no reply ──► call once more
                                                                                  └─► no answer ──► Unresponsive

In the driver's quiet hours (22:00-06:00 local by default) and for text-only loads the round starts with the text.
A text reply at any point in the round is the check-in; nobody is called that round.

Pure helpers (plan_next_check, score, parse_loads_csv, in_quiet_hours, ...) hold the rules and are unit tested;
tick() runs the rounds every minute.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from sqlalchemy import func, select

from app.models.track_desk import CheckCall, FreightLoad, TrackAlert, TrackDeskSettings

log = structlog.get_logger(__name__)

OPEN = ("active", "at_risk", "late", "unresponsive")
CLOSED = ("delivered", "cancelled")
SMS_AFTER_MISSED_CALL = timedelta(minutes=15)
SMS_REPLY_WAIT = timedelta(minutes=45)
CALL_TIMEOUT = timedelta(minutes=10)  # a call still "dialing" after this is treated as not answered
AT_RISK_GRACE = timedelta(hours=2)

# Plans are configuration, not code: name -> loads per week (None = no cap). Final pricing is set by the business.
PLANS: dict[str, dict] = {
    "pilot": {"label": "Pilot", "loads_per_week": 50},
    "starter": {"label": "Starter", "loads_per_week": 50},
    "growth": {"label": "Growth", "loads_per_week": 125},
    "scale": {"label": "Scale", "loads_per_week": None},
}

# Where a driver is, roughly: the state the load is in. Drivers cross zones; the leg's state beats the phone's
# area code (a Texas number on a load into Ohio is in Ohio's time).
_STATE_TZ = {
    **dict.fromkeys(("CT", "DE", "DC", "FL", "GA", "IN", "ME", "MD", "MA", "MI", "NH", "NJ", "NY", "NC", "OH", "PA",
                     "RI", "SC", "VT", "VA", "WV", "KY", "ON", "QC", "NS", "NB", "PE"), "America/New_York"),
    **dict.fromkeys(("AL", "AR", "IL", "IA", "KS", "LA", "MN", "MS", "MO", "NE", "ND", "OK", "SD", "TN", "TX", "WI",
                     "MB", "SK"), "America/Chicago"),
    **dict.fromkeys(("CO", "ID", "MT", "NM", "UT", "WY", "AB"), "America/Denver"),
    "AZ": "America/Phoenix",
    **dict.fromkeys(("CA", "NV", "OR", "WA", "BC"), "America/Los_Angeles"),
    "AK": "America/Anchorage", "HI": "Pacific/Honolulu",
}


def _aware(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


def _zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "America/Chicago")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("America/Chicago")


# ── Settings ──────────────────────────────────────────────────────────────────

async def get_settings(db, org) -> TrackDeskSettings:
    row = (await db.execute(select(TrackDeskSettings).where(TrackDeskSettings.org_id == org.id))).scalar_one_or_none()
    if row is None:
        row = TrackDeskSettings(org_id=org.id, broker_name=org.name or "", sms_token=secrets.token_urlsafe(24),
                                alert_emails=[])
        db.add(row)
        await db.flush()
    if not row.sms_token:
        row.sms_token = secrets.token_urlsafe(24)
    return row


def plan_limit(cfg: TrackDeskSettings) -> int | None:
    return (PLANS.get(cfg.plan) or PLANS["pilot"])["loads_per_week"]


def week_start(now: datetime, tz: str) -> datetime:
    local = now.astimezone(_zone(tz))
    start = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc)


async def loads_this_week(db, org_id, tz: str, now: datetime | None = None) -> int:
    since = week_start(now or datetime.now(timezone.utc), tz)
    return await db.scalar(select(func.count()).select_from(FreightLoad).where(
        FreightLoad.org_id == org_id, FreightLoad.created_at >= since)) or 0


CHECK_CALL_PROMPT = """You are {{agent_name}}, an AI assistant making a quick check call for {{broker_name}}, a freight broker, \
to the driver of load {{load_id}} ({{pickup_city}} to {{delivery_city}}). This is a {{check_label}}.

Your only job is to get three answers, then hang up:
1. Where are you right now? (a city and state, highway mile marker or landmark is enough)
2. Are you loaded and rolling, or still at pickup?
3. What's your ETA to {{delivery_city}}?
If they mention a delay, ask once: "Got it, what's causing the delay, and when do you think you'll be there?"

Rules:
- Keep the whole call under 90 seconds. Ask only those questions. Never re-ask something they already answered: if
  they gave you location and ETA in one breath, just confirm and close.
- If they're driving, sleeping or can't talk: "No problem, I'll text you the same three questions, reply when you
  can." Then end the call.
- If they ask for a person: "I'll have someone from {{broker_name}} call you back within 15 minutes." Then end.
- If they're upset or say stop calling: apologize, say you won't call them about this load again, and end the call.
- If they say it's delivered, confirm and thank them.
- Never share rates, margins, the shipper's details or other loads. Never argue.
- If asked whether you're a person: "I'm an AI assistant calling for {{broker_name}}."
- Close with: "Thanks, I've logged that. We'll check in again in a few hours unless you need us. Drive safe." and end
  the call.
"""

FIRST_MESSAGE = ("Hi {{first_name}}, this is {{agent_name}} calling for {{broker_name}} about load {{load_id}} to "
                 "{{delivery_city}}. This'll take 30 seconds, is now okay?")
VOICEMAIL = ("Hi {{first_name}}, this is {{broker_name}} checking on load {{load_id}} to {{delivery_city}}. No need to "
             "call back, just reply to the text I'm sending with your location and ETA. Thanks.")
SMS_TEMPLATE = ("Hi {first}, {broker} check-in for load {load} to {city}: 1) Where are you now? 2) Loaded? 3) ETA? "
                "Reply here, takes 20 sec. Reply STOP to opt out.")
WELCOME_SMS = ("Hi {first}, {broker} uses an automated assistant to check on load {load} to {city} every few hours "
               "(location + ETA). Reply to its texts anytime. Reply STOP to opt out.")


async def ensure_agent(db, org, cfg: TrackDeskSettings):
    """The account's check-call agent, created the first time Track Desk is used."""
    from app.models.agent import Agent

    agent = await db.get(Agent, cfg.agent_id) if cfg.agent_id else None
    if agent is not None:
        return agent
    agent = Agent(
        org_id=org.id, name="Track Desk · Check calls", description="Calls drivers for location, loaded status and ETA.",
        template="track_desk", status="active", system_prompt=CHECK_CALL_PROMPT, first_message=FIRST_MESSAGE,
        voicemail_action="leave_message", voicemail_message=VOICEMAIL, screener_action="answer",
        max_duration_seconds=150, specialty="Check calls", ai_disclosure=True,
        caller_number=cfg.caller_number or None,
    )
    db.add(agent)
    await db.flush()
    cfg.agent_id = agent.id
    return agent


# ── Import ────────────────────────────────────────────────────────────────────

_COLUMNS = {
    "external_id": ("load_id", "load", "load number", "load #", "load_number", "id", "pro"),
    "driver_name": ("driver_name", "driver", "driver name"),
    "driver_phone": ("driver_phone", "phone", "driver phone", "cell", "driver cell", "mobile"),
    "pickup_city": ("pickup_city", "pickup city", "origin city", "origin"),
    "pickup_state": ("pickup_state", "pickup state", "origin state", "o state"),
    "pickup_start": ("pickup_window_start", "pickup_start", "pickup window start", "pickup time", "pickup", "pickup date",
                     "pickup_window"),
    "pickup_end": ("pickup_window_end", "pickup_end", "pickup window end"),
    "delivery_city": ("delivery_city", "delivery city", "destination city", "destination", "consignee city"),
    "delivery_state": ("delivery_state", "delivery state", "destination state", "d state"),
    "delivery_start": ("delivery_window_start", "delivery_start", "delivery window start", "delivery time", "delivery",
                       "delivery date", "delivery_window"),
    "delivery_end": ("delivery_window_end", "delivery_end", "delivery window end"),
    "shipper_name": ("shipper_name", "shipper", "customer"),
    "broker_reference": ("broker_reference", "reference", "ref", "po"),
    "commodity": ("commodity",),
    "trailer": ("trailer", "equipment", "trailer type"),
    "notes": ("notes", "note", "comments"),
}
REQUIRED = ("external_id", "driver_phone", "pickup_city", "pickup_state", "pickup_start",
            "delivery_city", "delivery_state", "delivery_start")
_LABELS = {"external_id": "load_id", "driver_phone": "driver_phone", "pickup_city": "pickup city",
           "pickup_state": "pickup state", "pickup_start": "pickup window", "delivery_city": "delivery city",
           "delivery_state": "delivery state", "delivery_start": "delivery window"}


def map_columns(headers: list[str]) -> dict[str, str]:
    """Our field -> the CSV header that holds it."""
    norm = {re.sub(r"[\s_]+", " ", h.strip().lower()): h for h in headers if h}
    out = {}
    for fieldname, names in _COLUMNS.items():
        for n in names:
            hit = norm.get(re.sub(r"[\s_]+", " ", n))
            if hit:
                out[fieldname] = hit
                break
    return out


def parse_when(value: str, tz: str) -> datetime | None:
    """A time from a load sheet, read in the broker's zone unless it carries its own offset."""
    from dateutil import parser as dparser

    value = (value or "").strip()
    if not value:
        return None
    try:
        dt = dparser.parse(value, fuzzy=False)
    except (ValueError, OverflowError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_zone(tz))
    return dt.astimezone(timezone.utc)


def _window(start_raw: str, end_raw: str, tz: str) -> tuple[datetime | None, datetime | None, str | None]:
    """'11/19 08:00-12:00' in one cell, or two cells."""
    start_raw, end_raw = (start_raw or "").strip(), (end_raw or "").strip()
    if not end_raw:
        m = re.match(r"^(.*?\d{1,2}:?\d{0,2}\s*(?:am|pm)?)\s*(?:-|–|to)\s*(\d{1,2}:?\d{0,2}\s*(?:am|pm)?)$", start_raw, re.I)
        if m and re.search(r"[/\-.]|\d{4}", m.group(1)):
            start = parse_when(m.group(1), tz)
            if start:
                day = start.astimezone(_zone(tz)).strftime("%Y-%m-%d")
                end = parse_when(f"{day} {m.group(2)}", tz)
                if end and end < start:
                    end += timedelta(days=1)
                return start, end, None
    start = parse_when(start_raw, tz)
    if start_raw and start is None:
        return None, None, f"couldn't read the time '{start_raw[:40]}'"
    end = parse_when(end_raw, tz) if end_raw else None
    if end_raw and end is None:
        return None, None, f"couldn't read the time '{end_raw[:40]}'"
    if start and end and end < start:
        return None, None, "the window ends before it starts"
    return start, end, None


def _phone(raw: str) -> str | None:
    from app.services.outbound_call import validate_e164

    try:
        return validate_e164(raw)
    except Exception:
        return None


@dataclass
class ImportReport:
    rows: list[dict] = field(default_factory=list)  # parsed loads
    errors: list[dict] = field(default_factory=list)  # {"row", "load_id", "reason"}
    mapping: dict = field(default_factory=dict)


def parse_rows(records: list[dict], tz: str, mapping: dict | None = None) -> ImportReport:
    """Validate load rows (CSV records or JSON objects). Bad rows are reported with the reason, never guessed."""
    headers = list(records[0].keys()) if records else []
    mapping = mapping or map_columns(headers)
    report = ImportReport(mapping=mapping)
    seen: set[str] = set()
    for i, rec in enumerate(records, start=2):  # row 1 is the header
        get = lambda f: str(rec.get(mapping.get(f, f), "") or "").strip()  # noqa: E731
        load_id = get("external_id")
        missing = [_LABELS[f] for f in REQUIRED if not get(f)]
        if not any(str(v or "").strip() for v in rec.values()):
            continue  # blank line
        if missing:
            report.errors.append({"row": i, "load_id": load_id, "reason": "missing " + ", ".join(missing)})
            continue
        if load_id in seen:
            report.errors.append({"row": i, "load_id": load_id, "reason": "duplicate load_id in this file"})
            continue
        phone = _phone(get("driver_phone"))
        if not phone:
            report.errors.append({"row": i, "load_id": load_id, "reason": f"driver phone '{get('driver_phone')}' isn't a valid number"})
            continue
        ps, pe, perr = _window(get("pickup_start"), get("pickup_end"), tz)
        ds, de, derr = _window(get("delivery_start"), get("delivery_end"), tz)
        if perr or derr:
            report.errors.append({"row": i, "load_id": load_id, "reason": f"pickup window: {perr}" if perr else f"delivery window: {derr}"})
            continue
        if ds and ps and (de or ds) < ps:
            report.errors.append({"row": i, "load_id": load_id, "reason": "delivery is before pickup"})
            continue
        seen.add(load_id)
        report.rows.append({
            "external_id": load_id[:64], "driver_name": get("driver_name")[:255], "driver_phone": phone,
            "pickup_city": get("pickup_city")[:128], "pickup_state": get("pickup_state").upper()[:8],
            "pickup_start": ps, "pickup_end": pe,
            "delivery_city": get("delivery_city")[:128], "delivery_state": get("delivery_state").upper()[:8],
            "delivery_start": ds, "delivery_end": de,
            "shipper_name": get("shipper_name")[:255], "broker_reference": get("broker_reference")[:128],
            "commodity": get("commodity")[:128], "trailer": get("trailer")[:64], "notes": get("notes"),
        })
    return report


def parse_loads_csv(text: str, tz: str, mapping: dict | None = None) -> ImportReport:
    text = (text or "").lstrip("﻿")
    reader = csv.DictReader(io.StringIO(text))
    return parse_rows([dict(r) for r in reader], tz, mapping)


async def import_loads(db, org, cfg: TrackDeskSettings, report: ImportReport, now: datetime | None = None) -> dict:
    """Save parsed rows: new loads are scheduled, an existing open load with the same load_id is updated."""
    now = now or datetime.now(timezone.utc)
    ids = [r["external_id"] for r in report.rows]
    existing = {l.external_id: l for l in (await db.execute(select(FreightLoad).where(
        FreightLoad.org_id == org.id, FreightLoad.external_id.in_(ids)))).scalars()} if ids else {}
    limit = plan_limit(cfg)
    used = await loads_this_week(db, org.id, cfg.time_zone, now)
    imported, updated, errors = 0, 0, list(report.errors)
    new_loads = []
    for row in report.rows:
        load = existing.get(row["external_id"])
        if load is not None:
            if load.status in CLOSED:
                errors.append({"row": None, "load_id": row["external_id"], "reason": f"load is already {load.status}"})
                continue
            changed_phone = load.driver_phone != row["driver_phone"]
            for k, v in row.items():
                setattr(load, k, v)
            if changed_phone:
                load.do_not_call, load.unresponsive = False, False
            load.next_check_at, load.next_check_kind = plan_next_check(load, cfg, now)
            updated += 1
            continue
        if limit is not None and used + imported >= limit:
            errors.append({"row": None, "load_id": row["external_id"],
                           "reason": f"over this week's plan limit of {limit} loads"})
            continue
        load = FreightLoad(org_id=org.id, status="active", milestones=[], **row)
        load.next_check_at, load.next_check_kind = plan_next_check(load, cfg, now)
        db.add(load)
        new_loads.append(load)
        imported += 1
    await db.flush()
    return {"imported": imported, "updated": updated, "skipped": len(errors), "errors": errors,
            "new_ids": [str(l.id) for l in new_loads]}


# ── Scheduling ────────────────────────────────────────────────────────────────

def plan_next_check(load: FreightLoad, cfg: TrackDeskSettings, now: datetime,
                    base: datetime | None = None) -> tuple[datetime | None, str]:
    """When to check this load next, and which check it is.

    Pickup check 30 min after the pickup time; en-route checks every interval while rolling; a pre-delivery check
    2 h before the delivery window; a delivery confirmation 30 min after it. Nothing once delivered or cancelled.
    """
    if load.status in CLOSED:
        return None, ""
    done = set(load.milestones or [])
    interval = timedelta(hours=min(4, max(2, cfg.check_interval_hours or 3)))
    last = _aware(load.last_check_at)
    pickup = _aware(load.pickup_start)
    d_start = _aware(load.delivery_start)
    d_end = _aware(load.delivery_end) or d_start
    if "pickup" not in done:
        return (max(now, pickup + timedelta(minutes=30)) if pickup else now), "pickup"
    milestone = None
    if d_start and "pre_delivery" not in done:
        milestone = (d_start - timedelta(hours=2), "pre_delivery")
    elif d_end and "delivery" not in done:
        milestone = (d_end + timedelta(minutes=30), "delivery")
    en_route = (base or last or now) + interval  # base: when the last round ended
    if milestone and milestone[0] <= en_route + timedelta(minutes=30):
        return max(now, milestone[0]), milestone[1]
    return max(now, en_route), "en_route"


def driver_zone(load: FreightLoad, cfg: TrackDeskSettings) -> ZoneInfo:
    """The driver's local zone: delivery state once loaded, pickup state before; else the broker's zone."""
    state = load.delivery_state if load.loaded == "yes" or "pickup" in (load.milestones or []) else load.pickup_state
    zone = _STATE_TZ.get((state or "").upper())
    if not zone:
        from app.services.quiet_hours import zones_for

        zones = zones_for(load.driver_phone)
        zone = zones[0] if zones else cfg.time_zone
    return _zone(zone)


def in_quiet_hours(load: FreightLoad, cfg: TrackDeskSettings, now: datetime) -> bool:
    hour = now.astimezone(driver_zone(load, cfg)).hour
    start, end = cfg.quiet_start_hour, cfg.quiet_end_hour
    return (start <= hour or hour < end) if start > end else (start <= hour < end)


def quiet_hours_end(load: FreightLoad, cfg: TrackDeskSettings, now: datetime) -> datetime:
    local = now.astimezone(driver_zone(load, cfg))
    end = local.replace(hour=cfg.quiet_end_hour, minute=0, second=0, microsecond=0)
    if end <= local:
        end += timedelta(days=1)
    return end.astimezone(timezone.utc)


def may_call(load: FreightLoad, cfg: TrackDeskSettings, now: datetime) -> bool:
    if load.sms_only or cfg.sms_only or load.do_not_call:
        return False
    if in_quiet_hours(load, cfg, now):
        return cfg.call_late_loads_in_quiet_hours and load.status == "late"
    return True


# ── Scoring ───────────────────────────────────────────────────────────────────

_DELAY = re.compile(r"\b(break ?down|broke down|broken down|detention|detained|delay|delayed|running late|behind|"
                    r"accident|stuck|flat|blowout|blew a tire|weather|snow|closed|waiting on|not loaded yet|"
                    r"reefer (?:issue|problem)|out of hours|reset)\b", re.I)


def score(load: FreightLoad, now: datetime) -> str:
    """on time (active) / at_risk / late / unresponsive, from the last check-in against the delivery window.

    Late: ETA after the window, the window passed undelivered, or a reported breakdown / detention / delay that
    pushes the ETA past the window (or gives none). At risk: ETA up to 2 h past the window, or no usable ETA after
    a check-in. Unresponsive: the last round got no answer after a call, a text and a second call.
    """
    if load.status in CLOSED:
        return load.status
    if load.unresponsive:
        return "unresponsive"
    end = _aware(load.delivery_end) or _aware(load.delivery_start)
    eta = _aware(load.last_eta)
    if end and now > end + timedelta(minutes=30) and not load.delivered_at:
        return "late"
    if load.last_check_at is None:
        return "active"
    delayed = bool(_DELAY.search(load.delay_reason or ""))
    if end is None:
        return "at_risk" if delayed else "active"
    if eta is None:
        return "late" if delayed else "at_risk"
    if eta <= end:
        return "active"
    if eta <= end + AT_RISK_GRACE and not delayed:
        return "at_risk"
    return "late"


# ── Reading the driver's answer ───────────────────────────────────────────────

_STOP = re.compile(r"^\s*(stop|stopall|unsubscribe|cancel|end|quit|opt ?out)\s*[.!]*\s*$", re.I)
_STOP_CALLING = re.compile(r"\b(stop calling|don'?t call|do not call|quit calling|leave me alone|take me off|"
                           r"lose my number)\b", re.I)


@dataclass
class CheckIn:
    location: str = ""
    loaded: str = "unknown"
    eta: datetime | None = None
    eta_text: str = ""
    delay_reason: str = ""
    delivered: bool = False
    wants_text: bool = False
    wants_human: bool = False
    stop: bool = False
    notes: str = ""
    confidence: str = "low"

    @property
    def useful(self) -> bool:
        return bool(self.location or self.eta or self.eta_text or self.delivered or self.loaded != "unknown")


def _prompt(load: FreightLoad, cfg: TrackDeskSettings, text: str, now: datetime, channel: str) -> str:
    zone = driver_zone(load, cfg)
    local_now = now.astimezone(zone)
    return f"""A freight check-{'call transcript' if channel == 'call' else 'in text message'} from a truck driver. \
Extract their check-in as JSON.

Load {load.external_id}: pickup {load.pickup_city}, {load.pickup_state}; delivery {load.delivery_city}, \
{load.delivery_state}. Delivery window: {_fmt(load.delivery_start, zone)} to {_fmt(load.delivery_end, zone)}.
Right now it is {local_now.strftime('%A %Y-%m-%d %H:%M')} ({zone.key}).

{'Transcript' if channel == 'call' else 'Driver text'}:
{text}

Return only JSON with these keys:
- "location": where the driver said they are (city/state, highway, mile marker, landmark), "" if not said
- "loaded": "yes" if loaded / rolling / picked up, "no" if still waiting at pickup or empty, "unknown" if not said
- "eta": the ETA to delivery as an ISO 8601 time with offset, worked out from the current time above ("about \
3 hours" = now + 3 h; "tomorrow 8am" = next day 08:00 {zone.key}); null if they gave none
- "eta_text": the ETA in their words, "" if none
- "delay_reason": what's delaying them (breakdown, detention, weather, traffic, waiting to load...), "" if no delay
- "delivered": true only if they said the load is delivered / unloaded / empty at the receiver
- "wants_text": true if they can't talk now (driving, sleeping, busy) or asked to be texted
- "wants_human": true if they asked for a person / dispatcher / the broker to call them
- "stop": true if they asked not to be called or texted again
- "notes": anything else useful for the broker in a few words, "" if nothing
- "confidence": "high" if location and ETA are clear, "medium" if one is vague or missing, "low" if neither
Never invent an answer the driver didn't give."""


def _fmt(d: datetime | None, zone: ZoneInfo) -> str:
    d = _aware(d)
    return d.astimezone(zone).strftime("%a %m/%d %H:%M") if d else "not set"


def _to_checkin(data: dict | None, now: datetime) -> CheckIn:
    data = data or {}
    eta = None
    if data.get("eta"):
        try:
            eta = datetime.fromisoformat(str(data["eta"]).replace("Z", "+00:00"))
            eta = _aware(eta).astimezone(timezone.utc)
            if eta < now - timedelta(hours=6) or eta > now + timedelta(days=10):
                eta = None  # a garbled time is worse than none
        except ValueError:
            eta = None
    loaded = str(data.get("loaded") or "unknown").lower()
    conf = str(data.get("confidence") or "low").lower()
    return CheckIn(
        location=str(data.get("location") or "")[:255], loaded=loaded if loaded in ("yes", "no") else "unknown",
        eta=eta, eta_text=str(data.get("eta_text") or "")[:128], delay_reason=str(data.get("delay_reason") or "")[:255],
        delivered=bool(data.get("delivered")), wants_text=bool(data.get("wants_text")),
        wants_human=bool(data.get("wants_human")), stop=bool(data.get("stop")), notes=str(data.get("notes") or "")[:500],
        confidence=conf if conf in ("high", "medium", "low") else "low",
    )


async def read_checkin(load: FreightLoad, cfg: TrackDeskSettings, text: str, now: datetime, channel: str) -> CheckIn:
    """The driver's answer as fields. STOP and 'don't call me' are caught without the model."""
    if channel == "sms" and _STOP.match(text or ""):
        return CheckIn(stop=True, confidence="high")
    from app.services.llm import _analysis_json

    data = await _analysis_json(_prompt(load, cfg, text, now, channel))
    result = _to_checkin(data, now)
    if data is None:
        result.notes = "Couldn't read this automatically, check the transcript."
    if _STOP_CALLING.search(text or ""):
        result.stop = True
    return result


def transcript_text(transcript: list[dict] | None) -> str:
    lines = []
    for t in transcript or []:
        role = t.get("role")
        if role in ("user", "caller") and (t.get("text") or "").strip():
            lines.append(f"Driver: {t['text'].strip()}")
        elif role == "assistant" and (t.get("text") or "").strip():
            lines.append(f"Agent: {t['text'].strip()}")
    return "\n".join(lines)


# ── Rounds ────────────────────────────────────────────────────────────────────

def _first(name: str) -> str:
    return (name or "").split(" ")[0] or "there"


def _check_label(kind: str) -> str:
    return {"pickup": "pickup check (they should be at or leaving pickup)",
            "pre_delivery": "pre-delivery check (delivery is in about 2 hours)",
            "delivery": "delivery confirmation (the delivery window has passed: ask if it's delivered)",
            "manual": "check-in the broker asked for"}.get(kind, "routine en-route check")


async def _sms_connection(db, org_id):
    from app.models.messaging import MessagingConnection

    conn = (await db.execute(select(MessagingConnection).where(MessagingConnection.org_id == org_id))).scalar_one_or_none()
    return conn if conn and conn.secret_enc and conn.from_number else None


async def send_text(db, org_id, to: str, body: str) -> bool:
    from app.services import secret_store, sms

    conn = await _sms_connection(db, org_id)
    if conn is None:
        return False
    try:
        await sms.send(conn.provider, conn.account_sid, secret_store.decrypt_value(conn.secret_enc), conn.from_number,
                       to, body, conn.messaging_profile_id)
        conn.last_sent_at = datetime.now(timezone.utc)
        return True
    except Exception as exc:
        log.warning("track_desk_sms_failed", error=str(exc)[:200])
        return False


async def _place_call(db, org, cfg, load: FreightLoad, kind: str):
    """Dial the driver with the check-call agent. Returns the CallLog, or None when the call couldn't start."""
    from app.services.outbound_call import call_service

    agent = await ensure_agent(db, org, cfg)
    variables = {
        "name": _first(load.driver_name), "first_name": _first(load.driver_name), "full_name": load.driver_name,
        "agent_name": cfg.agent_name or "Alex", "broker_name": cfg.broker_name or org.name or "your broker",
        "load_id": load.external_id, "pickup_city": load.pickup_city, "delivery_city": load.delivery_city,
        "check_label": _check_label(kind),
    }
    try:
        return await call_service.dispatch_call(None, db, agent=agent, to_phone=load.driver_phone,
                                                from_number=cfg.caller_number or None, variables=variables)
    except Exception as exc:
        log.warning("track_desk_call_failed", load=str(load.id), error=str(exc)[:200])
        return None


async def start_round(db, org, cfg: TrackDeskSettings, load: FreightLoad, now: datetime, kind: str | None = None) -> CheckCall:
    """Begin a check on a load: a call when we may call, else the text."""
    kind = kind or load.next_check_kind or "en_route"
    retried = bool((load.round_state or {}).get("retried"))
    if load.round_state is None:
        await welcome_text(db, org, cfg, load)
    if may_call(load, cfg, now):
        call_log = await _place_call(db, org, cfg, load, kind)
        if call_log is not None:
            check = CheckCall(org_id=org.id, load_id=load.id, kind=kind, channel="call", outcome="dialing",
                              scheduled_at=load.next_check_at, attempted_at=now, call_log_id=call_log.id)
            db.add(check)
            await db.flush()
            load.round_state = {"phase": "calling", "check_id": str(check.id), "kind": kind, "retried": retried}
            return check
    return await _text_driver(db, org, cfg, load, now, kind, retried=retried)


async def _text_driver(db, org, cfg, load, now, kind, retried: bool) -> CheckCall:
    body = SMS_TEMPLATE.format(first=_first(load.driver_name), broker=cfg.broker_name or org.name,
                               load=load.external_id, city=load.delivery_city)
    sent = await send_text(db, org.id, load.driver_phone, body)
    check = CheckCall(org_id=org.id, load_id=load.id, kind=kind, channel="sms", outcome="sms_sent" if sent else "failed",
                      scheduled_at=load.next_check_at, attempted_at=now, message=body if sent else "")
    if not sent:
        check.driver_notes = "Texting isn't set up for this account (Phone Numbers → Texting)."
    db.add(check)
    await db.flush()
    wait = now + SMS_REPLY_WAIT
    if in_quiet_hours(load, cfg, now) and not retried:
        wait = max(wait, quiet_hours_end(load, cfg, now))  # the retry call waits for morning
    load.round_state = {"phase": "sms_wait", "check_id": str(check.id), "kind": kind, "retried": retried,
                        "until": wait.isoformat(), "texted": sent}
    return check


async def apply_checkin(db, org, cfg, load: FreightLoad, check: CheckCall, info: CheckIn, now: datetime,
                        source_text: str) -> None:
    """Log a driver's answer on the check and the load, rescore, alert on exceptions, plan the next check."""
    check.location_text, check.loaded, check.eta_at = info.location, info.loaded, info.eta
    check.eta_text, check.delay_reason, check.driver_notes = info.eta_text, info.delay_reason, info.notes
    check.confidence = info.confidence
    check.needs_review = info.confidence == "low" and not info.stop
    kind = (load.round_state or {}).get("kind") or check.kind
    load.round_state = None
    if info.stop:
        load.do_not_call = True
        load.sms_only = False
        await raise_alert(db, org, cfg, load, "dnc", f"Driver {load.driver_name or load.driver_phone} asked us to stop "
                          f"contacting them about load {load.external_id}. No more calls or texts on this load.")
    if info.wants_human:
        await raise_alert(db, org, cfg, load, "driver_requested_human",
                          f"Driver {load.driver_name or ''} on load {load.external_id} asked for a call back from your "
                          f"team (promised within 15 minutes).")
    if info.useful:
        load.unresponsive = False
        load.last_check_at = now
        if info.location:
            load.last_location = info.location
        if info.loaded != "unknown":
            load.loaded = info.loaded
        if info.eta or info.eta_text:
            load.last_eta, load.last_eta_text = info.eta, info.eta_text
        load.delay_reason = info.delay_reason
        if info.delivered:
            load.status, load.delivered_at = "delivered", now
    _done_milestone(load, kind)
    check.outcome = check.outcome if check.outcome != "dialing" else "answered"
    if check.needs_review and info.useful:
        await raise_alert(db, org, cfg, load, "needs_review", f"Load {load.external_id}: the driver's answer was unclear. "
                          f"Check the {'transcript' if check.channel == 'call' else 'text'}: \"{source_text[:160]}\"",
                          notify=False)
    await rescore(db, org, cfg, load, now, round_done=True)


def _done_milestone(load: FreightLoad, kind: str) -> None:
    if kind in ("pickup", "pre_delivery", "delivery"):
        done = list(load.milestones or [])
        if kind not in done:
            load.milestones = done + [kind]


async def rescore(db, org, cfg, load: FreightLoad, now: datetime, round_done: bool = False) -> None:
    """Rescore the load and plan its next check (counted from now when a round just ended)."""
    before = load.status
    load.status = score(load, now)
    if load.status in CLOSED or load.do_not_call:
        load.next_check_at, load.next_check_kind = None, ""  # nobody contacts a driver who asked us to stop
    elif round_done or load.round_state is None:
        load.next_check_at, load.next_check_kind = plan_next_check(load, cfg, now, base=now if round_done else None)
    if load.status != before and load.status in ("late", "unresponsive", "at_risk"):
        await raise_alert(db, org, cfg, load, load.status, alert_text(load, cfg), notify=load.status != "at_risk")


def alert_text(load: FreightLoad, cfg: TrackDeskSettings) -> str:
    zone = driver_zone(load, cfg)
    eta = _fmt(load.last_eta, zone) if load.last_eta else (load.last_eta_text or "no ETA")
    head = {"late": "LATE", "at_risk": "At risk", "unresponsive": "Driver unresponsive"}.get(load.status, load.status)
    parts = [f"{head}: load {load.external_id} ({load.pickup_city}, {load.pickup_state} to {load.delivery_city}, "
             f"{load.delivery_state})", f"Driver: {load.driver_name or 'unknown'} {load.driver_phone}",
             f"Last location: {load.last_location or 'unknown'}", f"ETA: {eta}",
             f"Delivery window: {_fmt(load.delivery_start, zone)} to {_fmt(load.delivery_end, zone)}"]
    if load.delay_reason:
        parts.append(f"Reason: {load.delay_reason}")
    if load.status == "unresponsive":
        parts.append("No answer to a call, a text and a second call.")
    return "\n".join(parts)


async def raise_alert(db, org, cfg, load: FreightLoad, kind: str, message: str, notify: bool = True) -> TrackAlert:
    """In the Alerts inbox always; by email and text too for exceptions the broker must act on now."""
    alert = TrackAlert(org_id=org.id, load_id=load.id, kind=kind, message=message, delivered_via=["in_app"])
    db.add(alert)
    await db.flush()
    if notify:
        link = _load_link(load)
        via = ["in_app"]
        from app.services.email import send_email

        subject = {"late": f"Late load {load.external_id}", "unresponsive": f"Driver not answering · load {load.external_id}",
                   "driver_requested_human": f"Driver wants a call · load {load.external_id}",
                   "dnc": f"Driver opted out · load {load.external_id}"}.get(kind, f"Track Desk · load {load.external_id}")
        html = (f"<div style='font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;line-height:1.5'>"
                f"{_html(message)}<p><a href='{link}'>Open the load</a> &nbsp;·&nbsp; "
                f"<a href='tel:{load.driver_phone}'>Call the driver</a></p>"
                f"<p style='color:#71717a;font-size:12px'>Track Desk by BlackSync</p></div>")
        for to in cfg.alert_emails or []:
            try:
                if await send_email(to, subject, html, kind="track_desk_alert",
                                    idempotency_key=f"track-alert-{alert.id}-{to}"):
                    if "email" not in via:
                        via.append("email")
            except Exception as exc:
                log.warning("track_desk_alert_email_failed", error=str(exc)[:160])
        if cfg.alert_phone and kind in ("late", "unresponsive", "driver_requested_human", "dnc"):
            if await send_text(db, org.id, cfg.alert_phone, f"{subject}. {message.splitlines()[1] if len(message.splitlines()) > 1 else ''} {link}"[:600]):
                via.append("sms")
        alert.delivered_via = via
    return alert


def _html(text: str) -> str:
    import html

    return "<br>".join(html.escape(line) for line in (text or "").splitlines())


def _load_link(load: FreightLoad) -> str:
    from app.config import settings

    return f"{(settings.app_url or 'https://blacksync.si').rstrip('/')}/track-desk/{load.id}"


async def _finish_call(db, org, cfg, load: FreightLoad, check: CheckCall, now: datetime) -> None:
    """A check call ended: log the answer, or move the round on to the text / retry."""
    from app.models.call_log import CallLog

    call = await db.get(CallLog, check.call_log_id) if check.call_log_id else None
    ended = call is not None and call.ended_at is not None
    if not ended and _aware(check.attempted_at) > now - CALL_TIMEOUT:
        return  # still on the call
    said = transcript_text(call.transcript if call else None)
    driver_spoke = "Driver:" in said
    check.duration_sec = call.duration_seconds if call else None
    voicemail = call is not None and call.outcome == "voicemail"
    if driver_spoke and not voicemail:
        check.outcome = "answered"
        info = await read_checkin(load, cfg, said, now, "call")
        if info.wants_text and not info.useful and not info.stop:
            await apply_checkin(db, org, cfg, load, check, info, now, said)
            await _text_driver(db, org, cfg, load, now, check.kind, retried=bool((load.round_state or {}).get("retried")))
            return
        await apply_checkin(db, org, cfg, load, check, info, now, said)
        if not info.useful and not info.stop and not info.wants_human:
            # Picked up but gave nothing usable (bad line, hung up): text them the questions.
            await _text_driver(db, org, cfg, load, now, check.kind, retried=True)
        return
    check.outcome = "voicemail" if voicemail else ("failed" if call is not None and call.status == "failed" else "no_answer")
    state = dict(load.round_state or {})
    if state.get("retried"):
        await _unresponsive(db, org, cfg, load, now, state.get("kind") or check.kind)
        return
    load.round_state = {**state, "phase": "sms_pending", "until": (now + SMS_AFTER_MISSED_CALL).isoformat()}


async def _unresponsive(db, org, cfg, load: FreightLoad, now: datetime, kind: str) -> None:
    load.round_state = None
    load.unresponsive = True
    _done_milestone(load, kind)
    # Keep trying on the normal cadence (from now); rescore() alerts on the change to unresponsive.
    await rescore(db, org, cfg, load, now, round_done=True)


async def advance(db, org, cfg, load: FreightLoad, now: datetime) -> None:
    """Move one load's check round forward. Idempotent: safe to run every minute."""
    if load.status in CLOSED or cfg.paused:
        return
    if load.do_not_call:
        load.round_state, load.next_check_at = None, None
        return
    state = load.round_state or {}
    phase = state.get("phase")
    check = await db.get(CheckCall, uuid.UUID(state["check_id"])) if state.get("check_id") else None
    if phase == "calling" and check is not None:
        await _finish_call(db, org, cfg, load, check, now)
        return
    until = datetime.fromisoformat(state["until"]) if state.get("until") else None
    if phase == "sms_pending":
        if until and now >= until:
            await _text_driver(db, org, cfg, load, now, state.get("kind") or "en_route", retried=bool(state.get("retried")))
        return
    if phase == "sms_wait":
        if until and now >= until:
            if state.get("retried"):
                await _unresponsive(db, org, cfg, load, now, state.get("kind") or "en_route")
                return
            load.round_state = {**state, "retried": True}
            if may_call(load, cfg, now):
                await start_round(db, org, cfg, load, now, state.get("kind"))
            else:
                await _unresponsive(db, org, cfg, load, now, state.get("kind") or "en_route")
        return
    # No round in progress: rescore (a window can pass with no news) and start one when due.
    await rescore_if_changed(db, org, cfg, load, now)
    due = _aware(load.next_check_at)
    if due is not None and due <= now:
        await start_round(db, org, cfg, load, now)


async def rescore_if_changed(db, org, cfg, load, now) -> None:
    if score(load, now) != load.status:
        await rescore(db, org, cfg, load, now)


async def on_text_reply(db, cfg: TrackDeskSettings, from_phone: str, body: str, now: datetime | None = None) -> FreightLoad | None:
    """A driver's text: the check-in for their open load (the one most recently texted or called)."""
    from app.models.account import Organization
    from app.services.outbound_call import validate_e164

    now = now or datetime.now(timezone.utc)
    try:
        phone = validate_e164(from_phone)
    except Exception:
        return None
    loads = (await db.execute(select(FreightLoad).where(
        FreightLoad.org_id == cfg.org_id, FreightLoad.driver_phone == phone, FreightLoad.status.in_(OPEN))
        .order_by(FreightLoad.updated_at.desc()))).scalars().all()
    if not loads:
        return None
    # Prefer the load waiting on a text; a reply naming a load id picks that one.
    load = next((l for l in loads if l.external_id and re.search(rf"\b{re.escape(l.external_id)}\b", body or "")), None) \
        or next((l for l in loads if (l.round_state or {}).get("phase") in ("sms_wait", "sms_pending", "calling")), loads[0])
    org = await db.get(Organization, cfg.org_id)
    check = CheckCall(org_id=cfg.org_id, load_id=load.id, kind=(load.round_state or {}).get("kind") or "en_route",
                      channel="sms", outcome="sms_reply", attempted_at=now, message=(body or "")[:2000])
    db.add(check)
    await db.flush()
    info = await read_checkin(load, cfg, body, now, "sms")
    if info.stop:
        for other in loads:  # STOP by text opts the number out of every load
            other.do_not_call, other.round_state, other.next_check_at = True, None, None
    await apply_checkin(db, org, cfg, load, check, info, now, body)
    return load


async def welcome_text(db, org, cfg, load: FreightLoad) -> None:
    """First load for a driver number: who will be checking in, how often, and how to opt out."""
    seen = await db.scalar(select(func.count()).select_from(CheckCall).join(FreightLoad, FreightLoad.id == CheckCall.load_id)
                           .where(CheckCall.org_id == org.id, FreightLoad.driver_phone == load.driver_phone))
    if seen:
        return
    body = WELCOME_SMS.format(first=_first(load.driver_name), broker=cfg.broker_name or org.name,
                              load=load.external_id, city=load.delivery_city)
    if await send_text(db, org.id, load.driver_phone, body):
        db.add(CheckCall(org_id=org.id, load_id=load.id, kind="welcome", channel="sms", outcome="sms_sent",
                         message=body))


# ── Worker ────────────────────────────────────────────────────────────────────

_LOCK = asyncio.Lock()


async def tick(now: datetime | None = None) -> int:
    """Advance every load that has a round in progress or a check due. Returns how many were touched."""
    from sqlalchemy import and_, or_

    from app.database import AsyncSessionLocal
    from app.models.account import Organization

    if _LOCK.locked():
        return 0
    async with _LOCK:
        now = now or datetime.now(timezone.utc)
        touched = 0
        async with AsyncSessionLocal() as db:
            ids = (await db.execute(select(FreightLoad.id).where(
                FreightLoad.status.in_(OPEN),
                or_(FreightLoad.round_state.isnot(None), FreightLoad.next_check_at <= now,
                    and_(FreightLoad.status != "late",
                         or_(FreightLoad.delivery_end <= now - timedelta(minutes=30),
                             and_(FreightLoad.delivery_end.is_(None), FreightLoad.delivery_start <= now - timedelta(minutes=30))))))
                .order_by(FreightLoad.round_state.is_(None), FreightLoad.next_check_at).limit(300))).scalars().all()
        for load_id in ids:
            async with AsyncSessionLocal() as db:
                load = await db.get(FreightLoad, load_id, with_for_update=True)
                if load is None:
                    continue
                org = await db.get(Organization, load.org_id)
                cfg = await get_settings(db, org)
                try:
                    await advance(db, org, cfg, load, now)
                    await db.commit()
                    touched += 1
                except Exception as exc:
                    await db.rollback()
                    log.warning("track_desk_advance_failed", load=str(load_id), error=f"{type(exc).__name__}: {str(exc)[:200]}")
        return touched


def start_worker(interval: float = 60.0) -> asyncio.Task:
    async def loop():
        await asyncio.sleep(20)
        while True:
            try:
                await tick()
            except Exception as exc:
                log.warning("track_desk_worker_failed", error=f"{type(exc).__name__}: {str(exc)[:200]}")
            await asyncio.sleep(interval)
    return asyncio.create_task(loop())


def board_json(load: FreightLoad) -> dict:
    return {
        "id": str(load.id), "load_id": load.external_id, "driver_name": load.driver_name, "driver_phone": load.driver_phone,
        "pickup": {"city": load.pickup_city, "state": load.pickup_state, "start": _iso(load.pickup_start),
                   "end": _iso(load.pickup_end)},
        "delivery": {"city": load.delivery_city, "state": load.delivery_state, "start": _iso(load.delivery_start),
                     "end": _iso(load.delivery_end)},
        "shipper_name": load.shipper_name, "broker_reference": load.broker_reference, "commodity": load.commodity,
        "trailer": load.trailer, "notes": load.notes, "status": load.status, "sms_only": load.sms_only,
        "do_not_call": load.do_not_call, "last_location": load.last_location, "loaded": load.loaded,
        "last_eta": _iso(load.last_eta), "last_eta_text": load.last_eta_text, "delay_reason": load.delay_reason,
        "last_check_at": _iso(load.last_check_at), "next_check_at": _iso(load.next_check_at),
        "next_check_kind": load.next_check_kind, "round": (load.round_state or {}).get("phase"),
        "delivered_at": _iso(load.delivered_at), "created_at": _iso(load.created_at),
    }


def check_json(c: CheckCall) -> dict:
    return {
        "id": str(c.id), "kind": c.kind, "channel": c.channel, "outcome": c.outcome, "attempted_at": _iso(c.attempted_at),
        "call_id": str(c.call_log_id) if c.call_log_id else None, "location": c.location_text, "loaded": c.loaded,
        "eta": _iso(c.eta_at), "eta_text": c.eta_text, "delay_reason": c.delay_reason, "notes": c.driver_notes,
        "message": c.message, "confidence": c.confidence, "needs_review": c.needs_review, "duration_sec": c.duration_sec,
        "entered_by": c.entered_by,
    }


def alert_json(a: TrackAlert, load: FreightLoad | None = None) -> dict:
    return {
        "id": str(a.id), "load": str(a.load_id), "load_id": load.external_id if load else None,
        "driver_name": load.driver_name if load else None, "driver_phone": load.driver_phone if load else None,
        "kind": a.kind, "message": a.message, "sent_at": _iso(a.sent_at), "delivered_via": a.delivered_via or [],
        "acknowledged_at": _iso(a.acknowledged_at), "acknowledged_by": a.acknowledged_by,
    }


def _iso(d: datetime | None) -> str | None:
    d = _aware(d)
    return d.isoformat() if d else None


SORT = {"late": 0, "at_risk": 1, "unresponsive": 2, "active": 3, "delivered": 4, "cancelled": 5}


def json_rows(text: str) -> list[dict]:
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("loads") or [data]
    if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
        raise ValueError("Send a list of load objects.")
    return data
