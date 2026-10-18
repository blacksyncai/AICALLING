"""Per-account caller IDs: SignalWire purchases by default, with explicit Twilio backup.

SignalWire purchases use the shared outbound LiveKit trunk; inbound routing is
not provisioned here. Purchased numbers are released through their own carrier.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.agent import Agent
from app.models.billing import PhoneNumber

log = structlog.get_logger(__name__)

_API = "https://api.twilio.com/2010-04-01"
_TRUNKING = "https://trunking.twilio.com/v1"


class TelephonyError(RuntimeError):
    """A provider or configuration problem, with a message safe to show an admin."""


def _client() -> httpx.AsyncClient:
    if not settings.twilio_ready:
        raise TelephonyError("Twilio isn't configured — set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN.")
    return httpx.AsyncClient(auth=(settings.twilio_account_sid, settings.twilio_auth_token), timeout=20.0)


def _account_url(path: str) -> str:
    return f"{_API}/Accounts/{settings.twilio_account_sid}/{path}"


async def _request(method: str, url: str, **kwargs) -> dict:
    async with _client() as client:
        try:
            resp = await client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise TelephonyError(f"Couldn't reach Twilio: {exc.__class__.__name__}") from exc
    if resp.status_code == 204:
        return {}
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400:
        msg = data.get("message") or resp.text[:200] or f"HTTP {resp.status_code}"
        log.warning("twilio_error", status=resp.status_code, code=data.get("code"), message=msg, url=url.split("?")[0])
        if resp.status_code == 401:
            raise TelephonyError("Twilio rejected the credentials — check TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN.")
        raise TelephonyError(f"Twilio: {msg}")
    return data


def normalize(number: str) -> str:
    from app.services.outbound_call import validate_e164

    return validate_e164(number)


# ── Twilio ────────────────────────────────────────────────────────────────────

_trunk_cache: dict[str, str] = {}


async def livekit_trunk_address() -> str:
    """The SIP host the LiveKit outbound trunk dials (e.g. xyz.pstn.twilio.com)."""
    from livekit import api

    from app.services.outbound_call import _lk

    if not settings.livekit_sip_outbound_trunk_id:
        return ""
    lk = _lk()
    try:
        resp = await lk.sip.list_outbound_trunk(api.ListSIPOutboundTrunkRequest(
            trunk_ids=[settings.livekit_sip_outbound_trunk_id]))
        return resp.items[0].address if resp.items else ""
    finally:
        await lk.aclose()


async def trunk_sid() -> str:
    """The Twilio Elastic SIP trunk behind the LiveKit outbound trunk."""
    if settings.twilio_trunk_sid:
        return settings.twilio_trunk_sid
    if "sid" in _trunk_cache:
        return _trunk_cache["sid"]
    address = (await livekit_trunk_address()).lower()
    data = await _request("GET", f"{_TRUNKING}/Trunks", params={"PageSize": 100})
    trunks = data.get("trunks") or []
    match = next((t for t in trunks if address and (t.get("domain_name") or "").lower() == address), None)
    if match is None and len(trunks) == 1:
        match = trunks[0]
    if match is None:
        raise TelephonyError("Couldn't find the Twilio SIP trunk — set TWILIO_TRUNK_SID.")
    _trunk_cache["sid"] = match["sid"]
    return match["sid"]


def purchase_carriers() -> list[str]:
    from app.services import signalwire
    return (["signalwire"] if signalwire.ready() else []) + (["twilio"] if settings.twilio_ready else [])


def purchase_carrier(carrier: str | None = None) -> str:
    available = purchase_carriers()
    selected = carrier or (available[0] if available else "")
    if selected not in available:
        raise TelephonyError("The selected number provider is not configured.")
    return selected


async def search_available(area_code: str = "", contains: str = "", country: str = "US", limit: int = 20, carrier: str | None = None) -> list[dict]:
    selected = purchase_carrier(carrier)
    if selected == "signalwire":
        from app.services import signalwire
        if country.upper() != "US":
            raise TelephonyError("Only US local numbers are supported here.")
        try:
            return await signalwire.search_available(area_code, contains, limit)
        except signalwire.SignalWireError as exc:
            raise TelephonyError(str(exc)) from exc
    params: dict = {"VoiceEnabled": "true", "PageSize": max(1, min(limit, 50))}
    if area_code:
        if not area_code.isdigit() or len(area_code) != 3:
            raise TelephonyError("Area code must be 3 digits.")
        params["AreaCode"] = area_code
    if contains:
        params["Contains"] = contains
    country = (country or "US").upper()[:2]
    data = await _request("GET", _account_url(f"AvailablePhoneNumbers/{country}/Local.json"), params=params)
    return [
        {"number": n["phone_number"], "friendly": n.get("friendly_name") or n["phone_number"],
         "locality": n.get("locality") or "", "region": n.get("region") or "", "carrier": "twilio"}
        for n in data.get("available_phone_numbers") or []
    ]


async def list_owned(warnings: list[str] | None = None) -> list[dict]:
    """Every number in the Twilio account (first 1000), plus the Bandwidth account's numbers."""
    out = []
    if settings.twilio_ready:
        data = await _request("GET", _account_url("IncomingPhoneNumbers.json"), params={"PageSize": 1000})
        out = [
            {"sid": n["sid"], "number": n["phone_number"], "friendly": n.get("friendly_name") or "",
             "trunk_sid": n.get("trunk_sid") or "", "carrier": "twilio"}
            for n in data.get("incoming_phone_numbers") or []
        ]
    if settings.bandwidth_ready:
        from app.services import bandwidth

        try:
            out += [{"sid": f"bw:{n}", "number": n, "friendly": "Bandwidth", "trunk_sid": "", "carrier": "bandwidth"}
                    for n in await bandwidth.list_numbers()]
        except bandwidth.BandwidthError as exc:
            log.warning("bandwidth_numbers_failed", error=str(exc))
    from app.services import signalwire
    if signalwire.ready():
        try:
            out += await signalwire.list_numbers()
        except signalwire.SignalWireError as exc:
            warning = str(exc)
            try:
                configured = await signalwire.configured_numbers()
                out += configured
                if configured:
                    warning += " Showing caller IDs already configured on the SignalWire SIP trunk. Other purchased numbers may be missing."
            except signalwire.SignalWireError as fallback_exc:
                warning += " " + str(fallback_exc)
            if warnings is not None:
                warnings.append(warning)
            elif not out:
                raise TelephonyError(warning) from exc
    return out


