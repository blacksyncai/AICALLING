"""One Cal.com calendar for the whole account: saved from any agent's editor, copied to every agent, and
given to agents created later so the API key and event type aren't typed in again."""
import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Organization
from app.models.agent import Agent


async def apply_default(db: AsyncSession, agent: Agent) -> None:
    """Give a new agent the account's calendar (only when it has none of its own)."""
    if agent.calcom_event_type_id or agent.calcom_api_key_enc:
        return
    org = await db.get(Organization, agent.org_id)
    default = (org.calendar_default if org else None) or {}
    if not default.get("event_type_id"):
        return
    agent.calcom_event_type_id = default["event_type_id"]
    agent.calcom_api_key_enc = default.get("api_key_enc")
    agent.calendar_timezone = agent.calendar_timezone or default.get("timezone") or None


async def use_everywhere(db: AsyncSession, org_id: uuid.UUID, source: Agent) -> int:
    """Make this agent's calendar the account default and copy it to every agent. Returns agents updated."""
    org = await db.get(Organization, org_id)
    org.calendar_default = {"event_type_id": source.calcom_event_type_id or "",
                            "api_key_enc": source.calcom_api_key_enc, "timezone": source.calendar_timezone or ""}
    res = await db.execute(update(Agent).where(Agent.org_id == org_id, Agent.id != source.id).values(
        calcom_event_type_id=source.calcom_event_type_id or "", calcom_api_key_enc=source.calcom_api_key_enc,
        calendar_timezone=source.calendar_timezone))
    return int(res.rowcount or 0)
