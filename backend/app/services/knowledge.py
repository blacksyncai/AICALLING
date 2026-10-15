"""
Knowledge base helpers — the shape of `BusinessProfile.knowledge`, cleaning,
counting, and the plain-text rendering used when generating agents.

Shape (see docs/agent-builder.md):
    {"sections": [{"key", "title", "items": [{"id", "text", "source_url", "origin", "needs_review"}]}]}
"""

from __future__ import annotations

import copy
import re
import uuid

from sqlalchemy import select

from app.models.builder import BusinessProfile

# Always present, always in this order.
SECTIONS: list[tuple[str, str]] = [
    ("overview", "Company Overview"),
    ("services", "Services and Products"),
    ("locations", "Locations and Coverage"),
    ("team", "Team Members"),
    ("hours", "Business Hours"),
    ("pricing", "Pricing and Policies"),
    ("faqs", "FAQs"),
    ("custom", "Custom Instructions"),
]
SECTION_KEYS = [k for k, _ in SECTIONS]
# Heading the "custom" section gets in an agent's knowledge text (app/agent/runtime.py looks for it).
OWNER_HEADING = "Instructions from the business owner"
SECTION_TITLES = dict(SECTIONS)
ORIGINS = ("website", "manual", "upload")

MAX_ITEM_CHARS = 500
MAX_ITEMS_PER_SECTION = 200  # hard cap for anything stored (extraction is capped lower)


def new_item_id() -> str:
    return f"k_{uuid.uuid4().hex[:10]}"


def empty_knowledge() -> dict:
    return {"sections": [{"key": k, "title": t, "items": []} for k, t in SECTIONS]}


def norm_text(text: str) -> str:
    """Comparison key for a fact: case-, punctuation- and whitespace-insensitive."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def clean_text(value, limit: int = MAX_ITEM_CHARS) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()[:limit].strip()


def clean_item(raw, default_origin: str = "manual") -> dict | None:
    """Coerce one stored/submitted item into the canonical shape (None if unusable)."""
    if not isinstance(raw, dict):
        return None
    text = clean_text(raw.get("text"))
    if not text:
        return None
    item_id = raw.get("id")
    if not isinstance(item_id, str) or not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", item_id):
        item_id = new_item_id()
    origin = raw.get("origin") if raw.get("origin") in ORIGINS else default_origin
    source = raw.get("source_url")
    source = source.strip()[:2000] if isinstance(source, str) and source.strip() else None
    return {"id": item_id, "text": text, "source_url": source, "origin": origin,
            "needs_review": bool(raw.get("needs_review"))}


def normalize_knowledge(knowledge) -> dict:
    """Every known section, in order, with clean items; unknown sections dropped; ids unique."""
    by_key: dict[str, list] = {}
    if isinstance(knowledge, dict) and isinstance(knowledge.get("sections"), list):
        for sec in knowledge["sections"]:
            if isinstance(sec, dict) and sec.get("key") in SECTION_TITLES and isinstance(sec.get("items"), list):
                by_key.setdefault(sec["key"], []).extend(sec["items"])
    out = empty_knowledge()
    seen: set[str] = set()
    for sec in out["sections"]:
        for raw in by_key.get(sec["key"], []):
            item = clean_item(raw)
            if not item:
                continue
            if item["id"] in seen:
                item["id"] = new_item_id()
            seen.add(item["id"])
            sec["items"].append(item)
            if len(sec["items"]) >= MAX_ITEMS_PER_SECTION:
                break
    return out


def section_items(knowledge: dict, key: str) -> list[dict]:
    for sec in knowledge.get("sections", []):
        if sec.get("key") == key:
            return sec["items"]
    return []


def iter_items(knowledge: dict | None):
    """Yield (section_key, item) for every item."""
    for sec in (knowledge or {}).get("sections", []) or []:
        for item in sec.get("items", []) or []:
            yield sec.get("key"), item


def counts(knowledge: dict | None) -> tuple[int, int]:
    """(item_count, review_count)."""
    total = review = 0
    for _, item in iter_items(knowledge):
        total += 1
        review += 1 if item.get("needs_review") else 0
    return total, review


def copy_knowledge(knowledge: dict | None) -> dict:
    return normalize_knowledge(copy.deepcopy(knowledge)) if knowledge else empty_knowledge()


async def get_profile(db, org_id) -> BusinessProfile | None:
    return (await db.execute(select(BusinessProfile).where(BusinessProfile.org_id == org_id))).scalar_one_or_none()


def knowledge_text(profile: BusinessProfile | None) -> str:
    """Plain-text knowledge base, grouped by section, for agent prompts."""
    if profile is None:
        return ""
    lines: list[str] = []
    header = []
    if profile.name:
        header.append(f"Business name: {profile.name}")
    if profile.website:
        header.append(f"Website: {profile.website}")
    if profile.description:
        header.append(f"About: {profile.description}")
    if header:
        lines.extend(header)
    knowledge = normalize_knowledge(profile.knowledge)
    for sec in knowledge["sections"]:
        if not sec["items"]:
            continue
        if lines:
            lines.append("")
        # The owner's own instructions are labelled so the call runtime follows them (the rest is reference).
        lines.append(f"## {OWNER_HEADING if sec['key'] == 'custom' else sec['title']}")
        for item in sec["items"]:
            suffix = " (unconfirmed)" if item.get("needs_review") else ""
            lines.append(f"- {item['text']}{suffix}")
    return "\n".join(lines).strip()