async def _buy(number: str) -> dict:
    return await _request("POST", _account_url("IncomingPhoneNumbers.json"), data={
        "PhoneNumber": number, "TrunkSid": await trunk_sid(), "FriendlyName": "BlackSync",
    })


async def _release_twilio(sid: str) -> None:
    await _request("DELETE", _account_url(f"IncomingPhoneNumbers/{sid}.json"))


# ── LiveKit trunk caller IDs ──────────────────────────────────────────────────


async def _livekit_numbers(add: list[str] | None = None, remove: list[str] | None = None) -> None:
    """Keep the LiveKit outbound trunk's number list in step (it's the allowed caller-ID list)."""
    from livekit import api

    from app.services.outbound_call import _lk

    if not settings.livekit_sip_outbound_trunk_id or not settings.livekit_ready:
        return
    lk = _lk()
    try:
        await lk.sip.update_outbound_trunk_fields(
            settings.livekit_sip_outbound_trunk_id, numbers=api.ListUpdate(add=add or [], remove=remove or []),
        )
    except Exception as exc:  # caller ID still works when the trunk doesn't restrict numbers
        log.warning("livekit_trunk_numbers_update_failed", error=str(exc), add=add, remove=remove)
    finally:
        await lk.aclose()


# ── Account numbers ───────────────────────────────────────────────────────────


