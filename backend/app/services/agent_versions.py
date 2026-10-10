"""Prompt version history for agents: a snapshot each time the prompt is generated, edited or restored."""

from __future__ import annotations

from sqlalchemy import delete, func, select

from app.models.playbook import AgentVersion

MAX_VERSIONS = 50


def _sections(agent) -> dict | None:
    s = (agent.builder or {}).get("sections")
    return dict(s) if isinstance(s, dict) else None


async def snapshot(db, agent, source: str, user_id=None, note: str = "") -> AgentVersion | None:
    """Save the agent's current prompt as a new version (skipped when nothing changed since the last one)."""
    latest = (await db.execute(select(AgentVersion).where(AgentVersion.agent_id == agent.id)
                               .order_by(AgentVersion.version.desc()).limit(1))).scalar_one_or_none()
    sections = _sections(agent)
    if latest and latest.system_prompt == (agent.system_prompt or "") and \
            latest.first_message == (agent.first_message or "") and (latest.sections or None) == sections:
        return None
    v = AgentVersion(org_id=agent.org_id, agent_id=agent.id, version=(latest.version + 1) if latest else 1,
                     source=source, note=note[:500], system_prompt=agent.system_prompt or "",
                     first_message=agent.first_message or "", sections=sections, created_by=user_id)
    db.add(v)
    await db.flush()
    count = (await db.execute(select(func.count()).select_from(AgentVersion)
                              .where(AgentVersion.agent_id == agent.id))).scalar_one()
    if count > MAX_VERSIONS:
        old = (await db.execute(select(AgentVersion.id).where(AgentVersion.agent_id == agent.id)
                                .order_by(AgentVersion.version).limit(count - MAX_VERSIONS))).scalars().all()
        await db.execute(delete(AgentVersion).where(AgentVersion.id.in_(old)))
    return v


async def ensure_baseline(db, agent) -> None:
    """Keep the pre-edit prompt of agents created before version history existed."""
    exists = (await db.execute(select(AgentVersion.id).where(AgentVersion.agent_id == agent.id).limit(1))).first()
    if not exists and (agent.system_prompt or agent.first_message):
        await snapshot(db, agent, "original", note="Before the first saved edit")


def version_to_dict(v: AgentVersion, full: bool = False) -> dict:
    d = {"id": str(v.id), "version": v.version, "source": v.source, "note": v.note,
         "words": len((v.system_prompt or "").split()),
         "created_at": v.created_at.isoformat() if v.created_at else None}
    if full:
        d.update(system_prompt=v.system_prompt, first_message=v.first_message, sections=v.sections)
    return d
