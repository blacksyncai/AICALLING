"""
Integrations router — the account's API keys (for the public /api/v1 API,
Zapier, Make, n8n…) and outgoing webhooks.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.models.account import WEBHOOK_EVENTS, ApiKey, WebhookEndpoint
from app.services.accounts import deliver, new_webhook_secret
from app.services.auth import DbDep, ManagerDep, generate_api_key, sha256

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

SAMPLE_EVENT = {
    "call_id": "00000000-0000-0000-0000-000000000000",
    "contact": {"name": "Jamie Rivera", "phone": "+14155550123", "company": "Globex"},
    "agent_name": "Outbound Sales SDR",
    "outcome": "meeting_booked",
    "summary": "Test event from BlackSync — your webhook is connected.",
    "duration_seconds": 142,
}


class ApiKeyCreate(BaseModel):
    name: str = "API key"


class WebhookIn(BaseModel):
    name: str = ""
    url: str
    events: list[str] = list(WEBHOOK_EVENTS)
    active: bool = True


class WebhookPatch(BaseModel):
    name: str | None = None
    url: str | None = None
    events: list[str] | None = None
    active: bool | None = None


def _iso(d: datetime | None) -> str | None:
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()


def _key_to_dict(k: ApiKey) -> dict:
    return {"id": str(k.id), "name": k.name, "prefix": k.prefix, "created_at": _iso(k.created_at),
            "last_used_at": _iso(k.last_used_at)}


def _hook_to_dict(w: WebhookEndpoint) -> dict:
    return {"id": str(w.id), "name": w.name, "url": w.url, "events": w.events or list(WEBHOOK_EVENTS),
            "secret": w.secret, "active": w.active, "last_status": w.last_status, "last_error": w.last_error,
            "last_sent_at": _iso(w.last_sent_at), "created_at": _iso(w.created_at)}


def _validate_hook(url: str | None, events: list[str] | None) -> None:
    if url is not None and not url.strip().lower().startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="Webhook URL must start with https://")
    if events is not None:
        bad = [e for e in events if e not in WEBHOOK_EVENTS]
        if bad or not events:
            raise HTTPException(status_code=400, detail=f"Events must be from: {', '.join(WEBHOOK_EVENTS)}")


@router.get("")
@router.get("/")
async def overview(ctx: ManagerDep, db: DbDep):
    keys = (await db.execute(select(ApiKey).where(ApiKey.org_id == ctx.org.id, ApiKey.revoked_at.is_(None))
                             .order_by(ApiKey.created_at.desc()))).scalars().all()
    hooks = (await db.execute(select(WebhookEndpoint).where(WebhookEndpoint.org_id == ctx.org.id)
                              .order_by(WebhookEndpoint.created_at.desc()))).scalars().all()
    return {"api_keys": [_key_to_dict(k) for k in keys], "webhooks": [_hook_to_dict(w) for w in hooks],
            "events": list(WEBHOOK_EVENTS)}


@router.post("/api-keys", status_code=201)
async def create_api_key(body: ApiKeyCreate, ctx: ManagerDep, db: DbDep):
    """The full key is returned only here — store it somewhere safe."""
    raw = generate_api_key()
    key = ApiKey(id=uuid.uuid4(), org_id=ctx.org.id, name=body.name.strip()[:100] or "API key",
                 prefix=raw[:10], key_hash=sha256(raw), created_by=ctx.user.id)
    db.add(key)
    await db.commit()
    return {**_key_to_dict(key), "key": raw}


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(key_id: uuid.UUID, ctx: ManagerDep, db: DbDep):
    key = await db.get(ApiKey, key_id)
    if not key or key.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="API key not found")
    key.revoked_at = datetime.now(timezone.utc)
    await db.commit()


@router.post("/webhooks", status_code=201)
async def create_webhook(body: WebhookIn, ctx: ManagerDep, db: DbDep):
    _validate_hook(body.url, body.events)
    hook = WebhookEndpoint(id=uuid.uuid4(), org_id=ctx.org.id, name=body.name.strip()[:100], url=body.url.strip(),
                           events=body.events, secret=new_webhook_secret(), active=body.active)
    db.add(hook)
    await db.commit()
    return _hook_to_dict(hook)


async def _hook(db, ctx, hook_id: uuid.UUID) -> WebhookEndpoint:
    hook = await db.get(WebhookEndpoint, hook_id)
    if not hook or hook.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return hook


@router.patch("/webhooks/{hook_id}")
async def update_webhook(hook_id: uuid.UUID, body: WebhookPatch, ctx: ManagerDep, db: DbDep):
    hook = await _hook(db, ctx, hook_id)
    _validate_hook(body.url, body.events)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(hook, key, value.strip() if isinstance(value, str) else value)
    await db.commit()
    return _hook_to_dict(hook)


@router.delete("/webhooks/{hook_id}", status_code=204)
async def delete_webhook(hook_id: uuid.UUID, ctx: ManagerDep, db: DbDep):
    hook = await _hook(db, ctx, hook_id)
    await db.delete(hook)
    await db.commit()


@router.post("/webhooks/{hook_id}/test")
async def test_webhook(hook_id: uuid.UUID, ctx: ManagerDep, db: DbDep):
    hook = await _hook(db, ctx, hook_id)
    event = (hook.events or list(WEBHOOK_EVENTS))[0]
    status, error = await deliver(hook.id, event, {**SAMPLE_EVENT, "test": True})
    return {"ok": status is not None and status < 400, "status": status, "error": error, "event": event}