async def _inbound_ready(number: str) -> None:
    """Accept inbound calls to this number in LiveKit right away (best effort; Go live re-checks)."""
    try:
        from app.services.inbound import ensure_routing

        await ensure_routing(number)
    except Exception as exc:
        log.warning("inbound_routing_setup_failed", number=number, error=str(exc)[:200])


async def sync_inbound_numbers() -> int:
    """Startup: make sure every active account number is on the LiveKit inbound trunk."""
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        nums = (await db.execute(select(PhoneNumber.number).where(
            PhoneNumber.status == "active",
            (PhoneNumber.carrier.is_(None)) | (PhoneNumber.carrier == "twilio")))).scalars().all()  # Bandwidth: own trunk
    for n in nums:
        await _inbound_ready(n)
    return len(nums)


async def active_numbers(db: AsyncSession, org_id: uuid.UUID) -> list[PhoneNumber]:
    return list((await db.execute(
        select(PhoneNumber).where(PhoneNumber.org_id == org_id, PhoneNumber.status == "active")
        .order_by(PhoneNumber.created_at)
    )).scalars().all())


async def _claim_row(db: AsyncSession, org_id: uuid.UUID, number: str) -> PhoneNumber:
    """A fresh row for the number, reusing a released one (numbers are unique)."""
    row = (await db.execute(select(PhoneNumber).where(PhoneNumber.number == number))).scalar_one_or_none()
    if row is not None:
        if row.status == "active":
            raise TelephonyError("That number is already assigned to an account.")
        from app.services.number_registration import retire_number
        await retire_number(db, row)
        row.org_id, row.status, row.released_at = org_id, "active", None
        row.created_at = datetime.now(timezone.utc)
        row.label, row.is_default = "", None
        return row
    row = PhoneNumber(id=uuid.uuid4(), org_id=org_id, number=number)
    db.add(row)
    return row


async def _make_default_if_first(db: AsyncSession, row: PhoneNumber) -> None:
    others = [n for n in await active_numbers(db, row.org_id) if n.id != row.id]
    if not any(n.is_default for n in others):
        row.is_default = True


async def purchase(db: AsyncSession, org_id: uuid.UUID, number: str, label: str = "", *, carrier: str | None = None) -> PhoneNumber:
    number = normalize(number)
    existing = (await db.execute(select(PhoneNumber).where(PhoneNumber.number == number,
                                                           PhoneNumber.status == "active"))).scalar_one_or_none()
    if existing:
        raise TelephonyError("That number is already assigned to an account.")
    selected = purchase_carrier(carrier)
    from app.services import signalwire
    try:
        bought = await signalwire.buy(number) if selected == "signalwire" else await _buy(number)
    except signalwire.SignalWireError as exc:
        raise TelephonyError(str(exc)) from exc
    try:
        if selected == "signalwire":
            await signalwire.allow_number(number)
        row = await _claim_row(db, org_id, number)
        row.provider_sid, row.source, row.label = bought["sid"], "purchased", label.strip()[:100]
        row.carrier = "signalwire" if selected == "signalwire" else None
        await db.flush()
        await _make_default_if_first(db, row)
        from app.services.number_registration import enqueue_number
        await enqueue_number(db, row)
        await db.commit()
    except Exception as exc:
        log.error("phone_number_save_failed_releasing", number=number)
        await db.rollback()
        try:
            await signalwire.release(bought["sid"]) if selected == "signalwire" else await _release_twilio(bought["sid"])
        except Exception:
            log.error("phone_number_release_after_failure_failed", number=number, sid=bought.get("sid"))
        if isinstance(exc, signalwire.SignalWireError):
            raise TelephonyError(str(exc)) from exc
        raise
    if selected != "signalwire":
        await _livekit_numbers(add=[number])
        await _inbound_ready(number)
    log.info("phone_number_purchased", org_id=str(org_id), number=number)
    return row


