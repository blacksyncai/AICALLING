"""Plivo number inventory, search, purchase and release (calls go through the Zentrunk LiveKit trunk)."""
import re

import httpx

from app.config import settings


class PlivoError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def ready() -> bool:
    return bool(settings.plivo_auth_id and settings.plivo_auth_token and settings.livekit_sip_plivo_trunk_id)


async def _request(method: str, path: str, **kw) -> dict:
    if not re.fullmatch(r"[A-Z0-9]+", settings.plivo_auth_id):
        raise PlivoError("Invalid Plivo Auth ID.")
    url = f"https://api.plivo.com/v1/Account/{settings.plivo_auth_id}/{path}"
    try:
        async with httpx.AsyncClient(auth=(settings.plivo_auth_id, settings.plivo_auth_token), timeout=20) as client:
            r = await client.request(method, url, **kw)
    except httpx.HTTPError:
        raise PlivoError("Couldn't reach Plivo. Try again.") from None
    if r.status_code in (401, 403):
        raise PlivoError(f"Plivo rejected the request (HTTP {r.status_code}). Check the Auth ID and token.")
    if r.status_code >= 400:
        try:
            msg = r.json().get("error") or ""
        except ValueError:
            msg = ""
        raise PlivoError(f"Plivo error (HTTP {r.status_code}){': ' + str(msg)[:200] if msg else ''}.", status_code=r.status_code)
    try:
        return r.json() if r.content else {}
    except ValueError:
        return {}


async def list_numbers() -> list[dict]:
    if not ready():
        return []
    out, offset = [], 0
    for _ in range(50):
        data = await _request("GET", "Number/", params={"limit": 20, "offset": offset})
        for n in data.get("objects") or []:
            if n.get("voice_enabled") is False:
                continue
            num = "+" + str(n["number"]).lstrip("+")
            out.append({"sid": f"plivo:{num}", "number": num, "friendly": n.get("alias") or "Plivo",
                        "carrier": "plivo", "trunk_sid": ""})
        if not (data.get("meta") or {}).get("next"):
            return out
        offset += 20
    return out


async def search_available(area_code: str = "", contains: str = "", limit: int = 20) -> list[dict]:
    if area_code and not re.fullmatch(r"\d{3}", area_code):
        raise PlivoError("Area code must be 3 digits.")
    if contains and not re.fullmatch(r"\d{3,7}", contains):
        raise PlivoError("Number search must be 3 to 7 digits.")
    params = {"country_iso": "US", "type": "local", "services": "voice", "limit": max(1, min(limit, 20))}
    if area_code:
        params["pattern"] = area_code + (contains or "")
    elif contains:
        params["pattern"] = contains
    data = await _request("GET", "PhoneNumber/", params=params)
    return [{"number": "+" + str(n["number"]).lstrip("+"), "friendly": "+" + str(n["number"]).lstrip("+"),
             "locality": n.get("city") or n.get("rate_center") or "", "region": n.get("region") or "",
             "carrier": "plivo"}
            for n in data.get("objects") or [] if n.get("voice_enabled", True)]


async def buy(number: str) -> dict:
    if not re.fullmatch(r"\+1\d{10}", number):
        raise PlivoError("Choose a US local number from search results.")
    data = await _request("POST", f"PhoneNumber/{number[1:]}/", json={})
    if data.get("status") not in ("fulfilled", "pending") and not data.get("numbers"):
        raise PlivoError("Couldn't confirm the purchased number. Check Plivo before retrying.")
    return {"sid": f"plivo:{number}", "number": number}


async def release(sid: str) -> None:
    number = sid.removeprefix("plivo:")
    if not re.fullmatch(r"\+1\d{10}", number):
        raise PlivoError("Invalid Plivo number.")
    await _request("DELETE", f"Number/{number[1:]}/")


# ── Caller Reputation (AT&T / T-Mobile spam-label registration) ───────────────
# The business is registered once as a Plivo Profile; each number is then attached to it.
# https://www.plivo.com/docs/voice/concepts/caller-reputation


async def reputation_profile() -> str:
    """UUID of the account's Profile that carriers approved for Caller Reputation ("" if none yet)."""
    # The list response has no enable_caller_reputation field, only the status; APPROVED means at
    # least one carrier approved the business, which is what attaching numbers requires.
    data = await _request("GET", "Profile/")
    for p in data.get("profiles") or data.get("objects") or []:
        if p.get("caller_reputation_status") == "APPROVED":
            return str(p.get("profile_uuid") or "")
    return ""


def _reputation(data: dict) -> dict:
    by = {carrier: {"status": (v or {}).get("status") or "", "reason": (v or {}).get("reason") or "",
                    "reason_code": (v or {}).get("reason_code") or ""}
          for carrier, v in (data.get("caller_reputation_by_carrier") or {}).items()}
    return {"status": data.get("caller_reputation_status") or "NOT_REGISTERED", "carriers": by}


async def reputation_status(number: str) -> dict:
    return _reputation(await _request("GET", f"Number/{number.lstrip('+')}/"))


async def enable_reputation(number: str, profile_uuid: str) -> dict:
    data = await _request("POST", f"Number/{number.lstrip('+')}/",
                          json={"caller_reputation": "enabled", "profile_uuid": profile_uuid})
    return _reputation(data)


async def inventory_numbers() -> set[str]:
    """Complete account inventory, including non-voice numbers. Partial data is an error."""
    if not settings.plivo_auth_id or not settings.plivo_auth_token:
        raise PlivoError("Plivo inventory credentials are not configured.")
    found: set[str] = set()
    for page in range(50):
        data = await _request("GET", "Number/", params={"limit": 20, "offset": page * 20})
        objects, meta = data.get("objects"), data.get("meta")
        if not isinstance(objects, list) or not isinstance(meta, dict) or "next" not in meta:
            raise PlivoError("Incomplete Plivo inventory response; no local numbers changed.")
        for item in objects:
            number = "+" + str(item.get("number") or "").lstrip("+") if isinstance(item, dict) else ""
            if not re.fullmatch(r"\+[1-9]\d{7,14}", number) or number in found:
                raise PlivoError("Invalid or repeated Plivo inventory entry.")
            found.add(number)
        if not meta["next"]:
            if meta.get("total_count") is not None and int(meta["total_count"]) != len(found):
                raise PlivoError("Plivo inventory count did not match; no local numbers changed.")
            return found
        if not objects:
            raise PlivoError("Plivo inventory pagination is incomplete.")
    raise PlivoError("Plivo inventory pagination limit reached; no local numbers changed.")


async def number_exists(number: str) -> bool:
    try:
        data = await _request("GET", f"Number/{number.lstrip('+')}/")
    except PlivoError as exc:
        if exc.status_code == 404:
            return False
        raise
    if "+" + str(data.get("number") or "").lstrip("+") != number:
        raise PlivoError("Plivo number ownership could not be verified.")
    return True
