"""Plivo number inventory, search, purchase and release (calls go through the Zentrunk LiveKit trunk)."""
import re

import httpx

from app.config import settings


class PlivoError(RuntimeError):
    pass


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
        raise PlivoError(f"Plivo error (HTTP {r.status_code}){': ' + str(msg)[:200] if msg else ''}.")
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