async def import_owned(db: AsyncSession, org_id: uuid.UUID, number: str, label: str = "") -> PhoneNumber:
    """Assign a number that's already in the Twilio (or Bandwidth) account."""
    number = normalize(number)
    owned = {n["number"]: n for n in await list_owned()}
    if number not in owned:
        raise TelephonyError("That number isn't in a configured carrier account.")
    carrier = owned[number].get("carrier")
    if carrier == "signalwire":
        from app.services import signalwire
        try:
            await signalwire.allow_number(number)
        except signalwire.SignalWireError as exc:
            raise TelephonyError(str(exc)) from exc
    row = await _claim_row(db, org_id, number)
    row.provider_sid, row.source, row.label = owned[number]["sid"], "imported", label.strip()[:100]
    row.carrier = carrier if carrier in ("bandwidth", "signalwire") else None
    await db.flush()
    await _make_default_if_first(db, row)
    from app.services.number_registration import enqueue_number
    await enqueue_number(db, row)
    await db.commit()
    if row.carrier == "bandwidth":
        from app.services import bandwidth

        await bandwidth.ensure_bridge_trunk([number])
    elif row.carrier != "signalwire":
        await _livekit_numbers(add=[number])
        await _inbound_ready(number)
    log.info("phone_number_imported", org_id=str(org_id), number=number)
    return row


async def release(db: AsyncSession, row: PhoneNumber, *, return_to_twilio: bool) -> None:
    """Remove a number from its account; purchased numbers can also be released back to Twilio."""
    if row.status != "active":
        return
    if return_to_twilio and row.source == "purchased" and row.provider_sid:
        if row.carrier == "signalwire":
            from app.services import signalwire
            try:
                await signalwire.release(row.provider_sid)
            except signalwire.SignalWireError as exc:
                raise TelephonyError(str(exc)) from exc
        else:
            await _release_twilio(row.provider_sid)
    from app.services.number_registration import retire_number
    await retire_number(db, row)
    was_default = bool(row.is_default)
    row.status, row.released_at, row.is_default = "released", datetime.now(timezone.utc), None
    await db.execute(update(Agent).where(Agent.org_id == row.org_id, Agent.caller_number == row.number)
                     .values(caller_number=None))
    await db.flush()
    if was_default:
        rest = await active_numbers(db, row.org_id)
        if rest:
            rest[0].is_default = True
    await db.commit()
    if row.carrier not in ("signalwire", "bandwidth"):
        await _livekit_numbers(remove=[row.number])
    log.info("phone_number_released", org_id=str(row.org_id), number=row.number, returned=return_to_twilio)


async def set_default(db: AsyncSession, row: PhoneNumber) -> None:
    await db.execute(update(PhoneNumber).where(PhoneNumber.org_id == row.org_id).values(is_default=None))
    row.is_default = True
    await db.commit()


async def caller_id_for(db: AsyncSession, org_id: uuid.UUID, agent: Agent | None) -> str:
    """The number a call goes out from: the agent's pick, else the account default, else the trunk's."""
    numbers = await active_numbers(db, org_id)
    if not numbers:
        return ""
    if agent is not None and agent.caller_number:
        if any(n.number == agent.caller_number for n in numbers):
            return agent.caller_number
    default = next((n for n in numbers if n.is_default), numbers[0])
    return default.number


async def carrier_of(db: AsyncSession, org_id: uuid.UUID, number: str) -> str:
    """"bandwidth" when the account's number is a Bandwidth one, else "twilio"."""
    if not number:
        return "twilio"
    row = (await db.execute(select(PhoneNumber).where(PhoneNumber.org_id == org_id, PhoneNumber.number == number,
                                                      PhoneNumber.status == "active"))).scalar_one_or_none()
    return row.carrier if row is not None and row.carrier in ("bandwidth", "signalwire") else "twilio"


def number_to_dict(n: PhoneNumber) -> dict:
    return {
        "id": str(n.id), "number": n.number, "label": n.label, "source": n.source or "assigned",
        "carrier": n.carrier or "twilio",
        "is_default": bool(n.is_default), "status": n.status,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }
