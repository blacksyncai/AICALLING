"""
Plan entitlements — what an account may use, enforced on the server.

effective limits = the plan's limits (catalog.PLANS) + purchased extra agent slots + active admin overrides.

Accounts without a paid plan (free trial, or a plan that ended) get the `no_plan_entitlements`
platform setting's plan — "teams" by default, so nobody loses access when tiers go live; an admin
can switch it to "solo". House accounts (unlimited credits) have no limits.

Over a limit after a downgrade, nothing is deleted: extra agents stay, but only the oldest
`agents` active ones can place calls, and new activations are refused until the account is back
under its limit.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Invite, Membership, Organization
from app.models.agent import Agent
from app.models.billing import BillingSubscription, EntitlementOverride
from app.services.accounts import InsufficientCredits
from app.services.billing import catalog

LIVE = ("active", "trialing", "past_due")
NUMERIC = ("agents", "seats", "numbers", "crm", "concurrency")
FLAGS = ("workflows", "advanced_workflows", "roles", "team_reporting")
OVERRIDE_KEYS = NUMERIC + FLAGS + ("plan",)
# The welcome guide every new account starts with never counts against the agent limit.
EXEMPT_TEMPLATES = ("welcome_demo",)

_FEATURE_LABELS = {
    "agents": "active agents", "seats": "team members", "numbers": "included phone numbers",
    "crm": "CRM integrations", "concurrency": "calls at once", "workflows": "workflow automations",
    "advanced_workflows": "webhooks and the API", "roles": "member roles and permissions",
    "team_reporting": "team analytics",
}


class PlanLimit(InsufficientCredits):
    """A plan doesn't include something. Carries an upgrade suggestion for the UI."""

    def __init__(self, feature: str, message: str, *, plan: str | None, suggest_plan: str | None = None,
                 addon: str | None = None, limit=None, used=None):
        super().__init__(message)
        self.feature, self.message, self.plan = feature, message, plan
        self.suggest_plan, self.addon, self.limit, self.used = suggest_plan, addon, limit, used

    def detail(self) -> dict:
        suggest = catalog.PLANS.get(self.suggest_plan or "")
        return {
            "code": "plan_limit", "feature": self.feature, "message": self.message, "current_plan": self.plan,
            "limit": self.limit, "used": self.used,
            "suggest": {"plan": self.suggest_plan, "plan_name": suggest["name"] if suggest else None,
                        "self_serve": catalog.self_serve(self.suggest_plan) if suggest else None,
                        "addon": self.addon},
        }

    def http(self) -> HTTPException:
        return HTTPException(status_code=402, detail=self.detail())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


async def active_overrides(db: AsyncSession, org_id: uuid.UUID) -> list[EntitlementOverride]:
    rows = (await db.execute(select(EntitlementOverride).where(
        EntitlementOverride.org_id == org_id, EntitlementOverride.revoked_at.is_(None))
        .order_by(EntitlementOverride.created_at))).scalars().all()
    now = _now()
    return [r for r in rows if r.expires_at is None or _aware(r.expires_at) > now]


async def _no_plan_key(db: AsyncSession) -> str:
    from app.services.billing import settings_store

    key = await settings_store.get(db, "no_plan_entitlements")
    return key if key in catalog.PLANS else "teams"


async def effective(db: AsyncSession, org: Organization) -> dict:
    """{plan, plan_name, source, unlimited, limits{…}, agent_slots, overrides[…]}."""
    row = await db.get(BillingSubscription, org.id)
    subscribed = bool(row and row.status in LIVE and row.plan_key in catalog.PLANS)
    plan_key = row.plan_key if subscribed else None
    source = "subscription" if subscribed else "no_plan"
    overrides = await active_overrides(db, org.id)
    plan_override = next((o.value for o in reversed(overrides) if o.key == "plan" and o.value in catalog.PLANS), None)
    if plan_override:
        plan_key, source = plan_override, "override"
    limits_key = plan_key or await _no_plan_key(db)
    limits = catalog.plan_limits(limits_key) or {}
    slots = int((row.agent_slots or 0) if subscribed else 0)
    if limits.get("agents") is not None:
        limits["agents"] += slots
    for o in overrides:
        if o.key in NUMERIC:
            limits[o.key] = None if o.value is None else int(o.value)
        elif o.key in FLAGS:
            limits[o.key] = bool(o.value)
    unlimited = bool(org.unlimited_credits)
    if unlimited:
        limits = {**{k: None for k in NUMERIC}, **{k: True for k in FLAGS}}
    shown = catalog.PLANS.get(plan_key or "")
    return {
        "plan": plan_key, "plan_name": shown["name"] if shown else None, "limits_plan": limits_key,
        "source": source, "unlimited": unlimited, "limits": limits, "agent_slots": slots,
        "overrides": [override_to_dict(o) for o in overrides],
    }


