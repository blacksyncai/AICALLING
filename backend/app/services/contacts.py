"""
Contacts — CSV parsing shared by the contacts page and campaign imports.
"""

from __future__ import annotations

import csv
import io
import re

_PHONE_KEYS = ("phone", "phone_number", "mobile", "number", "phone number", "telephone", "cell", "phone1", "phone 1", "primary phone")
_NAME_KEYS = ("name", "full_name", "full name", "contact", "contact_name")
_FIRST_KEYS = ("first_name", "first name", "firstname", "owner first name")
_LAST_KEYS = ("last_name", "last name", "lastname", "surname", "owner last name")
_KNOWN = {"company": ("company", "company_name", "organization", "business"),
          "email": ("email", "email_address", "e-mail"),
          "role": ("role", "title", "job_title", "position")}


class CsvError(ValueError):
    pass


def normalize_phone(raw: str) -> str:
    raw = (raw or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""
    if raw.startswith("+"):
        return "+" + digits
    if len(digits) == 10:          # assume North American number without country code
        return "+1" + digits
    return "+" + digits


_PHONE_COL = re.compile(
    r"^(?:primary |owner |contact |best )?(phone|phone number|phone_number|phonenumber|mobile|mobile phone|cell|"
    r"cell phone|cellphone|home|home phone|work|work phone|office phone|telephone|tel|landline|wireless|number)"
    r"(?:[\s_#-]*(\d{1,2}))?(?: number)?$")
_COMPANION = re.compile(r"dnc|do[\s_-]*not[\s_-]*call|status|type|litigator", re.IGNORECASE)
_TRUE = {"y", "yes", "true", "1", "x", "dnc", "do not call", "on dnc", "flagged"}


def phone_columns(fieldnames: list[str]) -> list[str]:
    """The file's phone columns in the order they appear (Phone, Phone 2, Mobile, Home, Work, Cell...)."""
    return [c for c in fieldnames if c and _PHONE_COL.match(c.strip().lower()) and not _COMPANION.search(c)]


def _number_status(value: str, col: str) -> str | None:
    """A per-number flag or status cell (e.g. Vortex "Phone 2 DNC" = "Yes") as a number status."""
    v = (value or "").strip().lower()
    if not v:
        return None
    if "dnc" in col.lower() or "do not call" in col.lower().replace("_", " ") or "litigator" in col.lower():
        return "do_not_call" if v in _TRUE or "dnc" in v or "litigator" in v else None
    if "disconnect" in v or "invalid" in v or "bad" in v:
        return "disconnected"
    if "wrong" in v:
        return "wrong_number"
    if "dnc" in v or "do not call" in v or "litigator" in v:
        return "do_not_call"
    return None


def _companions(fieldnames: list[str], phones: list[str]) -> dict[str, list[str]]:
    """Flag/status columns and the phone column each one belongs to ("Phone 2 DNC" -> "Phone 2", "DNC" -> first)."""
    out: dict[str, list[str]] = {p: [] for p in phones}
    if not phones:
        return out
    for c in fieldnames:
        if not c or c in phones or not _COMPANION.search(c) or (_COMPANION.search(c).group(0).lower() == "type"):
            continue
        low = c.strip().lower()
        owner = max((p for p in phones if low.startswith(p.strip().lower())), key=len, default=None)
        if owner is None:
            digits = re.findall(r"\d+", low)
            if digits:
                owner = next((p for p in phones if (_PHONE_COL.match(p.strip().lower()).group(2) or "1") == digits[0]),
                             None)
            elif low in ("dnc", "do not call", "do_not_call", "dnc flag", "phone status", "status"):
                owner = phones[0]
        if owner is not None:
            out[owner].append(c)
    return out


def parse_contacts_csv(text: str, phone_cols: list[str] | None = None,
                       skip_dnc: bool = False) -> tuple[list[dict], int]:
    """
    Rows from CSV text (header row required). Needs a phone column; every phone column (Phone, Phone 2...,
    Mobile, Home, Work, Cell) is kept in the file's order. A per-number DNC flag in the file only marks that
    number do-not-call when `skip_dnc` is on (off by default: flagged numbers are called like any other);
    disconnected / wrong-number statuses are always carried over. `phone_cols` (column names, in call order) overrides the automatic detection.
    Name (or first/last), company, email and role are recognised and every other column becomes a custom
    field usable as {{column}} in prompts.
    Returns (contacts, skipped_rows).
    """
    reader = csv.DictReader(io.StringIO(text.strip().lstrip("\ufeff")))
    if not reader.fieldnames:
        raise CsvError("CSV needs a header row")
    fields = [c for c in reader.fieldnames if c]
    cols = {c: (c or "").strip().lower() for c in reader.fieldnames}
    if phone_cols:
        wanted = {p.strip().lower() for p in phone_cols}
        phones = [c for p in phone_cols for c in fields if c.strip().lower() == p.strip().lower()]
        phones = list(dict.fromkeys(phones))
        if not phones or len(phones) < len(wanted):
            raise CsvError("Some of the phone columns you picked aren't in the file")
    else:
        phones = phone_columns(fields)
    if not phones:
        raise CsvError("CSV needs a phone column (e.g. 'phone')")
    flags = _companions(fields, phones)
    flag_cols = {c for cs in flags.values() for c in cs}

    def pick(row: dict, keys: tuple) -> tuple[str, str | None]:
        for orig, low in cols.items():
            if low in keys and (row.get(orig) or "").strip():
                return row[orig].strip(), orig
        return "", None

    contacts, skipped = [], 0
    for row in reader:
        numbers, seen = [], set()
        for col in phones:
            number = normalize_phone(row.get(col) or "")
            if len(number) < 11 or number in seen:
                continue
            seen.add(number)
            status = next((st for f in flags[col] if (st := _number_status(row.get(f) or "", f))), None)
            if status == "do_not_call" and not skip_dnc:
                status = None
            numbers.append({"number": number, "label": col.strip()[:30], "status": status or "untried"})
        if not numbers:
            skipped += 1
            continue
        # Numbers ruled out by the file go last, so the primary is one the dialer may call.
        numbers.sort(key=lambda n: n["status"] != "untried")
        name, name_col = pick(row, _NAME_KEYS)
        first, first_col = pick(row, _FIRST_KEYS)
        last, last_col = pick(row, _LAST_KEYS)
        if not name:
            name = f"{first} {last}".strip()
        used = {*phones, *flag_cols, name_col, first_col, last_col}
        known: dict[str, str] = {}
        for field, keys in _KNOWN.items():
            val, col = pick(row, keys)
            known[field] = val
            used.add(col)
        # Owner name and the first phone column also stay available as {{variables}}, as before.
        keep_as_var = {"phone1", "phone 1", "primary phone", "owner first name", "owner last name"}
        custom = {cols[c].replace(" ", "_"): (v or "").strip()
                  for c, v in row.items() if c and (c not in used or cols[c] in keep_as_var) and (v or "").strip()}
        contacts.append({"name": name or numbers[0]["number"], "phone": numbers[0]["number"],
                         "phones": [{**n, "attempts": 0, "round": 0, "last_attempt_at": None} for n in numbers],
                         **known, "custom_fields": custom or None})
    return contacts, skipped


# How a contact's pipeline status follows its calls. Calls that didn't reach anyone never undo a real result,
# and a vague "we talked" never replaces a clear one. A clear answer on a later call (yes, no, call me back)
# always becomes the new status.
NO_CONVERSATION = ("no_answer", "voicemail", "screened", "failed")
_OPEN = (None, "", "new", "calling", *NO_CONVERSATION)
_VAGUE = ("completed", "hung_up", "language_barrier", "no_decision", "insufficient_conversation", "busy", "declined_conversation")
_RANK = {"interested": 1, "information_requested": 1, "callback": 1, "qualified": 2, "transferred": 3, "meeting_booked": 3}


def next_status(current: str | None, outcome: str | None) -> str | None:
    """The contact's status after a call ended with `outcome` (None: leave it as it is)."""
    if not outcome:
        return None
    if outcome in NO_CONVERSATION:
        return outcome if current in _OPEN else None
    if outcome in _VAGUE:
        return outcome if current in _OPEN or current in _VAGUE else None
    if outcome in _RANK and _RANK.get(current or "", 0) > _RANK[outcome]:
        return None  # a booked meeting isn't undone by a later "interested"
    return outcome
