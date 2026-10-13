"""
Free-trial onboarding — a signed-in login with no account answers a few
questions and gets its own workspace: trial credits, the welcome demo agent
(briefed on their answers), their industry saved for Build with AI, and Lead
Finder only where it fits (real estate and home services).
"""

from __future__ import annotations

from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent import catalog
from app.models.account import Membership, User
from app.models.agent import Agent
from app.models.builder import BusinessProfile
from app.services.accounts import create_organization
from app.services.auth import DbDep, get_current_user
from app.services.billing import settings_store

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])
UserDep = Annotated[User, Depends(get_current_user)]

# Industries where Lead Finder (property-owner lookups) is useful.
LEAD_FINDER_INDUSTRIES = {"real_estate", "home_services"}
# Extra words under each industry on the onboarding screen (labels come from the agent catalog).
HINTS = {
    "real_estate": "Agents, teams and brokerages",
    "home_services": "HVAC, roofing, plumbing, solar and other trades",
    "logistics": "Freight, trucking and dispatch",
    "financial_services": "Equipment finance, lending and advisory",
    "mortgage": "Loan officers and brokers",
    "insurance": "Agencies and carriers",
    "recruiting": "Staffing and recruiting firms",
    "automotive": "Dealers and service centers",
    "healthcare": "Clinics, dental and wellness",
    "professional_services": "Agencies, consultants and law firms",
    "other": "Tell us what you do",
}
TEAM_SIZES = ("just_me", "2_5", "6_20", "21_plus")


@router.get("/options")
async def options(_: UserDep, db: DbDep):
    c = catalog.catalog()
    return {
        "industries": [{**i, "hint": HINTS.get(i["key"], "")} for i in c["industries"]],
        "specialties": c.get("specialties", {}),
        "lead_finder_industries": sorted(LEAD_FINDER_INDUSTRIES),
        "trial_credits": int(await settings_store.get(db, "trial_credits") or 0),
    }


class StartBody(BaseModel):
    company: str = Field(min_length=1, max_length=120)
    industry: str
    goals: list[str] = Field(default_factory=list, max_length=8)
    other_goal: str = Field(default="", max_length=300)
    team_size: Literal["just_me", "2_5", "6_20", "21_plus"] | None = None
    website: str = Field(default="", max_length=300)
    timezone: str = Field(default="", max_length=64)


def _brief(industry_label: str, goal_labels: list[str], other: str, company: str) -> str:
    wants = ", ".join(goal_labels) or other or "not sure yet"
    return (f"\n\nABOUT THIS CALLER (from their signup): they work at {company} in {industry_label}. "
            f"They said they want AI calling for: {wants}. Use this to make your tip specific, "
            "but still ask them in your own words.")


@router.post("/start", status_code=201)
async def start(body: StartBody, user: UserDep, db: DbDep):
    """Create the trial workspace for a login that isn't in any account yet."""
    from app.routers.auth import session_payload
    from app.services.reporting import is_valid_timezone

    if (await db.execute(select(Membership.id).where(Membership.user_id == user.id).limit(1))).first():
        raise HTTPException(status_code=409, detail="This login already has an account.")
    label = catalog.industry_label(body.industry)
    if not label:
        raise HTTPException(status_code=422, detail="Choose one of the listed industries.")
    specs = {s["key"]: s for s in catalog.specialties_for(body.industry)}
    goals = [g for g in dict.fromkeys(body.goals) if g in specs]

    credits = int(await settings_store.get(db, "trial_credits") or 0)
    org = await create_organization(db, body.company, created_by=user.id)
    if credits:
        from app.services.billing.credits import add_lot

        await add_lot(db, org, credits, source="grant", kind="grant", note=f"Free trial — {credits} calling credits",
                      created_by=user.id)
    org.industry = body.industry
    org.lead_finder_enabled = body.industry in LEAD_FINDER_INDUSTRIES
    org.onboarding = {"goals": goals, "other_goal": body.other_goal.strip(), "team_size": body.team_size,
                      "trial_credits": credits}
    if body.timezone and is_valid_timezone(body.timezone):
        org.timezone = body.timezone
    db.add(Membership(user_id=user.id, org_id=org.id, role="owner"))
    db.add(BusinessProfile(org_id=org.id, name=body.company.strip(), industry=body.industry,
                           website=body.website.strip()))
    user.active_org_id = org.id
    await db.flush()

    # Brief the welcome demo agent on what they told us.
    demo = (await db.execute(select(Agent).where(Agent.org_id == org.id, Agent.template == "welcome_demo"))).scalar_one_or_none()
    if demo:
        demo.system_prompt += _brief(label, [specs[g]["label"] for g in goals], body.other_goal.strip(), body.company.strip())
    await db.commit()
    log.info("trial_started", org_id=str(org.id), industry=body.industry, goals=goals, credits=credits)
    from app.services.onboarding_emails import send_welcome_soon

    send_welcome_soon(user.id, org.id)
    return await session_payload(db, user)
