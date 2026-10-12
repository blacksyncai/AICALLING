"""
Radar: scan a connected CRM for people worth calling now, grouped into plays.

Each provider returns raw signals per contact (created, last inbound, calls and whether any
connected, open deal stage and when it last moved, won deals). Plain rules turn those into
plays, most urgent first, so every person lands in exactly one play with a reason:

  hot          they reached out (email/text/form/inbound call) in the last 7 days, no call since
  never_called in the CRM 1+ day, never called
  unreached    called 1–5 times, never reached, last try 3+ days ago
  went_cold    had a real conversation, nothing for 30+ days, deal still open
  stuck        open deal hasn't moved in 21+ days
  past_client  won 6+ months ago (check-in / referrals)
  revive       old lead (6+ months), quiet for 90+ days
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

UTC = dt.timezone.utc

PLAYS = [
    {"key": "hot", "title": "Hot right now", "why": "Reached out in the last 7 days and nobody has called them since.",
     "suggest": "Call within the hour — they're expecting it."},
    {"key": "never_called", "title": "Never called", "why": "In your CRM for a day or more and never got a call.",
     "suggest": "Fast first touch: introduce yourself and qualify."},
    {"key": "unreached", "title": "Tried, never reached", "why": "Called 1–5 times, never got them on the phone.",
     "suggest": "Try again at a different time of day; leave a voicemail on the last try."},
    {"key": "went_cold", "title": "Went cold", "why": "Had a real conversation, then nothing for 30+ days.",
     "suggest": "Reference the last conversation and ask what changed."},
    {"key": "stuck", "title": "Stuck in a stage", "why": "Open deal that hasn't moved in 21+ days.",
     "suggest": "Ask the one question that unblocks the next stage."},
    {"key": "past_client", "title": "Past clients", "why": "Won 6+ months ago.",
     "suggest": "Check in, ask how it's going, ask for a referral."},
    {"key": "revive", "title": "Old leads to revive", "why": "6+ months old and quiet for 90+ days.",
     "suggest": "Low-pressure reactivation: is this still on your radar?"},
]
PLAY_KEYS = [p["key"] for p in PLAYS]


@dataclass
class Signals:
    external_id: str
    name: str
    phone: str
    company: str = ""
    email: str = ""
    created_at: dt.datetime | None = None
    last_activity_at: dt.datetime | None = None
    last_inbound_at: dt.datetime | None = None
    inbound_kind: str = ""
    calls: int = 0
    connected_calls: int = 0
    last_call_at: dt.datetime | None = None
    last_call_result: str = ""
    deal_stage: str = ""
    deal_open: bool = False
    deal_updated_at: dt.datetime | None = None
    won_at: dt.datetime | None = None
    status: str = ""
    dnc: bool = False
    extra: dict = field(default_factory=dict)


def _days(a: dt.datetime | None, now: dt.datetime) -> int | None:
    return None if a is None else max(0, (now - a).days)


def _when(d: dt.datetime | None) -> str:
    return d.strftime("%b %-d") if d else ""


def classify(s: Signals, now: dt.datetime) -> tuple[str, str] | None:
    """(play, reason) for one contact, or None when there's nothing to do (closed, DNC, just called)."""
    if s.dnc or not s.phone:
        return None
    lost = any(w in s.status.lower() for w in ("lost", "dead", "trash", "not interested", "bad fit", "do not"))
    last_touch = max([d for d in (s.last_call_at, s.last_inbound_at, s.last_activity_at) if d] or [None]) \
        if any((s.last_call_at, s.last_inbound_at, s.last_activity_at)) else None
    if s.last_inbound_at and _days(s.last_inbound_at, now) <= 7 and (not s.last_call_at or s.last_call_at < s.last_inbound_at):
        return "hot", f"{s.inbound_kind or 'Reached out'} on {_when(s.last_inbound_at)}, no call since"
    if lost:
        return None
    if s.won_at and not s.deal_open:
        return ("past_client", f"Won {_when(s.won_at)}") if _days(s.won_at, now) >= 180 else None
    if s.calls == 0 and s.created_at and _days(s.created_at, now) >= 1:
        return "never_called", f"Added {_when(s.created_at)}, never called"
    if 1 <= s.calls <= 5 and s.connected_calls == 0 and s.last_call_at and _days(s.last_call_at, now) >= 3:
        res = f" ({s.last_call_result})" if s.last_call_result else ""
        return "unreached", f"{s.calls} call{'s' if s.calls > 1 else ''}, never reached · last try {_when(s.last_call_at)}{res}"
    if s.connected_calls and last_touch and _days(last_touch, now) >= 30 and (s.deal_open or not s.won_at):
        return "went_cold", f"Last real conversation, then quiet since {_when(last_touch)}"
    if s.deal_open and s.deal_updated_at and _days(s.deal_updated_at, now) >= 21:
        return "stuck", f"In “{s.deal_stage}” since {_when(s.deal_updated_at)}"
    if s.created_at and _days(s.created_at, now) >= 180 and (not last_touch or _days(last_touch, now) >= 90):
        return "revive", f"Added {_when(s.created_at)}, quiet since {_when(last_touch) or 'then'}"
    return None


def build_plays(signals: list[Signals], now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(UTC)
    groups: dict[str, list[dict]] = {k: [] for k in PLAY_KEYS}
    for s in signals:
        hit = classify(s, now)
        if not hit:
            continue
        play, reason = hit
        groups[play].append({"external_id": s.external_id, "name": s.name, "phone": s.phone, "company": s.company,
                             "email": s.email, "reason": reason, "stage": s.deal_stage or s.status,
                             "last_touch": (s.last_call_at or s.last_inbound_at or s.last_activity_at or s.created_at
                                            or now).isoformat()})
    # Most recent first inside each play (hot: freshest inbound; others: oldest touch is least urgent).
    for k in groups:
        groups[k].sort(key=lambda x: x["last_touch"], reverse=(k == "hot"))
    return {"scanned": len(signals), "plays": [{**p, "count": len(groups[p["key"]]), "items": groups[p["key"]]}
                                               for p in PLAYS]}
