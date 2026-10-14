"""
Texting through the account's own provider (Twilio or Telnyx), with the credentials they pasted in.

Errors are worded without the provider's name: customers see them, and the platform hides messages that
mention the services it runs on (see public_errors.py).
"""

from __future__ import annotations

import re

import httpx
import structlog

log = structlog.get_logger(__name__)

PROVIDERS = ("twilio", "telnyx")
_TWILIO = "https://api.twilio.com/2010-04-01"
_TELNYX = "https://api.telnyx.com/v2"
_TIMEOUT = 15.0


class SmsError(RuntimeError):
    pass


def _clean(text: str) -> str:
    """A provider message, minus links (they name the provider) and trailing noise."""
    text = re.sub(r"https?://\S+", "", text or "").strip()
    return re.sub(r"\s+", " ", text)[:240]


async def _twilio(method: str, path: str, sid: str, token: str, data: dict | None = None,
                  params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.request(method, f"{_TWILIO}/Accounts/{sid}{path}", auth=(sid, token), data=data,
                                    params=params)
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code in (401, 403):
        raise SmsError("Those credentials didn't work — check the Account SID and Auth Token.")
    if resp.status_code == 404 and not path:
        raise SmsError("That Account SID wasn't found.")
    if resp.status_code >= 400:
        raise SmsError(_clean(body.get("message") or f"The texting provider answered {resp.status_code}."))
    return body


async def _telnyx(method: str, path: str, key: str, json: dict | None = None, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.request(method, f"{_TELNYX}{path}", headers={"Authorization": f"Bearer {key}"},
                                    json=json, params=params)
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code in (401, 403):
        raise SmsError("That API key didn't work — check it and try again.")
    if resp.status_code >= 400:
        err = next(iter(body.get("errors") or []), {}) or {}
        raise SmsError(_clean(err.get("detail") or err.get("title") or f"The texting provider answered {resp.status_code}."))
    return body


async def verify(provider: str, account_sid: str, secret: str, from_number: str) -> str:
    """Check the credentials and that the sending number belongs to that account. Returns an account label."""
    if provider == "twilio":
        if not re.fullmatch(r"AC[0-9a-fA-F]{32}", account_sid or ""):
            raise SmsError("The Account SID starts with AC and is 34 characters long.")
        acct = await _twilio("GET", ".json", account_sid, secret)
        if acct.get("status") and acct["status"] != "active":
            raise SmsError(f"That account is {acct['status']}.")
        if from_number:
            found = await _twilio("GET", "/IncomingPhoneNumbers.json", account_sid, secret,
                                  params={"PhoneNumber": from_number})
            if not found.get("incoming_phone_numbers"):
                raise SmsError(f"{from_number} isn't a number in that account.")
        return acct.get("friendly_name") or "Connected account"
    if provider == "telnyx":
        await _telnyx("GET", "/balance", secret)
        if from_number:
            found = await _telnyx("GET", "/phone_numbers", secret, params={"filter[phone_number]": from_number})
            if not found.get("data"):
                raise SmsError(f"{from_number} isn't a number in that account.")
        return "Connected account"
    raise SmsError("Pick a texting provider.")


async def send(provider: str, account_sid: str, secret: str, from_number: str, to: str, body: str,
               messaging_profile_id: str = "") -> str:
    """Send one text. Returns the provider's message id."""
    if provider == "twilio":
        msg = await _twilio("POST", "/Messages.json", account_sid, secret,
                            data={"From": from_number, "To": to, "Body": body})
        return msg.get("sid", "")
    if provider == "telnyx":
        payload = {"from": from_number, "to": to, "text": body}
        if messaging_profile_id:
            payload["messaging_profile_id"] = messaging_profile_id
        msg = await _telnyx("POST", "/messages", secret, json=payload)
        return (msg.get("data") or {}).get("id", "")
    raise SmsError("Texting isn't set up for this account.")
