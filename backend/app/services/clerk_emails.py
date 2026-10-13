"""
Clerk's emails (verification codes, magic links, new sign-in alerts…) sent from our own address.

Clerk sends from the domain its instance is on (blacksync.si), which Gmail flags as a lookalike of
blacksync.ai. With "Delivered by Clerk" turned off for an email, Clerk still writes it and posts it to us
as an `email.created` webhook (signed with Svix); we send it through Resend from EMAIL_FROM.
Emails Clerk still delivers itself are ignored, so nothing goes out twice.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

from app.config import settings

TOLERANCE = 5 * 60  # seconds a signed webhook stays valid (Svix's own default)


class BadSignature(Exception):
    pass


def verify(headers: dict[str, str], body: bytes, secret: str | None = None, now: float | None = None) -> None:
    """Raise BadSignature unless the Svix headers sign this exact body with our secret."""
    secret = secret if secret is not None else settings.clerk_webhook_secret
    msg_id, ts, sigs = headers.get("svix-id"), headers.get("svix-timestamp"), headers.get("svix-signature")
    if not (secret and msg_id and ts and sigs):
        raise BadSignature("missing signature")
    try:
        if abs((now or time.time()) - int(ts)) > TOLERANCE:
            raise BadSignature("stale")
        key = base64.b64decode(secret.removeprefix("whsec_"))
    except (ValueError, TypeError) as exc:
        raise BadSignature("bad header") from exc
    expected = base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    if not any(hmac.compare_digest(expected, part.split(",", 1)[1]) for part in sigs.split() if "," in part):
        raise BadSignature("no match")


def to_send(event: dict) -> tuple[str, str, str] | None:
    """(to, subject, html) for an email.created event we should send, else None."""
    if event.get("type") != "email.created":
        return None
    d = event.get("data") or {}
    if d.get("delivered_by_clerk", True):
        return None  # Clerk is sending this one itself
    to, subject, html = d.get("to_email_address"), d.get("subject"), d.get("body") or d.get("body_plain")
    if not (to and subject and html):
        return None
    return to, subject, html
