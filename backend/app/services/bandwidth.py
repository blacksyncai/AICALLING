"""
Bandwidth as a second carrier for outbound calls.

Flow for a call from a Bandwidth number:
  1. `place_call` asks Bandwidth's Voice API to ring the contact from our Bandwidth number, and remembers the
     call's prepared agent config as a pending bridge (keyed by our number + the contact's number).
  2. When the contact answers, Bandwidth fetches `answer_bxml`: a <Transfer> of the live call to LiveKit over SIP
     (sip:<our number>@<livekit sip host>, digest login), so it arrives like an inbound call.
  3. LiveKit's dispatch rule puts it in a room with our agent; the worker asks /internal/inbound-call who
     answers, and `take_bridge` hands back the outbound call's config instead of starting a new inbound call.
  4. If nobody answers (or it's busy / rejected), Bandwidth's disconnect callback closes the call as unanswered.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from xml.sax.saxutils import escape, quoteattr

import httpx
import structlog

from app.config import settings

log = structlog.get_logger(__name__)

VOICE_API = "https://voice.bandwidth.com/api/v2"
DASHBOARD_API = "https://dashboard.bandwidth.com/api"
TOKEN_URL = "https://api.bandwidth.com/api/v1/oauth2/token"
BRIDGE_TRUNK_NAME = "Bandwidth bridge"
RING_SECONDS = 45
_BRIDGE_TTL = 180  # a pending bridge older than this is stale (the call rang out long ago)


class BandwidthError(RuntimeError):
    pass


# ── Auth ──────────────────────────────────────────────────────────────────────

_token: dict = {"value": "", "expires": 0.0}
_token_lock = asyncio.Lock()


async def _access_token() -> str:
    async with _token_lock:
        if _token["value"] and _token["expires"] - 60 > time.time():
            return _token["value"]
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(TOKEN_URL, data={"grant_type": "client_credentials"},
                                     auth=(settings.bandwidth_client_id, settings.bandwidth_client_secret))
        if resp.status_code != 200:
            raise BandwidthError(f"Bandwidth sign-in failed ({resp.status_code}).")
        body = resp.json()
        _token["value"] = body["access_token"]
        _token["expires"] = time.time() + float(body.get("expires_in") or 3600)
        return _token["value"]


async def _request(method: str, url: str, **kwargs) -> httpx.Response:
    headers = {"Authorization": f"Bearer {await _access_token()}", **kwargs.pop("headers", {})}
    async with httpx.AsyncClient(timeout=20) as client:
        return await client.request(method, url, headers=headers, **kwargs)


# ── Numbers ───────────────────────────────────────────────────────────────────


async def list_numbers() -> list[str]:
    """Every in-service number on the Bandwidth account, as +E.164."""
    import re

    resp = await _request("GET", f"{DASHBOARD_API}/accounts/{settings.bandwidth_account_id}/inserviceNumbers",
                          params={"size": 1000})
    if resp.status_code != 200:
        raise BandwidthError(f"Couldn't list the Bandwidth numbers ({resp.status_code}).")
    out = []
    for n in re.findall(r"<TelephoneNumber>(\d+)</TelephoneNumber>", resp.text):
        out.append("+" + (n if len(n) > 10 else "1" + n))
    return out


# ── Pending bridges (one API process places every call) ─────────────────────────

_PENDING: dict[str, dict] = {}  # call_log_id → {number, to, metadata, expires, record_key}


def _sign(call_id: str) -> str:
    key = (settings.bandwidth_client_secret or "dev").encode()
    return hmac.new(key, f"bw:{call_id}".encode(), hashlib.sha256).hexdigest()[:32]


def valid_signature(call_id: str, sig: str) -> bool:
    return bool(call_id and sig) and hmac.compare_digest(_sign(call_id), sig)


def _prune() -> None:
    now = time.time()
    for k in [k for k, v in _PENDING.items() if v["expires"] < now]:
        _PENDING.pop(k, None)


def _digits(n: str) -> str:
    d = "".join(c for c in (n or "") if c.isdigit())
    return d[-10:]


def take_bridge(our_number: str, caller: str) -> dict | None:
    """The pending outbound call this SIP hand-off belongs to (removed once taken)."""
    _prune()
    mine = [(k, v) for k, v in _PENDING.items() if v.get("answered") and _digits(v["number"]) == _digits(our_number)]
    hit = [(k, v) for k, v in mine if _digits(v["to"]) == _digits(caller)]
    if not hit and len(mine) == 1:
        hit = mine  # caller ID didn't come through as expected, but only one call is waiting on this number
    if not hit:
        return None
    key, value = hit[0]
    _PENDING.pop(key, None)
    return {"call_log_id": key, **value}


def pending_count() -> int:
    _prune()
    return len(_PENDING)


# ── Calls ─────────────────────────────────────────────────────────────────────


def _callback_url(path: str, call_id: str) -> str:
    base = (settings.app_url or "").rstrip("/")
    return f"{base}/api/telephony/bandwidth/{path}?c={call_id}&s={_sign(call_id)}"


async def place_call(call_id: str, to: str, from_number: str, metadata: str, record_key: str | None = None) -> str:
    """Ask Bandwidth to ring `to` from `from_number`; returns Bandwidth's call id."""
    if not settings.bandwidth_ready:
        raise BandwidthError("Bandwidth calling isn't set up on the platform.")
    _prune()
    _PENDING[call_id] = {"number": from_number, "to": to, "metadata": json.loads(metadata),
                         "record_key": record_key, "expires": time.time() + _BRIDGE_TTL, "answered": False}
    body = {
        "from": from_number, "to": to, "applicationId": settings.bandwidth_application_id,
        "answerUrl": _callback_url("answer", call_id), "answerMethod": "POST",
        "disconnectUrl": _callback_url("disconnect", call_id), "disconnectMethod": "POST",
        "callTimeout": RING_SECONDS, "tag": call_id,
    }
    try:
        resp = await _request("POST", f"{VOICE_API}/accounts/{settings.bandwidth_account_id}/calls", json=body)
    except httpx.HTTPError as exc:
        _PENDING.pop(call_id, None)
        raise BandwidthError("Couldn't reach Bandwidth to place the call.") from exc
    if resp.status_code not in (200, 201):
        _PENDING.pop(call_id, None)
        detail = ""
        try:
            detail = (resp.json().get("description") or resp.json().get("message") or "")[:200]
        except Exception:
            pass
        log.error("bandwidth_call_failed", status=resp.status_code, detail=detail, to=to)
        raise BandwidthError(f"Bandwidth didn't place the call ({resp.status_code}{': ' + detail if detail else ''}).")
    bw_id = resp.json().get("callId", "")
    log.info("bandwidth_call_placed", call_log_id=call_id, bw_call_id=bw_id, to=to, from_number=from_number)
    return bw_id


