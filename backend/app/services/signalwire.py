"""Inventory and outbound trunk management; never purchases or releases numbers."""
import re
import copy
from urllib.parse import urljoin, urlparse

import httpx

from app.config import settings


class SignalWireError(RuntimeError):
    pass


def ready() -> bool:
    return bool(settings.signalwire_space and settings.signalwire_project_id
                and settings.signalwire_api_token and settings.signalwire_sip_outbound_trunk_id)


async def list_numbers() -> list[dict]:
    if not ready():
        return []
    space = settings.signalwire_space.strip().lower()
    if not re.fullmatch(r"[a-z0-9-]+\.signalwire\.com", space):
        raise SignalWireError("SignalWire space must be a hostname ending in .signalwire.com.")
    if not re.fullmatch(r"[a-zA-Z0-9-]+", settings.signalwire_project_id):
        raise SignalWireError("Invalid SignalWire project ID.")
    base = f"https://{space}"
    path = "/api/relay/rest/phone_numbers"
    result = []
    async with httpx.AsyncClient(auth=(settings.signalwire_project_id, settings.signalwire_api_token),
                                 timeout=20, follow_redirects=False) as client:
        for _ in range(100):
            try:
                response = await client.get(base + path)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in (401, 403):
                    raise SignalWireError(f"SignalWire rejected number access (HTTP {status}). Check the API token, project ID and number-read permission.") from None
                raise SignalWireError(f"SignalWire number lookup failed (HTTP {status}).") from None
            except (httpx.HTTPError, ValueError):
                raise SignalWireError("Couldn't load SignalWire numbers. Check the API credentials and number-read permission.") from None
            for number in data.get("data", []):
                if number.get("capabilities", {}).get("voice") is False:
                    continue
                result.append({"sid": number["id"], "number": number["number"],
                               "friendly": number.get("name") or "SignalWire",
                               "carrier": "signalwire", "trunk_sid": ""})
            path = (data.get("links") or {}).get("next")
            if not path:
                return result
            # Do not forward API credentials to a pagination URL on another host.
            parsed = urlparse(urljoin(base, path))
            if (parsed.scheme != "https" or parsed.netloc != space
                    or parsed.path != "/api/relay/rest/phone_numbers" or parsed.fragment):
                raise SignalWireError("SignalWire returned an unexpected pagination URL.")
            path = parsed.path + ("?" + parsed.query if parsed.query else "")
    raise SignalWireError("Too many SignalWire numbers to load safely.")


async def configured_numbers() -> list[dict]:
    """Fallback inventory from the explicitly configured, authenticated LiveKit trunk."""
    from livekit import api
    from app.services.outbound_call import _lk

    if not settings.signalwire_sip_outbound_trunk_id:
        return []
    lk = _lk()
    try:
        response = await lk.sip.list_outbound_trunk(api.ListSIPOutboundTrunkRequest(
            trunk_ids=[settings.signalwire_sip_outbound_trunk_id]))
        trunk = next((t for t in response.items
                      if t.sip_trunk_id == settings.signalwire_sip_outbound_trunk_id), None)
        if trunk is None:
            raise SignalWireError("The configured SignalWire LiveKit trunk wasn't found.")
        return [{"sid": f"sw:{n}", "number": n, "friendly": "Configured SignalWire SIP caller ID",
                 "carrier": "signalwire", "trunk_sid": "", "inventory_source": "livekit"}
                for n in trunk.numbers]
    except SignalWireError:
        raise
    except Exception:
        raise SignalWireError("Couldn't read configured SignalWire caller IDs from LiveKit.") from None
    finally:
        await lk.aclose()


async def allow_number(number: str) -> None:
    from livekit import api
    from app.services.outbound_call import _lk

    if not settings.signalwire_sip_outbound_trunk_id:
        raise SignalWireError("Configure the SignalWire LiveKit outbound trunk first.")
    await ensure_dynamic_routing()
    lk = _lk()
    try:
        await lk.sip.update_outbound_trunk_fields(
            settings.signalwire_sip_outbound_trunk_id, numbers=api.ListUpdate(add=[number]))
    except Exception:
        raise SignalWireError("Couldn't add the caller ID to the SignalWire trunk. Try again.") from None
    finally:
        await lk.aclose()


DYNAMIC_CALLER_ID = "%{call.sip_data.sip_from_user}"
DYNAMIC_DESTINATION = "%{call.to.replace(/^sip:/i, '').replace(/@.*/, '')}"


def dynamic_script(contents: dict) -> dict:
    """Patch only the known one-connect outbound script; refuse arbitrary custom call flows."""
    expected = {"version": "1.0.0", "sections": {"main": [{"connect": {
        "answer_on_bridge": True, "from": "", "to": DYNAMIC_DESTINATION}}]}}
    if not isinstance(contents, dict):
        raise SignalWireError("Review the outbound SWML script before enabling multiple caller IDs.")
    candidate = copy.deepcopy(contents)
    try:
        caller = candidate["sections"]["main"][0]["connect"]["from"]
        candidate["sections"]["main"][0]["connect"]["from"] = ""
    except (KeyError, TypeError, IndexError):
        raise SignalWireError("Review the outbound SWML script before enabling multiple caller IDs.") from None
    if candidate != expected or not (caller == DYNAMIC_CALLER_ID or
                                    isinstance(caller, str) and re.fullmatch(r"\+[1-9]\d{7,14}", caller)):
        raise SignalWireError("Custom outbound script detected. Review caller-ID routing before assigning a new number.")
    candidate["sections"]["main"][0]["connect"]["from"] = DYNAMIC_CALLER_ID
    return candidate


async def ensure_dynamic_routing() -> None:
    resource = settings.signalwire_outbound_script_id
    if not resource:
        raise SignalWireError("Configure the shared SignalWire outbound script before assigning more numbers.")
    if not re.fullmatch(r"[a-zA-Z0-9-]+", resource):
        raise SignalWireError("Invalid SignalWire outbound script ID.")
    space = settings.signalwire_space.strip().lower()
    if not re.fullmatch(r"[a-z0-9-]+\.signalwire\.com", space):
        raise SignalWireError("Invalid SignalWire space hostname.")
    url = f"https://{space}/api/fabric/resources/swml_scripts/{resource}"
    async with httpx.AsyncClient(auth=(settings.signalwire_project_id, settings.signalwire_api_token),
                                 timeout=20, follow_redirects=False) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            old = response.json()["swml_script"]["contents"]
            updated = dynamic_script(old)
            if updated == old:
                return
            response = await client.put(url, json={"contents": updated})
            response.raise_for_status()
            # Do not claim repair based only on HTTP success; verify the saved document.
            response = await client.get(url)
            response.raise_for_status()
            if response.json()["swml_script"]["contents"] != updated:
                raise SignalWireError("SignalWire routing update could not be verified.")
        except (httpx.HTTPError, ValueError, KeyError):
            raise SignalWireError("Couldn't verify shared SignalWire caller-ID routing. Check the API token and Voice permission.") from None
