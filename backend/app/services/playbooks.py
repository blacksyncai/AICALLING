"""
Internal Agent Playbook Library — seeding, retrieval and leak terms.

Playbooks are platform-wide and admin-managed. Customers never read them; the
generator only receives the sanitized pattern card of the 1–3 most relevant
playbooks, and the quality gate rejects any agent containing a playbook's
private terms (unless the customer supplied that term themselves).
"""

from __future__ import annotations

import re

import structlog
from sqlalchemy import select

from app.agent.playbooks import SEED, original
from app.models.playbook import Playbook, PlaybookVersion

log = structlog.get_logger(__name__)

MAX_PATTERNS = 3


async def seed_playbooks(db) -> int:
    """Install the bundled playbooks once (by slug). Admin edits are never overwritten."""
    have = set((await db.execute(select(Playbook.slug))).scalars().all())
    added = 0
    for item in SEED:
        if item["slug"] in have:
            continue
        pb = Playbook(slug=item["slug"], title=item["title"], tags=item["tags"], active=True, current_version=1)
        db.add(pb)
        await db.flush()
        db.add(PlaybookVersion(
            playbook_id=pb.id, version=1, original_text=original(item["slug"]), patterns=item["patterns"],
            private_terms=item["private_terms"], note="Initial import",
        ))
        added += 1
    if added:
        await db.commit()
        log.info("playbooks_seeded", added=added)
    return added


async def current_versions(db, active_only: bool = True) -> list[tuple[Playbook, PlaybookVersion]]:
    q = select(Playbook, PlaybookVersion).join(
        PlaybookVersion,
        (PlaybookVersion.playbook_id == Playbook.id) & (PlaybookVersion.version == Playbook.current_version),
    )
    if active_only:
        q = q.where(Playbook.active.is_(True))
    return list((await db.execute(q.order_by(Playbook.title))).all())


_WORD = re.compile(r"[a-z]+")


def _score(pb: Playbook, industry: str, direction: str, goal_text: str) -> int:
    tags = pb.tags or {}
    score = 0
    if industry and industry in (tags.get("verticals") or []):
        score += 4
    dirs = tags.get("directions") or []
    if direction in dirs or (direction == "both" and dirs):
        score += 2
    words = set(_WORD.findall(goal_text.lower()))
    for goal in tags.get("goals") or []:
        if set(goal.split("_")) & words:
            score += 1
    for style in tags.get("styles") or []:
        if style in words:
            score += 1
    return score


async def relevant_patterns(db, industry: str, direction: str, goal_text: str) -> list[dict]:
    """The pattern cards of the 1–3 most relevant active playbooks (never the originals)."""
    rows = await current_versions(db)
    scored = sorted(((_score(pb, industry, direction, goal_text), pb, v) for pb, v in rows),
                    key=lambda t: (-t[0], t[1].slug))
    picked = [(pb, v) for s, pb, v in scored if s > 0][:MAX_PATTERNS] or [(pb, v) for _, pb, v in scored[:1]]
    return [{"slug": pb.slug, "title": pb.title, "version": v.version, "patterns": v.patterns} for pb, v in picked]


async def private_terms(db) -> list[str]:
    """Every client-specific term from every playbook version (active or not, current or old)."""
    terms: set[str] = set()
    for (lst,) in (await db.execute(select(PlaybookVersion.private_terms))).all():
        for t in lst or []:
            if isinstance(t, str) and t.strip():
                terms.add(t.strip())
    return sorted(terms)
