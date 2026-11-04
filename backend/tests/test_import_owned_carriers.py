"""Assigning an owned number: a carrier that fails (e.g. Twilio rejecting its credentials) must not block another."""

import asyncio

import pytest

from app.services import plivo, telephony


class Reached(Exception):
    pass


def test_plivo_number_assigns_while_twilio_fails(monkeypatch):
    async def twilio_down(*a, **kw):
        raise telephony.TelephonyError("Twilio rejected the credentials (account inactive)")

    async def plivo_numbers():
        return [{"sid": "plivo:+14155550999", "number": "+14155550999", "friendly": "Plivo", "trunk_sid": "",
                 "carrier": "plivo"}]

    async def claimed(db, org_id, number):
        raise Reached(number)

    monkeypatch.setattr(telephony.settings, "twilio_account_sid", "AC123", raising=False)
    monkeypatch.setattr(type(telephony.settings), "twilio_ready", property(lambda self: True), raising=False)
    monkeypatch.setattr(telephony, "_request", twilio_down)
    monkeypatch.setattr(plivo, "ready", lambda: True)
    monkeypatch.setattr(plivo, "list_numbers", plivo_numbers)
    monkeypatch.setattr(telephony, "_claim_row", claimed)
    with pytest.raises(Reached):
        asyncio.run(telephony.import_owned(None, None, "+14155550999"))
