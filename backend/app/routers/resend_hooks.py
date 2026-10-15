"""
Resend webhook: delivered / opened / clicked / bounced / complained events for the emails we send.

Resend signs webhooks with Svix: HMAC-SHA256 of "{svix-id}.{svix-timestamp}.{body}" with the endpoint's signing
secret (whsec_… — the part after the prefix is base64). Unsigned or stale requests are refused.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.email_message import EmailMessage

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

TOLERANCE_S = 5 * 60
# How far along an email got; a later event never moves it backwards. Bounces and complaints always win.
_RANK = {"sent": 0, "delayed": 1, "delivered": 2, "opened": 3, "clicked": 4}


def webhook_secret() -> str:
    from app.services import secret_store

    return (secret_store.get("resend_webhook_secret") or settings.resend_webhook_secret or "").strip()


def valid_signature(secret: str, msg_id: str, timestamp: str, body: bytes, signature_header: str) -> bool:
    if not (secret and msg_id and timestamp and signature_header):
        return False
    try:
        if abs(time.time() - int(timestamp)) > TOLERANCE_S:
            return False
        key = base64.b64decode(secret.split("_", 1)[1] if secret.startswith("whsec_") else secret)
    except (ValueError, IndexError):
        return False
    expected = base64.b64encode(hmac.new(key, f"{msg_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()).decode()
    return any(hmac.compare_digest(expected, part.split(",", 1)[1])
               for part in signature_header.split() if part.startswith("v1,"))


def _when(event: dict) -> datetime:
    raw = event.get("created_at") or ""
    try:
        d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def apply_event(m: EmailMessage, kind: str, at: datetime, data: dict) -> None:
    if kind == "delivered":
        m.delivered_at = m.delivered_at or at
    elif kind == "opened":
        m.opened_at = m.opened_at or at
        m.open_count += 1
    elif kind == "clicked":
        m.clicked_at = m.clicked_at or at
        m.click_count += 1
        m.last_link = str(((data.get("click") or {}).get("link")) or "")[:500] or m.last_link
    elif kind == "bounced":
        m.bounced_at = m.bounced_at or at
    elif kind == "complained":
        m.complained_at = m.complained_at or at
    if kind in ("bounced", "complained"):
        m.status = kind
    elif m.status not in ("bounced", "complained") and _RANK.get(kind, -1) > _RANK.get(m.status, -1):
        m.status = kind


@router.post("/resend")
async def resend_webhook(request: Request):
    body = await request.body()
    secret = webhook_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="Email tracking isn't set up yet.")
    h = request.headers
    if not valid_signature(secret, h.get("svix-id", ""), h.get("svix-timestamp", ""), body, h.get("svix-signature", "")):
        raise HTTPException(status_code=401, detail="Invalid signature")
    try:
        event = json.loads(body or b"{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    etype = str(event.get("type") or "")
    kind = {"email.delivered": "delivered", "email.opened": "opened", "email.clicked": "clicked",
            "email.bounced": "bounced", "email.complained": "complained",
            "email.delivery_delayed": "delayed", "email.sent": "sent"}.get(etype)
    data = event.get("data") or {}
    email_id = str(data.get("email_id") or "")
    if not kind or not email_id:
        return {"ok": True, "ignored": etype or "unknown"}
    async with AsyncSessionLocal() as db:
        m = (await db.execute(select(EmailMessage).where(EmailMessage.resend_id == email_id))).scalar_one_or_none()
        if m is None:  # sent before tracking existed, or by another sender on the account
            to = data.get("to") or []
            m = EmailMessage(resend_id=email_id[:64], to_email=str((to[0] if isinstance(to, list) and to else to) or "").lower()[:320],
                             subject=str(data.get("subject") or "")[:300], kind="other", sent_at=_when(event),
                             open_count=0, click_count=0, status="sent")
            db.add(m)
        apply_event(m, kind, _when(event), data)
        await db.commit()
    log.info("resend_event", type=etype, email_id=email_id)
    return {"ok": True}
