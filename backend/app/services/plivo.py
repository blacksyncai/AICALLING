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
            body = r.json()
            msg = body.get("error") or body.get("message") or body
        except ValueError:
            msg = r.text or ""
        raise PlivoError(f"Plivo error (HTTP {r.status_code}) on {method} {path.split('?')[0]}"
                         f"{': ' + str(msg)[:300] if msg else ''}.", status_code=r.status_code)
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


# ── Inbound: callbacks on Plivo numbers reach BlackSync ───────────────────────
# A Plivo Zentrunk inbound trunk sends calls on its numbers to LiveKit's SIP endpoint with digest auth; a matching
# LiveKit inbound trunk (same credentials) accepts them and a dispatch rule starts our agent (see inbound.route_call).
# Attaching a number sets its Plivo app_id to the trunk, replacing whatever Plivo application it used before.

INBOUND_NAME = "BlackSync Plivo inbound"
_INBOUND: dict = {}


async def _plivo_inbound_trunk() -> dict | None:
    data = await _request("GET", "Zentrunk/Trunk/")
    return next((t for t in data.get("objects", []) if t.get("name") == INBOUND_NAME
                 and t.get("trunk_direction") == "inbound"), None)


async def ensure_inbound_trunk(first_number: str) -> tuple[str, str]:
    """(Plivo trunk id, LiveKit trunk id) for callbacks, created together with fresh credentials when either is
    missing."""
    import secrets

    from livekit import api

    from app.services.inbound import _lk

    if _INBOUND.get("plivo") and _INBOUND.get("livekit"):
        return _INBOUND["plivo"], _INBOUND["livekit"]
    if not ready() or not settings.livekit_ready or not re.fullmatch(r"[a-zA-Z0-9.-]+", settings.livekit_sip_host or ""):
        raise PlivoError("Plivo inbound routing isn't configured on the platform.")
    lk = _lk()
    try:
        lk_trunk = next((t for t in (await lk.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())).items
                         if t.name == INBOUND_NAME), None)
        pl_trunk = await _plivo_inbound_trunk()
        if lk_trunk is None or pl_trunk is None or not lk_trunk.auth_username:
            # Plivo: 5-20 characters, letters and digits plus at least one of ~!@#$%^&*()_+
            alnum = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
            user = "bsplivo" + secrets.token_hex(4)
            password = "".join(secrets.choice(alnum) for _ in range(17)) + secrets.choice("!@#*_+") + secrets.choice(alnum)
            uri = await _request("POST", "Zentrunk/URI/", json={
                "name": INBOUND_NAME, "uri": settings.livekit_sip_host, "authentication_needed": True,
                "username": user, "password": password})
            uri_id = uri.get("uri_uuid")
            if not uri_id:
                raise PlivoError("Plivo didn't create the inbound SIP URI.")
            if pl_trunk is None:
                created = await _request("POST", "Zentrunk/Trunk/", json={
                    "name": INBOUND_NAME, "trunk_direction": "inbound", "primary_uri_uuid": uri_id})
                pl_id = created.get("trunk_id")
            else:
                pl_id = pl_trunk["trunk_id"]
                await _request("POST", f"Zentrunk/Trunk/{pl_id}/", json={"primary_uri_uuid": uri_id})
            if lk_trunk is None:
                lk_trunk = await lk.sip.create_inbound_trunk(api.CreateSIPInboundTrunkRequest(trunk=api.SIPInboundTrunkInfo(
                    name=INBOUND_NAME, numbers=["+" + first_number.lstrip("+")], auth_username=user, auth_password=password, krisp_enabled=True)))
            else:
                lk_trunk = await lk.sip.update_inbound_trunk_fields(lk_trunk.sip_trunk_id, auth_username=user,
                                                                   auth_password=password)
        else:
            pl_id = pl_trunk["trunk_id"]
        if not pl_id:
            raise PlivoError("Plivo didn't create the inbound trunk.")
        lk_id = lk_trunk.sip_trunk_id
        # A dispatch rule that starts our agent for calls on this trunk.
        agent_name = settings.livekit_agent_name or "closer"
        rules = (await lk.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())).items
        if not any(lk_id in r.trunk_ids for r in rules):
            import json as _json

            await lk.sip.create_dispatch_rule(api.CreateSIPDispatchRuleRequest(
                rule=api.SIPDispatchRule(dispatch_rule_individual=api.SIPDispatchRuleIndividual(room_prefix="call-")),
                trunk_ids=[lk_id], name=INBOUND_NAME,
                room_config=api.RoomConfiguration(agents=[api.RoomAgentDispatch(
                    agent_name=agent_name, metadata=_json.dumps({"call_type": "inbound"}))])))
    finally:
        await lk.aclose()
    _INBOUND.update(plivo=pl_id, livekit=lk_id)
    return pl_id, lk_id


async def route_inbound(number: str) -> None:
    """Send inbound calls on this Plivo number to BlackSync."""
    from livekit import api

    from app.services.inbound import _lk

    pl_id, lk_id = await ensure_inbound_trunk(number)
    e164 = "+" + number.lstrip("+")
    lk = _lk()
    try:
        trunk = next((t for t in (await lk.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())).items
                      if t.sip_trunk_id == lk_id), None)
        if trunk is not None and e164 not in trunk.numbers:
            await lk.sip.update_inbound_trunk_fields(lk_id, numbers=api.ListUpdate(add=[e164]))
    finally:
        await lk.aclose()
    await _request("POST", f"Number/{e164.lstrip('+')}/", json={"app_id": pl_id})