def answer_bxml(call_id: str) -> str:
    """What Bandwidth does when the contact picks up: hand the call to LiveKit, where the agent is waiting."""
    pending = _PENDING.get(call_id)
    if not pending:
        log.warning("bandwidth_answer_unknown_call", call_log_id=call_id)
        return '<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>'
    pending["answered"] = True
    pending["expires"] = time.time() + 60  # LiveKit should pick it up within seconds
    uri = f"sip:{pending['number']}@{settings.livekit_sip_host}"
    return ('<?xml version="1.0" encoding="UTF-8"?><Response><Transfer>'
            f"<SipUri username={quoteattr(settings.bandwidth_sip_username)} "
            f"password={quoteattr(settings.bandwidth_sip_password)}>{escape(uri)}</SipUri>"
            "</Transfer></Response>")


_NO_ANSWER_CAUSES = {"timeout", "busy", "cancel", "rejected"}


async def on_disconnect(call_id: str, payload: dict) -> None:
    """Bandwidth says the call is over. If it never reached the agent, close it here."""
    pending = _PENDING.pop(call_id, None)
    cause = (payload.get("cause") or "").lower()
    log.info("bandwidth_call_ended", call_log_id=call_id, cause=cause,
             bridged=pending is None, error=(payload.get("errorMessage") or "")[:160])
    if pending is None:
        return  # handed to LiveKit already — the agent reports how it went
    from app.database import AsyncSessionLocal
    from app.models.call_log import CallLog
    from app.services.outbound_call import _mark_call_failed

    async with AsyncSessionLocal() as db:
        call = await db.get(CallLog, uuid.UUID(call_id))
    if call is None or call.ended_at is not None or call.answered_at is not None:
        return
    if cause in _NO_ANSWER_CAUSES or not pending.get("answered"):
        await _mark_call_failed(call.id, call.lead_id, "no_answer", "Not answered.")
    else:
        await _mark_call_failed(call.id, call.lead_id, "failed", "Call failed — the call couldn't be connected.")


# ── LiveKit side: an inbound trunk Bandwidth logs into, routed to our agent ─────


async def ensure_bridge_trunk(numbers: list[str]) -> None:
    """A LiveKit inbound trunk for Bandwidth hand-offs (digest login, our Bandwidth numbers), on the dispatch rule."""
    from livekit import api

    if not settings.bandwidth_ready or not settings.livekit_ready:
        return
    lk = api.LiveKitAPI(url=settings.livekit_http_url, api_key=settings.livekit_api_key,
                        api_secret=settings.livekit_api_secret)
    try:
        trunks = (await lk.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())).items
        trunk = next((t for t in trunks if t.name == BRIDGE_TRUNK_NAME), None)
        if trunk is None:
            trunk = await lk.sip.create_inbound_trunk(api.CreateSIPInboundTrunkRequest(trunk=api.SIPInboundTrunkInfo(
                name=BRIDGE_TRUNK_NAME, numbers=numbers, auth_username=settings.bandwidth_sip_username,
                auth_password=settings.bandwidth_sip_password, krisp_enabled=True)))
            log.info("bandwidth_bridge_trunk_created", trunk=trunk.sip_trunk_id)
        else:
            missing = [n for n in numbers if n not in trunk.numbers]
            if missing or trunk.auth_username != settings.bandwidth_sip_username:
                await lk.sip.update_inbound_trunk_fields(
                    trunk.sip_trunk_id, numbers=api.ListUpdate(add=missing) if missing else None,
                    auth_username=settings.bandwidth_sip_username, auth_password=settings.bandwidth_sip_password)
        agent_name = settings.livekit_agent_name or "closer"
        rules = (await lk.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())).items
        if any(trunk.sip_trunk_id in r.trunk_ids for r in rules):
            return
        rule = next((r for r in rules if r.trunk_ids and any(a.agent_name == agent_name for a in r.room_config.agents)),
                    None)
        if rule is not None:
            await lk.sip.update_dispatch_rule_fields(rule.sip_dispatch_rule_id,
                                                     trunk_ids=api.ListUpdate(add=[trunk.sip_trunk_id]))
        else:
            meta = json.dumps({"call_type": "inbound"})
            await lk.sip.create_dispatch_rule(api.CreateSIPDispatchRuleRequest(
                rule=api.SIPDispatchRule(dispatch_rule_individual=api.SIPDispatchRuleIndividual(room_prefix="call-")),
                trunk_ids=[trunk.sip_trunk_id], name="Bandwidth bridge",
                room_config=api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=agent_name, metadata=meta)])))
        log.info("bandwidth_bridge_routed", trunk=trunk.sip_trunk_id)
    finally:
        await lk.aclose()
