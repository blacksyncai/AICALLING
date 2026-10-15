"""
Account services — startup bootstrap, creating organizations, the credit
ledger, and outgoing webhook delivery.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timezone

import httpx
import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.account import CreditTransaction, Membership, Organization, User, WebhookEndpoint
from app.models.agent import Agent
from app.models.call_log import CallLog
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.services.auth import generate_password, hash_password, normalize_email

log = structlog.get_logger(__name__)


# ── Bootstrap ─────────────────────────────────────────────────────────────────


async def bootstrap(db: AsyncSession) -> None:
    """
    First boot of a multi-account database: create the platform super-admin
    (AUTH_EMAIL / AUTH_PASSWORD) and a house organization, and move any data
    created before accounts existed into it.
    """
    users = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    if users == 0:
        email = normalize_email(settings.auth_email) or "admin@example.com"
        password = settings.auth_password or generate_password()
        has_agents = (await db.execute(select(func.count()).select_from(Agent))).scalar_one() > 0
        if has_agents:  # upgrading: existing agents move into the house account below
            org = Organization(id=uuid.uuid4(), name=settings.house_org_name or "BlackSync")
            db.add(org)
            await db.flush()
        else:
            org = await create_organization(db, settings.house_org_name or "BlackSync")
        org.unlimited_credits = True
        admin = User(
            id=uuid.uuid4(), email=email, first_name="Admin", password_hash=hash_password(password),
            is_superadmin=True, active_org_id=org.id,
        )
        db.add(admin)
        await db.flush()
        db.add(Membership(user_id=admin.id, org_id=org.id, role="owner"))
        await db.commit()
        if settings.auth_password:
            log.info("bootstrap_admin_created", email=email)
        else:
            # No AUTH_PASSWORD configured — print the generated one once so it can be used.
            log.warning("bootstrap_admin_created_with_generated_password", email=email, password=password)

    # Rows from before accounts existed belong to the oldest organization.
    house = (await db.execute(select(Organization).order_by(Organization.created_at).limit(1))).scalar_one_or_none()
    if house:
        for model in (Agent, Campaign, Lead, CallLog):
            await db.execute(update(model).where(model.org_id.is_(None)).values(org_id=house.id))
        await db.commit()


async def create_organization(db: AsyncSession, name: str, *, credits: int = 0,
                              created_by: uuid.UUID | None = None) -> Organization:
    """New sub-account with a ready-to-test agent."""
    from app.routers.agents import new_agent_from_template

    org = Organization(id=uuid.uuid4(), name=name.strip() or "New account")
    db.add(org)
    await db.flush()
    agent = new_agent_from_template("welcome_demo")  # Synchro, the BlackSync welcome guide
    agent.org_id = org.id
    db.add(agent)
    if credits:
        from app.services.billing.credits import add_lot

        await add_lot(db, org, credits, source="grant", kind="grant", note="Starting credits", created_by=created_by)
    return org


# ── Credits ───────────────────────────────────────────────────────────────────


class InsufficientCredits(Exception):
    pass


def has_credits(org: Organization) -> bool:
    return org.unlimited_credits or (org.credits_balance or 0) > 0


def ensure_can_call(org: Organization) -> None:
    if org.status == "suspended":
        raise InsufficientCredits("This account is suspended — contact support to re-enable calling.")
    if not has_credits(org):
        raise InsufficientCredits("You're out of calling credits. Contact your admin to add more.")


async def adjust_credits(db: AsyncSession, org: Organization, amount: int, *, kind: str, note: str = "",
                         call_id: uuid.UUID | None = None, created_by: uuid.UUID | None = None) -> CreditTransaction:
    """Atomically change the balance and record it in the ledger (caller commits)."""
    await db.execute(
        update(Organization).where(Organization.id == org.id)
        .values(credits_balance=Organization.credits_balance + amount)
    )
    await db.refresh(org, ["credits_balance"])
    tx = CreditTransaction(
        org_id=org.id, amount=amount, balance_after=org.credits_balance, kind=kind, note=note,
        amount_milli=amount * 1000,
        balance_after_milli=max(0, (org.credits_balance or 0) * 1000 - (org.credit_carry_milli or 0)),
        call_id=call_id, created_by=created_by,
    )
    db.add(tx)
    return tx


async def charge_call(db: AsyncSession, call: CallLog) -> None:
    """Bill a finished phone call once — per second at the agent's credit rate (see billing/credits.py)."""
    from app.services.billing.credits import charge_call as _charge

    await _charge(db, call)
    if call.org_id and call.credits_charged:
        from app.services.billing.recharge import schedule_check

        schedule_check(call.org_id)


# ── Outgoing webhooks ─────────────────────────────────────────────────────────

_BACKGROUND: set = set()


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def new_webhook_secret() -> str:
    return "whsec_" + secrets.token_hex(16)


def is_public_url(url: str) -> bool:
    """Webhooks may only target the public internet — never this server or a private network."""
    import ipaddress
    import socket
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        for info in socket.getaddrinfo(parsed.hostname, parsed.port or 443, proto=socket.IPPROTO_TCP):
            ip = ipaddress.ip_address(info[4][0])
            if not ip.is_global:
                return False
        return True
    except Exception:
        return False


async def deliver(endpoint_id: uuid.UUID, event: str, data: dict) -> tuple[int | None, str | None]:
    """POST one event to one endpoint and record the result."""
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        ep = await db.get(WebhookEndpoint, endpoint_id)
        if not ep:
            return None, "Endpoint not found"
        body = json.dumps({
            "id": f"evt_{uuid.uuid4().hex}", "event": event,
            "created_at": datetime.now(timezone.utc).isoformat(), "data": data,
        }, default=str).encode()
        status, error = None, None
        if not await asyncio.to_thread(is_public_url, ep.url):
            error = "URL must point to a public internet address"
        else:
            try:
                # No redirects: a public URL must not bounce the request somewhere internal.
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
                    resp = await client.post(ep.url, content=body, headers={
                        "Content-Type": "application/json",
                        "User-Agent": "BlackSync-Webhooks/1.0",
                        "X-BlackSync-Event": event,
                        "X-BlackSync-Signature": sign(ep.secret, body),
                    })
                status = resp.status_code
                if status >= 400:
                    error = resp.text[:300] or f"HTTP {status}"
            except Exception as exc:
                error = str(exc)[:300] or exc.__class__.__name__
        ep.last_status, ep.last_error, ep.last_sent_at = status, error, datetime.now(timezone.utc)
        await db.commit()
        log.info("webhook_delivered", endpoint=str(endpoint_id), webhook_event=event, status=status, error=error)
        return status, error


async def emit_event(org_id: uuid.UUID | None, event: str, data: dict) -> None:
    """Fan an event out to the org's active endpoints subscribed to it (fire-and-forget)."""
    if not org_id:
        return
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        endpoints = (await db.execute(
            select(WebhookEndpoint).where(WebhookEndpoint.org_id == org_id, WebhookEndpoint.active.is_(True))
        )).scalars().all()
    for ep in endpoints:
        if ep.events and event not in ep.events:
            continue
        task = asyncio.create_task(deliver(ep.id, event, data))
        _BACKGROUND.add(task)
        task.add_done_callback(_BACKGROUND.discard)
