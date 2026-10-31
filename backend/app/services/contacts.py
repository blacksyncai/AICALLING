"""
Contacts — CSV parsing shared by the contacts page and campaign imports.
"""

from __future__ import annotations

import csv
import io

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


def parse_contacts_csv(text: str) -> tuple[list[dict], int]:
    """
    Rows from CSV text (header row required). Needs a phone column;
    name (or first/last), company, email and role are recognised and every
    other column becomes a custom field usable as {{column}} in prompts.
    Returns (contacts, skipped_rows).
    """
    reader = csv.DictReader(io.StringIO(text.strip().lstrip("﻿")))
    if not reader.fieldnames:
        raise CsvError("CSV needs a header row")
    cols = {c: (c or "").strip().lower() for c in reader.fieldnames}
    if not any(low in _PHONE_KEYS for low in cols.values()):
        raise CsvError("CSV needs a phone column (e.g. 'phone')")

    def pick(row: dict, keys: tuple) -> tuple[str, str | None]:
        for orig, low in cols.items():
            if low in keys and (row.get(orig) or "").strip():
                return row[orig].strip(), orig
        return "", None

    contacts, skipped = [], 0
    for row in reader:
        phone, phone_col = pick(row, _PHONE_KEYS)
        phone = normalize_phone(phone)
        if len(phone) < 11:
            skipped += 1
            continue
        name, name_col = pick(row, _NAME_KEYS)
        first, first_col = pick(row, _FIRST_KEYS)
        last, last_col = pick(row, _LAST_KEYS)
        if not name:
            name = f"{first} {last}".strip()
        used = {phone_col, name_col, first_col, last_col}
        known: dict[str, str] = {}
        for field, keys in _KNOWN.items():
            val, col = pick(row, keys)
            known[field] = val
            used.add(col)
        custom = {
            cols[c].replace(" ", "_"): (v or "").strip()
            for c, v in row.items() if c and (c not in used or cols[c] in {"phone1", "phone 1", "primary phone", "owner first name", "owner last name"}) and (v or "").strip()
        }
        contacts.append({"name": name or phone, "phone": phone, **known, "custom_fields": custom or None})
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
