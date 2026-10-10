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

COUNTED = ("reserved", "completed")
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


def parse_full_address(text: str) -> dict:
    """Split '123 Main St, Erie, PA 16503' into parts. `confident` is False when the user should check them."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    m = _FULL.match(text)
    if not m:
        parts = [p.strip() for p in text.split(",") if p.strip()]
        return {"street": parts[0] if parts else text, "city": parts[1] if len(parts) > 1 else "",
                "state": "", "zip": "", "confident": False}
    state = clean_state(m.group("state"))
    out = {"street": m.group("street").strip(), "city": m.group("city").strip(), "state": state,
           "zip": clean_zip(m.group("zip") or "")}
    out["confident"] = bool(state and out["zip"] and re.match(r"^\d", out["street"]))
    return out


# ── Allowance ─────────────────────────────────────────────────────────────────


def today_utc(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


def next_reset(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc) + timedelta(days=1)


def daily_limit(org: Organization) -> int:
    return org.lead_finder_daily_limit if org.lead_finder_daily_limit is not None else settings.lead_finder_daily_limit


def enabled(org: Organization) -> bool:
    return org.lead_finder_enabled is not False


async def used_today(db, org_id) -> int:
    return (await db.execute(select(func.count()).select_from(PropertyLookup).where(
        PropertyLookup.org_id == org_id, PropertyLookup.lookup_date == today_utc(),
        PropertyLookup.status.in_(COUNTED)))).scalar_one()


# One lock per org serializes reservations inside this process; on Postgres the
# org row lock (SELECT … FOR UPDATE) does the same across processes.
_locks: dict = {}


def _lock(org_id) -> asyncio.Lock:
    return _locks.setdefault(org_id, asyncio.Lock())


async def reserve(db, org: Organization, user_id, addr: dict, key: str) -> PropertyLookup:
    """Atomically take one unit of today's allowance. Raises LookupError_(429) when none is left."""
    async with _lock(org.id):
        await db.execute(select(Organization.id).where(Organization.id == org.id).with_for_update())
        # A reservation older than this was stranded by a crash or redeploy: release it.
        stale = datetime.now(timezone.utc) - timedelta(minutes=5)
        await db.execute(update(PropertyLookup).where(
            PropertyLookup.org_id == org.id, PropertyLookup.status == "reserved", PropertyLookup.created_at < stale,
        ).values(status="failed", error_code="interrupted", error="Lookup interrupted before it finished"))
        inflight = (await db.execute(select(PropertyLookup.id).where(
            PropertyLookup.org_id == org.id, PropertyLookup.address_key == key,
            PropertyLookup.status == "reserved"))).first()
        if inflight:
            await db.commit()  # releases the row lock; nothing was written
            raise LookupError_(409, "in_progress", "This address is already being looked up. Give it a moment.")
        if await used_today(db, org.id) >= daily_limit(org):
            await db.commit()
            raise LookupError_(429, "quota", "You've used your property lookups for today. Your allowance resets tomorrow.")
        row = PropertyLookup(org_id=org.id, user_id=user_id, lookup_date=today_utc(), address_key=key,
                             street=addr["street"], city=addr["city"], state=addr["state"], zip=addr["zip"],
                             status="reserved")
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
        phones.append({"number": e164, "display": display, "type": ptype, "dnc": p.get("dnc") is not False})
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
    """Best number for the lead record: a non-DNC mobile, then any non-DNC number. Never a DNC-listed one."""
    for want in ("mobile", None):
        for p in phones:
            if not p["dnc"] and (want is None or p["type"] == want):
                return p
    return None


def one_line(a: dict) -> str:
    tail = " ".join(x for x in (a.get("state"), a.get("zip")) if x)
    return ", ".join(x for x in (a.get("address"), a.get("city"), tail) if x)
