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
    {"key": "never_called", "title": "Haven't been contacted", "why": "In your CRM for a day or more and nobody has called or reached out.",
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
    source: str = ""  # lead source / lead flow (e.g. Zillow, Cold call)
    pond: str = ""
    tags: list[str] = field(default_factory=list)
    dnc: bool = False
    contacted: bool | None = None  # the CRM's own "has anyone contacted them" flag, when it keeps one
    calls_known: bool = True  # False when the scan didn't read call history (quick / old-lead batches)
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
    never = s.contacted is False or (s.calls_known and s.calls == 0 and s.contacted is not True)
    if never and s.created_at and _days(s.created_at, now) >= 1:
        return "never_called", f"Added {_when(s.created_at)}, " + ("nobody has contacted them" if s.contacted is False else "never called")
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


def build_segment(signals: list[Signals], title: str, why: str, now: dt.datetime | None = None) -> dict:
    """Everyone in one CRM list (pond, lead source, stage) as a single play, minus do-not-call."""
    now = now or dt.datetime.now(UTC)
    items = []
    for s in signals:
        if s.dnc:
            continue
        last = s.last_activity_at or s.created_at
        reason = (f"Last activity {_when(last)}" if last else "In this list") + (f" · {s.deal_stage}" if s.deal_stage else "")
        items.append({"external_id": s.external_id, "name": s.name, "phone": s.phone, "company": s.company,
                      "email": s.email, "reason": reason, "stage": s.deal_stage or s.status, "source": s.source,
                      "pond": s.pond, "tags": s.tags[:20], "created": s.created_at.isoformat() if s.created_at else None,
                      "calls": None, "contacted": s.contacted, "last_touch": (last or now).isoformat()})
    return {"scanned": len(signals), "plays": [{"key": "segment", "title": title, "why": why,
            "suggest": "Pick who to call, or the whole list, and hand them to an agent.", "count": len(items),
            "items": items}]}


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
                             "source": s.source, "pond": s.pond, "tags": s.tags[:20],
                             "created": s.created_at.isoformat() if s.created_at else None,
                             "calls": s.calls if s.calls_known else None, "contacted": s.contacted,
                             "last_touch": (s.last_call_at or s.last_inbound_at or s.last_activity_at or s.created_at
                                            or now).isoformat()})
    # Most recent first inside each play (hot: freshest inbound; others: oldest touch is least urgent).
    for k in groups:
        groups[k].sort(key=lambda x: x["last_touch"], reverse=(k == "hot"))
    return {"scanned": len(signals), "plays": [{**p, "count": len(groups[p["key"]]), "items": groups[p["key"]]}
                                               for p in PLAYS]}


def merge(previous: dict, batch: dict) -> dict:
    """Add a new scan batch to an earlier scan's plays (people already listed aren't repeated)."""
    out = {"scanned": (previous.get("scanned") or 0) + (batch.get("scanned") or 0), "plays": []}
    old = {pl["key"]: pl for pl in previous.get("plays") or []}
    for pl in batch["plays"]:
        before = (old.get(pl["key"]) or {}).get("items") or []
        seen = {i["external_id"] for i in before}
        items = before + [i for i in pl["items"] if i["external_id"] not in seen]
        items.sort(key=lambda x: x["last_touch"], reverse=(pl["key"] == "hot"))
        out["plays"].append({**pl, "items": items, "count": len(items)})
    return out