def override_to_dict(o: EntitlementOverride) -> dict:
    iso = lambda d: _aware(d).isoformat() if d else None  # noqa: E731
    return {"id": str(o.id), "key": o.key, "value": o.value, "reason": o.reason, "expires_at": iso(o.expires_at),
            "created_at": iso(o.created_at), "created_by": str(o.created_by) if o.created_by else None,
            "revoked_at": iso(o.revoked_at)}


def _next_plan(current: str | None, feature: str, needed: int | None = None) -> str | None:
    """The cheapest plan above `current` that includes `feature` (or allows `needed` of it)."""
    rank = catalog.PLAN_RANK.get(current or "", 0)
    for key in catalog.PLAN_ORDER:
        if catalog.PLAN_RANK[key] <= rank:
            continue
        lim = catalog.plan_limits(key) or {}
        val = lim.get(feature)
        if feature in FLAGS and val:
            return key
        if feature in NUMERIC and (val is None or (needed is not None and val >= needed) or (needed is None and val > 0)):
            return key
    return None


# ── Usage counts ──────────────────────────────────────────────────────────────


def _counted_agents():
    return Agent.template.is_(None) | Agent.template.notin_(EXEMPT_TEMPLATES)


async def active_agent_ids(db: AsyncSession, org_id: uuid.UUID) -> list[uuid.UUID]:
    """Active agents that count toward the limit, oldest first."""
    return list((await db.execute(select(Agent.id).where(
        Agent.org_id == org_id, Agent.status == "active", _counted_agents()).order_by(Agent.created_at, Agent.id)
    )).scalars().all())


async def seat_usage(db: AsyncSession, org_id: uuid.UUID) -> int:
    members = (await db.execute(select(func.count()).select_from(Membership).where(Membership.org_id == org_id))).scalar_one()
    pending = (await db.execute(select(func.count()).select_from(Invite).where(
        Invite.org_id == org_id, Invite.accepted_at.is_(None), Invite.expires_at > _now()))).scalar_one()
    return int(members) + int(pending)


async def crm_usage(db: AsyncSession, org_id: uuid.UUID, exclude: str | None = None) -> int:
    from app.models.crm import CrmConnection
    from app.services.crm.providers import PROVIDERS

    keys = [r for r in (await db.execute(select(CrmConnection.provider).where(CrmConnection.org_id == org_id))).scalars()]
    return len([k for k in keys if k != exclude and getattr(PROVIDERS.get(k), "category", "crm") == "crm"])


async def usage(db: AsyncSession, org: Organization) -> dict:
    from app.services.telephony import active_numbers

    return {"agents": len(await active_agent_ids(db, org.id)), "seats": await seat_usage(db, org.id),
            "numbers": len([n for n in await active_numbers(db, org.id) if not n.stripe_subscription_id]),
            "crm": await crm_usage(db, org.id)}


async def summary(db: AsyncSession, org: Organization) -> dict:
    eff = await effective(db, org)
    used = await usage(db, org)
    over = [k for k, v in used.items() if k != "numbers" and eff["limits"].get(k) is not None and v > eff["limits"][k]]
    return {**eff, "usage": used, "over_limit": over}


# ── Checks (raise PlanLimit) ──────────────────────────────────────────────────


async def require(db: AsyncSession, org: Organization, feature: str, message: str | None = None) -> None:
    eff = await effective(db, org)
    if eff["limits"].get(feature):
        return
    target = _next_plan(eff["limits_plan"], feature)
    name = catalog.PLANS[target]["name"] if target else "a higher plan"
    raise PlanLimit(feature, message or f"{_FEATURE_LABELS[feature].capitalize()} are included from the {name} plan.",
                    plan=eff["plan"], suggest_plan=target)


