"""
Lead Finder — DataSkip property-owner lookups, the per-organization daily
allowance, and turning a result into a lead.

DataSkip contract (POST {SKIPTRACE_API_URL}/api/v1/skip-trace, Bearer key):
  request  {"address": street line only, "city", "state", "zip"}
  response {"success", "found", "charged", "contact": {firstName, lastName, fullName,
            propertyAddress/City/State/Zip, mailingAddress/City/State/Zip} | null,
            "phones": [{"number", "type": "mobile"|"landline", "dnc"}], "emails": [...]}
  errors   400 invalid request · 401 bad key · 402 insufficient balance · 429 rate limited (Retry-After)
A match is billed (use `charged` as returned); a miss isn't.

The API key only ever lives in settings.skiptrace_api_key on the backend. Nothing
here logs addresses, names, phones or emails.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from sqlalchemy import func, select, update

from app.config import settings
from app.models.account import Organization
from app.models.lead_finder import PropertyLookup

log = structlog.get_logger(__name__)

TIMEOUT_S = 30.0

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY",
    "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
    "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "PR", "VI", "GU",
}
STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "district of columbia": "DC", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA",
    "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "puerto rico": "PR",
}
_SUFFIXES = {
    "street": "st", "avenue": "ave", "road": "rd", "drive": "dr", "lane": "ln", "boulevard": "blvd",
    "court": "ct", "place": "pl", "terrace": "ter", "circle": "cir", "highway": "hwy", "parkway": "pkwy",
    "north": "n", "south": "s", "east": "e", "west": "w", "apartment": "apt", "suite": "ste",
}


class LookupError_(Exception):
    """A lookup that didn't complete. `status` is the HTTP status for our API; `code` is for admins."""

    def __init__(self, status: int, code: str, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.retry_after = status, code, message, retry_after


# ── Addresses ─────────────────────────────────────────────────────────────────


def clean_state(raw: str) -> str:
    s = (raw or "").strip()
    if s.upper() in US_STATES:
        return s.upper()
    return STATE_NAMES.get(s.lower().rstrip("."), "")


def clean_zip(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 5:
        return digits
    if len(digits) == 9:
        return f"{digits[:5]}-{digits[5:]}"
    return ""


def _norm_part(s: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split()
    return " ".join(_SUFFIXES.get(w, w) for w in words)


def address_key(street: str, city: str, state: str, zip_code: str) -> str:
    """Identity of a lookup: normalized street, city, state and 5-digit ZIP."""
    return "|".join([_norm_part(street), _norm_part(city), state.upper(), (zip_code or "")[:5]])


def validate_address(street: str, city: str, state: str, zip_code: str) -> dict:
    """Clean the four fields or raise ValueError with a plain message. Street must be the street line only."""
    street = re.sub(r"\s+", " ", (street or "").strip())
    city = re.sub(r"\s+", " ", (city or "").strip())
    st = clean_state(state)
    z = clean_zip(zip_code) if (zip_code or "").strip() else ""
    if not street or not re.search(r"\d", street) or len(street) < 4:
        raise ValueError("Enter the street address, including the house number.")
    if "," in street:
        raise ValueError("Put only the street line in Street Address — city, state and ZIP go in their own fields.")
    if len(street) > 200 or len(city) > 100:
        raise ValueError("That address is too long.")
    if not city:
        raise ValueError("Enter the city.")
    if not st:
        raise ValueError("Enter a US state (for example CA or California).")
    if (zip_code or "").strip() and not z:
        raise ValueError("Enter a 5-digit ZIP code.")
    return {"street": street, "city": city, "state": st, "zip": z}


_FULL = re.compile(
    r"^\s*(?P<street>[^,]+?)\s*,\s*(?P<city>[^,]+?)\s*,?\s+(?P<state>[A-Za-z]{2}|[A-Za-z ]{4,20}?)\.?\s*,?\s*(?P<zip>\d{5}(?:-?\d{4})?)?\s*(?:,\s*(?:USA|US|United States))?\s*$",
    re.I,
)


_STREET_END = re.compile(
    r"^(?P<street>\d[\w\s.'#-]*?\b(?:st|street|ave|avenue|rd|road|dr|drive|ln|lane|blvd|boulevard|ct|court|pl|place|"
    r"way|ter|terrace|cir|circle|hwy|highway|pkwy|parkway|trl|trail|loop|sq|square|pike|row|run|path|xing)\.?"
    r"(?:\s+(?:n|s|e|w|ne|nw|se|sw|north|south|east|west))?"
    r"(?:\s+(?:apt|unit|ste|suite|#)\s*[\w-]+)?)\s+(?P<city>[a-z][a-z .'-]*?)$",
    re.I,
)
_TAIL = re.compile(r"^(?P<head>.+)[\s,]+(?P<state>[A-Za-z]{2})\.?[\s,]*(?P<zip>\d{5}(?:-?\d{4})?)?\s*$")
_ZIP_END = re.compile(r"[\s,]*(?P<zip>\d{5}(?:-?\d{4})?)\s*$")


def _split_tail(text: str):
    """(head, state, zip) when the text ends in a state (abbreviation or full name) and optional ZIP."""
    t = _TAIL.match(text)
    if t and clean_state(t.group("state")):
        return t.group("head"), clean_state(t.group("state")), clean_zip(t.group("zip") or "")
    z = _ZIP_END.search(text)
    body, zip_code = (text[: z.start()], clean_zip(z.group("zip"))) if z else (text, "")
    low = body.lower().rstrip(" ,.")
    for name in sorted(STATE_NAMES, key=len, reverse=True):
        if low.endswith(" " + name) or low.endswith("," + name):
            return body.rstrip(" ,.")[: -len(name)], STATE_NAMES[name], zip_code
    return None


def parse_full_address(text: str) -> dict:
    """Split '123 Main St, Erie, PA 16503' (commas optional) into parts.
    `confident` is False when the user should check the fields."""
    text = re.sub(r"\s+", " ", (text or "").replace("\n", ", ").strip())
    text = re.sub(r",?\s*(?:USA|US|United States)\.?$", "", text, flags=re.I).strip(" ,")
    m = _FULL.match(text)
    if m and clean_state(m.group("state")):
        state = clean_state(m.group("state"))
        out = {"street": m.group("street").strip(), "city": m.group("city").strip(), "state": state,
               "zip": clean_zip(m.group("zip") or "")}
        out["confident"] = bool(out["zip"] and re.match(r"^\d", out["street"]))
        return out
    # No commas (or only some): peel "STATE ZIP" off the end, then split street/city at the street suffix.
    tail = _split_tail(text)
    if tail:
        head, state, zip_code = tail
        head = head.strip(" ,")
        sm = None
        if "," in head:
            street, city = [x.strip() for x in head.rsplit(",", 1)]
        else:
            sm = _STREET_END.match(head)
            street, city = (sm.group("street").strip(), sm.group("city").strip()) if sm else (head, "")
        confident = bool(city and zip_code and re.match(r"^\d", street) and ("," in head or sm))
        return {"street": street, "city": city, "state": state, "zip": zip_code, "confident": confident}
    parts = [p.strip() for p in text.split(",") if p.strip()]
    return {"street": parts[0] if parts else text, "city": parts[1] if len(parts) > 1 else "",
            "state": "", "zip": "", "confident": False}


# ── Lead-lookup credits (separate from calling credits) ───────────────────────


def today_utc(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


def enabled(org: Organization) -> bool:
    return org.lead_finder_enabled is not False


def credits_of(org: Organization) -> int:
    return org.lead_credits_balance or 0


def unlimited(org: Organization) -> bool:
    return org.lead_credits_unlimited is True


# One lock per org serializes credit holds inside this process; on Postgres the
# org row lock (SELECT … FOR UPDATE) does the same across processes.
_locks: dict = {}


def _lock(org_id) -> asyncio.Lock:
    return _locks.setdefault(org_id, asyncio.Lock())


class NotEnoughCredits(Exception):
    def __init__(self, needed: int, available: int):
        super().__init__(f"needed {needed}, have {available}")
        self.needed, self.available = needed, available


async def hold_credits(db, org: Organization, n: int) -> None:
    """Atomically set aside n credits (worst case: every address matches). Commits.
    Raises NotEnoughCredits. Matches turn holds into ledger usage; misses and failures give them back."""
    if n <= 0 or unlimited(org):
        return
    async with _lock(org.id):
        row = (await db.execute(select(Organization.lead_credits_balance).where(Organization.id == org.id)
                                .with_for_update())).first()
        have = (row[0] if row else 0) or 0
        if have < n:
            await db.commit()
            raise NotEnoughCredits(n, have)
        await db.execute(update(Organization).where(Organization.id == org.id)
                         .values(lead_credits_balance=Organization.lead_credits_balance - n))
        await db.commit()
    await db.refresh(org, ["lead_credits_balance"])


async def release_credits(db, org: Organization, n: int) -> None:
    """Give back held credits that weren't used (no match / failure). Caller commits."""
    if n <= 0 or unlimited(org):
        return
    await db.execute(update(Organization).where(Organization.id == org.id)
                     .values(lead_credits_balance=func.coalesce(Organization.lead_credits_balance, 0) + n))


async def record_usage(db, org: Organization, n: int, note: str, user_id=None, lookup_id=None, batch_id=None) -> None:
    """Ledger entry for credits actually spent (the balance was already reduced by hold_credits). Caller commits."""
    from app.models.lead_finder import LeadCreditTransaction

    if n <= 0:
        return
    await db.flush()
    bal = (await db.execute(select(Organization.lead_credits_balance).where(Organization.id == org.id))).scalar_one()
    db.add(LeadCreditTransaction(org_id=org.id, amount=-n, balance_after=bal or 0, kind="usage", note=note,
                                 lookup_id=lookup_id, batch_id=batch_id, created_by=user_id))


async def grant_credits(db, org: Organization, amount: int, note: str, user_id=None) -> int:
    """Admin grant (positive) or adjustment (negative, never below zero). Commits; returns the new balance."""
    from app.models.lead_finder import LeadCreditTransaction

    async with _lock(org.id):
        cur = (await db.execute(select(Organization.lead_credits_balance).where(Organization.id == org.id)
                                .with_for_update())).scalar_one() or 0
        new = max(0, cur + amount)
        await db.execute(update(Organization).where(Organization.id == org.id).values(lead_credits_balance=new))
        db.add(LeadCreditTransaction(org_id=org.id, amount=new - cur, balance_after=new,
                                     kind="grant" if amount > 0 else "adjustment", note=note[:500], created_by=user_id))
        await db.commit()
    await db.refresh(org, ["lead_credits_balance"])
    return new


STALE_AFTER = timedelta(minutes=5)


async def release_stale(db, org: Organization) -> None:
    """Single lookups stranded by a crash or redeploy: mark failed and give their held credit back."""
    cutoff = datetime.now(timezone.utc) - STALE_AFTER
    stale = (await db.execute(select(PropertyLookup).where(
        PropertyLookup.org_id == org.id, PropertyLookup.status == "reserved", PropertyLookup.batch_id.is_(None),
        PropertyLookup.created_at < cutoff))).scalars().all()
    for r in stale:
        r.status, r.error_code, r.error = "failed", "interrupted", "Lookup interrupted before it finished"
    if stale:
        await release_credits(db, org, len(stale))
        await db.commit()


async def start_lookup(db, org: Organization, user_id, addr: dict, key: str) -> PropertyLookup:
    """Hold one credit and create the in-flight lookup row. Raises LookupError_(402/409)."""
    await release_stale(db, org)
    inflight = (await db.execute(select(PropertyLookup.id).where(
        PropertyLookup.org_id == org.id, PropertyLookup.address_key == key,
        PropertyLookup.status == "reserved", PropertyLookup.batch_id.is_(None)))).first()
    if inflight:
        raise LookupError_(409, "in_progress", "This address is already being looked up. Give it a moment.")
    try:
        await hold_credits(db, org, 1)
    except NotEnoughCredits:
        raise LookupError_(402, "no_credits", "You're out of lead lookup credits. Ask your BlackSync admin to add more.")
    row = PropertyLookup(org_id=org.id, user_id=user_id, lookup_date=today_utc(), address_key=key,
                         street=addr["street"], city=addr["city"], state=addr["state"], zip=addr["zip"],
                         status="reserved", credits=0)
    db.add(row)
    await db.commit()
    return row


# ── Simple per-user request throttle (abuse protection, separate from the allowance) ──

_hits: dict = {}
MAX_REQUESTS_PER_MINUTE = 10


def throttle(user_id) -> None:
    now = datetime.now(timezone.utc).timestamp()
    recent = [t for t in _hits.get(user_id, []) if now - t < 60]
    if len(recent) >= MAX_REQUESTS_PER_MINUTE:
        raise LookupError_(429, "throttled", "Too many lookup requests. Wait a minute and try again.")
    recent.append(now)
    _hits[user_id] = recent


# ── DataSkip ──────────────────────────────────────────────────────────────────


def _fmt_phone(raw: str) -> tuple[str, str]:
    """(E.164, display) for a US number; non-US numbers are kept as given."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"+1{digits}", f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return (raw or "").strip(), (raw or "").strip()


def _s(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _flag(v) -> bool | None:
    """DataSkip's DNC flag: True/False only when the provider said so explicitly; None when missing or unclear."""
    if v is True or v == 1:
        return True
    if v is False or v == 0:
        return False
    if isinstance(v, str):
        t = v.strip().lower()
        if t in ("true", "yes", "y", "1"):
            return True
        if t in ("false", "no", "n", "0"):
            return False
    return None


def normalize_result(data: dict) -> dict:
    """The provider response reduced to what we show and store. Never invents values."""
    c = data.get("contact") if isinstance(data.get("contact"), dict) else {}
    phones, seen = [], set()
    for p in data.get("phones") or []:
        if not isinstance(p, dict) or not _s(p.get("number")):
            continue
        e164, display = _fmt_phone(p["number"])
        if e164 in seen:
            continue
        seen.add(e164)
        ptype = p.get("type") if p.get("type") in ("mobile", "landline") else "unknown"
        phones.append({"number": e164, "display": display, "type": ptype, "dnc": _flag(p.get("dnc"))})
    emails = list(dict.fromkeys(e.strip().lower() for e in (data.get("emails") or [])
                                if isinstance(e, str) and "@" in e))
    contact = {
        "first_name": _s(c.get("firstName")), "last_name": _s(c.get("lastName")), "full_name": _s(c.get("fullName")),
        "property": {"address": _s(c.get("propertyAddress")), "city": _s(c.get("propertyCity")),
                     "state": _s(c.get("propertyState")), "zip": _s(c.get("propertyZip"))},
        "mailing": {"address": _s(c.get("mailingAddress")), "city": _s(c.get("mailingCity")),
                    "state": _s(c.get("mailingState")), "zip": _s(c.get("mailingZip"))},
    }
    if not contact["full_name"]:
        contact["full_name"] = " ".join(x for x in (contact["first_name"], contact["last_name"]) if x)
    return {"contact": contact, "phones": phones, "emails": emails}


async def call_dataskip(addr: dict) -> dict:
    """One request, no automatic retry (a match is billed). Returns the parsed JSON or raises LookupError_."""
    payload = {"address": addr["street"], "city": addr["city"], "state": addr["state"]}
    if addr["zip"]:
        payload["zip"] = addr["zip"]
    url = f"{settings.skiptrace_api_url.rstrip('/')}/api/v1/skip-trace"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            resp = await client.post(url, json=payload, headers={"Authorization": f"Bearer {settings.skiptrace_api_key}"})
    except httpx.TimeoutException:
        raise LookupError_(502, "network", "The property lookup timed out. Please try again.")
    except httpx.HTTPError:
        raise LookupError_(502, "network", "We couldn't reach the property data service. Please try again.")

    s = resp.status_code
    if s == 400:
        raise LookupError_(400, "invalid_request", "We couldn't look up that address. Check the street, city, state and ZIP and try again.")
    if s in (401, 403):
        raise LookupError_(503, "auth", "Property lookup is temporarily unavailable due to a service configuration issue. Please try again later.")
    if s == 402:
        raise LookupError_(503, "balance", "Property lookup is temporarily unavailable. Please try again later.")
    if s == 429:
        try:
            retry = max(1, min(3600, int(float(resp.headers.get("Retry-After", "60")))))
        except ValueError:
            retry = 60
        raise LookupError_(503, "rate_limited", f"Property lookup is busy right now. Please try again in about {retry} seconds.", retry)
    if s >= 400:
        raise LookupError_(502, "provider_error", "The property data service had a problem. Please try again.")
    try:
        data = resp.json()
    except ValueError:
        raise LookupError_(502, "provider_error", "The property data service returned an unreadable answer. Please try again.")
    if not isinstance(data, dict) or data.get("success") is False:
        raise LookupError_(502, "provider_error", "The property data service had a problem. Please try again.")
    return data


# ── Leads ─────────────────────────────────────────────────────────────────────


def primary_phone(phones: list[dict]) -> dict | None:
    """Best number for the lead record: an unflagged mobile, then any unflagged number, then the first number."""
    for want in ("mobile", None):
        for p in phones:
            if p.get("dnc") is not True and (want is None or p["type"] == want):
                return p
    return phones[0] if phones else None


def one_line(a: dict) -> str:
    tail = " ".join(x for x in (a.get("state"), a.get("zip")) if x)
    return ", ".join(x for x in (a.get("address"), a.get("city"), tail) if x)


# ── Bulk (CSV of addresses) ───────────────────────────────────────────────────

MAX_BULK_ROWS = 1000
BULK_CHUNK = 100          # DataSkip's per-request maximum
MAX_CSV_BYTES = 2 * 1024 * 1024

_STREET = ("street", "street_address", "address1", "address_1", "address_line_1", "property_address", "site_address",
           "property_street", "address")
_CITY = ("city", "property_city", "site_city", "town")
_STATE = ("state", "st", "property_state", "site_state", "province")
_ZIP = ("zip", "zipcode", "zip_code", "postal_code", "postal", "property_zip", "site_zip")
_FULL_COLS = ("full_address", "full address", "address_full", "property_full_address", "address")


def _col(fields: dict, names) -> str | None:
    for n in names:
        if n in fields:
            return fields[n]
    return None


def parse_address_csv(text: str) -> tuple[list[dict], list[dict], int]:
    """(valid rows, invalid rows, total data rows). Address columns only; anything else in the file is ignored.

    Accepts separate street/city/state/zip columns, or one full-address column."""
    import csv
    import io

    text = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("That file has no header row. Add columns like Address, City, State, Zip.")
    fields = {re.sub(r"[^a-z0-9 ]+", "_", (f or "").strip().lower()).replace(" ", "_").strip("_"): f
              for f in reader.fieldnames}
    fields.update({(f or "").strip().lower(): f for f in reader.fieldnames})
    street_c, city_c, state_c, zip_c = (_col(fields, _STREET), _col(fields, _CITY), _col(fields, _STATE), _col(fields, _ZIP))
    full_c = None if (city_c and state_c) else _col(fields, _FULL_COLS)
    if not ((street_c and city_c and state_c) or full_c):
        raise ValueError("We couldn't find address columns. Use Address, City, State and Zip columns, "
                         "or one Full Address column like \"123 Main St, Erie, PA 16503\".")
    valid, invalid, seen, total = [], [], set(), 0
    for i, rec in enumerate(reader, start=2):  # row 1 is the header
        if not any((v or "").strip() for v in rec.values() if isinstance(v, str)):
            continue
        total += 1
        if total > MAX_BULK_ROWS:
            raise ValueError(f"That file has more than {MAX_BULK_ROWS:,} addresses. Split it into smaller files.")
        if full_c and not (city_c and state_c):
            p = parse_full_address(rec.get(full_c) or "")
            street, city, state, zip_code = p["street"], p["city"], p["state"], p["zip"]
        else:
            street, city = rec.get(street_c) or "", rec.get(city_c) or ""
            state, zip_code = rec.get(state_c) or "", (rec.get(zip_c) or "") if zip_c else ""
        try:
            a = validate_address(street, city, state, zip_code)
        except ValueError as exc:
            invalid.append({"row": i, "reason": str(exc)})
            continue
        key = address_key(a["street"], a["city"], a["state"], a["zip"])
        if key in seen:
            invalid.append({"row": i, "reason": "Duplicate of an earlier row."})
            continue
        seen.add(key)
        valid.append({"row": i, **a, "key": key})
    return valid, invalid, total


async def call_dataskip_bulk(addrs: list[dict]) -> list[dict]:
    """Up to 100 addresses in one request. Results come back in the same order. Raises LookupError_."""
    payload = {"addresses": [{k: v for k, v in {"address": a["street"], "city": a["city"], "state": a["state"],
                                                 "zip": a["zip"]}.items() if v} for a in addrs]}
    url = f"{settings.skiptrace_api_url.rstrip('/')}/api/v1/skip-trace-bulk"
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers={"Authorization": f"Bearer {settings.skiptrace_api_key}"})
    except httpx.HTTPError:
        raise LookupError_(502, "network", "We couldn't reach the property data service.")
    s_ = resp.status_code
    if s_ == 429:
        try:
            retry = max(1, min(300, int(float(resp.headers.get("Retry-After", "30")))))
        except ValueError:
            retry = 30
        raise LookupError_(503, "rate_limited", "Rate limited", retry)
    if s_ in (401, 403):
        raise LookupError_(503, "auth", "Provider rejected the API key")
    if s_ == 402:
        raise LookupError_(503, "balance", "Provider balance too low")
    if s_ == 400:
        raise LookupError_(400, "invalid_request", "Provider rejected the request")
    if s_ >= 400:
        raise LookupError_(502, "provider_error", f"Provider error {s_}")
    try:
        data = resp.json()
    except ValueError:
        raise LookupError_(502, "provider_error", "Unreadable provider response")
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list) or len(results) != len(addrs):
        raise LookupError_(502, "provider_error", "Provider returned an unexpected number of results")
    return results
