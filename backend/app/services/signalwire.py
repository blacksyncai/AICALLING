"""Inventory and outbound trunk management; never purchases or releases numbers."""
import re

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
    path = f"/api/laml/2010-04-01/Accounts/{settings.signalwire_project_id}/IncomingPhoneNumbers.json"
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
            for number in data.get("incoming_phone_numbers", []):
                if number.get("capabilities", {}).get("voice") is False:
                    continue
                result.append({"sid": number["sid"], "number": number["phone_number"],
                               "friendly": number.get("friendly_name") or "SignalWire",
                               "carrier": "signalwire", "trunk_sid": ""})
            path = data.get("next_page_uri")
            if not path:
                return result
            # Do not forward API credentials to a pagination URL on another host.
            if not path.startswith("/api/laml/") or "://" in path:
                raise SignalWireError("SignalWire returned an unexpected pagination URL.")
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
    lk = _lk()
    try:
        await lk.sip.update_outbound_trunk_fields(
            settings.signalwire_sip_outbound_trunk_id, numbers=api.ListUpdate(add=[number]))
    except Exception:
        raise SignalWireError("Couldn't add the caller ID to the SignalWire trunk. Try again.") from None
    finally:
        await lk.aclose()