async def check_agent_activation(db: AsyncSession, org: Organization, agent_id: uuid.UUID | None = None) -> None:
    """Before a new agent is created active, or a paused one is switched on."""
    eff = await effective(db, org)
    limit = eff["limits"].get("agents")
    if limit is None:
        return
    ids = [i for i in await active_agent_ids(db, org.id) if i != agent_id]
    if len(ids) < limit:
        return
    target = _next_plan(eff["limits_plan"], "agents", len(ids) + 1)
    plan_name = eff["plan_name"] or "your"
    raise PlanLimit("agents", f"The {plan_name} plan includes {limit} active agent{'s' if limit != 1 else ''}. "
                    "Add an extra agent slot, pause another agent, or upgrade.",
                    plan=eff["plan"], suggest_plan=target, addon=catalog.AGENT_ADDON["key"], limit=limit, used=len(ids))


async def check_agent_can_call(db: AsyncSession, org: Organization, agent: Agent) -> None:
    """Phone calls: only active agents within the limit (oldest first) may dial or answer."""
    if agent.template in EXEMPT_TEMPLATES:
        return
    eff = await effective(db, org)
    limit = eff["limits"].get("agents")
    if limit is None:
        return
    ids = await active_agent_ids(db, org.id)
    if agent.id in ids[:limit]:
        return
    if agent.status != "active" and len(ids) < limit:
        return  # a paused agent while there's room is still within the plan
    raise PlanLimit("agents", f"This account has more active agents than its plan allows ({limit}). "
                    "Pause the agents you don't need, add an extra agent slot, or upgrade.",
                    plan=eff["plan"], suggest_plan=_next_plan(eff["limits_plan"], "agents", len(ids)),
                    addon=catalog.AGENT_ADDON["key"], limit=limit, used=len(ids))


async def check_seat_role(db: AsyncSession, org: Organization, role: str) -> None:
    """Admins (people who manage the team, billing and settings) need a plan with roles."""
    if role != "admin":
        return
    eff = await effective(db, org)
    if not eff["limits"].get("roles"):
        target = _next_plan(eff["limits_plan"], "roles")
        raise PlanLimit("roles", "Admin roles and member permissions are included from the "
                        f"{catalog.PLANS[target]['name'] if target else 'Teams'} plan. Invite them as a member instead.",
                        plan=eff["plan"], suggest_plan=target)


async def check_seat(db: AsyncSession, org: Organization, role: str = "member") -> None:
    await check_seat_role(db, org, role)
    eff = await effective(db, org)
    limit = eff["limits"].get("seats")
    if limit is None:
        return
    used = await seat_usage(db, org.id)
    if used < limit:
        return
    target = _next_plan(eff["limits_plan"], "seats", used + 1)
    msg = ("The Solo plan is for one person — upgrade to invite your team." if limit <= 1 else
           f"Your plan includes {limit} team members (pending invites count). Upgrade to add more.")
    raise PlanLimit("seats", msg, plan=eff["plan"], suggest_plan=target, limit=limit, used=used)


async def check_crm(db: AsyncSession, org: Organization, provider: str) -> None:
    from app.services.crm.providers import PROVIDERS

    category = getattr(PROVIDERS.get(provider), "category", "crm")
    if category != "crm":
        await require(db, org, "workflows", "Slack and Google Sheets automations are included from the Growth plan.")
        return
    eff = await effective(db, org)
    limit = eff["limits"].get("crm")
    if limit is None:
        return
    used = await crm_usage(db, org.id, exclude=provider)  # reconnecting the same CRM is fine
    if used < limit:
        return
    target = _next_plan(eff["limits_plan"], "crm", used + 1)
    msg = ("CRM integrations are included from the Growth plan." if limit == 0 else
           f"Your plan includes {limit} CRM integration{'s' if limit != 1 else ''}. "
           f"Upgrade to {catalog.PLANS[target]['name'] if target else 'Teams'} to connect more.")
    raise PlanLimit("crm", msg, plan=eff["plan"], suggest_plan=target, limit=limit, used=used)


async def concurrency_cap(db: AsyncSession, org: Organization) -> int | None:
    return (await effective(db, org))["limits"].get("concurrency")


async def check_concurrency(db: AsyncSession, org: Organization, wanted: int | None) -> None:
    if not wanted:
        return
    eff = await effective(db, org)
    cap = eff["limits"].get("concurrency")
    if cap is None or wanted <= cap:
        return
    target = _next_plan(eff["limits_plan"], "concurrency", wanted)
    raise PlanLimit("concurrency", f"Your plan runs up to {cap} calls at once per campaign.",
                    plan=eff["plan"], suggest_plan=target, limit=cap, used=wanted)


async def included_numbers(db: AsyncSession, org: Organization) -> int:
    lim = (await effective(db, org))["limits"].get("numbers")
    return 1000 if lim is None else int(lim)
