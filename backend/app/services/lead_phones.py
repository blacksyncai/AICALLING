"""
A contact's phone numbers, in call order, and which one a campaign dials next.

Lead.phones holds the ordered list: [{"number", "label", "status", "attempts", "round", "last_attempt_at"}].
Lead.phone is always the first (primary) number, so everything that reads a single phone keeps working, and a
contact with no list behaves as a one-number list.

Number statuses: untried, no_answer, voicemail, wrong_number, disconnected, do_not_call, reached. Wrong number,
disconnected and do-not-call apply to that one number; a do-not-call request from the person (Lead.do_not_call)
stops the whole contact.

With a campaign's "Try other numbers" on, the dialer works through the numbers in order: each number gets
`rounds_per_number` tries ("round" counts them within the current pass), then the next number. A pass through every
dialable number is one of the campaign's tries for the contact; after it, the campaign's retry schedule decides when
the next pass starts, again from number 1.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.contacts import normalize_phone

SKIP = ("wrong_number", "disconnected", "do_not_call")
STATUSES = ("untried", "no_answer", "voicemail", *SKIP, "reached")
DEFAULT_ROUNDS = 2
DEFAULT_GAP_MINUTES = 10
MAX_NUMBERS = 10


def _entry(number: str, label: str = "", status: str = "untried") -> dict:
    return {"number": number, "label": label, "status": status if status in STATUSES else "untried",
            "attempts": 0, "round": 0, "last_attempt_at": None}


def numbers(lead) -> list[dict]:
    """The contact's numbers in call order (a contact without a list has just its primary number)."""
    rows = [dict(p) for p in (getattr(lead, "phones", None) or []) if isinstance(p, dict) and p.get("number")]
    if not rows and getattr(lead, "phone", None):
        rows = [_entry(lead.phone, "primary")]
    return rows


def build(raw: list, keep: list[dict] | None = None) -> list[dict]:
    """A clean number list from strings or {"number", "label", "status"} dicts: E.164, no blanks or repeats, in the
    given order. Numbers already on the contact (`keep`) keep their status and attempt counts."""
    old = {p["number"]: p for p in (keep or []) if isinstance(p, dict) and p.get("number")}
    out, seen = [], set()
    for item in raw or []:
        if isinstance(item, dict):
            number, label, status = item.get("number") or item.get("phone") or "", item.get("label") or "", item.get("status")
        else:
            number, label, status = str(item or ""), "", None
        number = normalize_phone(str(number))
        if len(number) < 11 or number in seen:
            continue
        seen.add(number)
        entry = dict(old[number]) if number in old else _entry(number, str(label)[:30])
        if label:
            entry["label"] = str(label)[:30]
        if status in STATUSES:
            entry["status"] = status
        out.append(entry)
        if len(out) >= MAX_NUMBERS:
            break
    return out


def set_numbers(lead, raw: list) -> None:
    """Replace the contact's numbers; the first becomes the primary (Lead.phone)."""
    rows = build(raw, numbers(lead))
    if not rows:
        return
    lead.phones = rows
    lead.phone = rows[0]["number"]


def add_numbers(lead, raw: list) -> int:
    """Append numbers the contact doesn't have yet (in order). Returns how many were added."""
    current = numbers(lead)
    have = {p["number"] for p in current}
    extra = [p for p in build(raw) if p["number"] not in have]
    if extra:
        lead.phones = (current + extra)[:MAX_NUMBERS]
        if not lead.phone:
            lead.phone = lead.phones[0]["number"]
    return len(extra)


def all_numbers(lead) -> list[str]:
    return [p["number"] for p in numbers(lead)]


def dialable(lead) -> list[dict]:
    return [p for p in numbers(lead) if p.get("status") not in SKIP]


def sequencing(campaign) -> bool:
    return bool(getattr(campaign, "try_other_numbers", None))


def rounds(campaign) -> int:
    return max(1, min(10, getattr(campaign, "rounds_per_number", None) or DEFAULT_ROUNDS))


def gap_minutes(campaign) -> int:
    return getattr(campaign, "number_gap_minutes", None) or DEFAULT_GAP_MINUTES


def pick(lead, campaign) -> str | None:
    """The number the campaign dials next for this contact (None: no number left to dial)."""
    if not sequencing(campaign):
        primary = numbers(lead)[:1]
        return primary[0]["number"] if primary and primary[0].get("status") not in SKIP else None
    live = dialable(lead)
    if not live:
        return None
    n = rounds(campaign)
    for p in live:
        if (p.get("round") or 0) < n:
            return p["number"]
    return live[0]["number"]  # the pass is done: the next one starts again from number 1


def mid_pass(lead, campaign) -> bool:
    """True while the current pass still has a number with rounds left (those dials don't use up a campaign try)."""
    if not sequencing(campaign):
        return False
    n = rounds(campaign)
    live = dialable(lead)
    started = any((p.get("round") or 0) > 0 for p in live)
    return started and any((p.get("round") or 0) < n for p in live)


def record_dial(lead, campaign, number: str, now: datetime | None = None) -> bool:
    """Count a dial on `number`. Returns True when it starts a new pass (that is one of the campaign's tries)."""
    now = now or datetime.now(timezone.utc)
    rows = numbers(lead)
    n = rounds(campaign) if sequencing(campaign) else 1
    live = [p for p in rows if p.get("status") not in SKIP]
    starts_pass = not any(0 < (p.get("round") or 0) for p in live) or all((p.get("round") or 0) >= n for p in live)
    if starts_pass:
        for p in rows:
            p["round"] = 0
    for p in rows:
        if p["number"] == number:
            p["attempts"] = (p.get("attempts") or 0) + 1
            p["round"] = (p.get("round") or 0) + 1
            p["last_attempt_at"] = now.isoformat()
    lead.phones = rows
    return starts_pass


def pass_done(lead, campaign) -> bool:
    """After a dial: every dialable number has had its rounds in this pass (the retry schedule decides what's next)."""
    if not sequencing(campaign):
        return True
    n = rounds(campaign)
    return all((p.get("round") or 0) >= n for p in dialable(lead))


def mark(lead, number: str | None, status: str) -> None:
    """Set one number's status after a call (e.g. no_answer, voicemail, wrong_number, reached)."""
    if not number or status not in STATUSES:
        return
    rows = numbers(lead)
    hit = False
    for p in rows:
        if p["number"] == number:
            # A number that reached the person or was ruled out keeps that over a later unanswered call.
            if p.get("status") in (*SKIP, "reached") and status in ("no_answer", "voicemail"):
                return
            p["status"] = status
            hit = True
    if hit:
        lead.phones = rows


def status_for_outcome(outcome: str | None) -> str | None:
    """A call outcome as the dialed number's status."""
    if not outcome:
        return None
    if outcome in ("no_answer", "screened", "failed", "busy"):
        return "no_answer"
    if outcome == "voicemail":
        return "voicemail"
    if outcome in ("wrong_number", "do_not_call"):
        return outcome
    return "reached"


def public(lead) -> list[dict]:
    """The numbers as the API and the app show them."""
    return [{"number": p["number"], "label": p.get("label") or ("primary" if i == 0 else str(i + 1)),
             "status": p.get("status") or "untried", "attempts": p.get("attempts") or 0,
             "last_attempt_at": p.get("last_attempt_at")} for i, p in enumerate(numbers(lead))]
