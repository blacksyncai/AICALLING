"""TEMPORARY read-only check (remove after it has run): Todd's voicemail calls where the agent kept talking.
Logs counts plus a few transcripts (turns truncated) so the miss can be diagnosed."""
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import or_, select

log = structlog.get_logger(__name__)


async def run():
    from app.agent.runtime import is_voicemail_text, voicemail_greeting_match
    from app.database import AsyncSessionLocal
    from app.models.account import Membership, Organization, User
    from app.models.agent import Agent
    from app.models.call_log import CallLog

    try:
        async with AsyncSessionLocal() as db:
            users = (await db.execute(select(User).where(or_(User.first_name.ilike("todd%"), User.email.ilike("todd%"))))).scalars().all()
            org_ids = {m.org_id for m in (await db.execute(select(Membership).where(
                Membership.user_id.in_([u.id for u in users] or [None])))).scalars()}
            org_ids |= set((await db.execute(select(Organization.id).where(Organization.name.ilike("%todd%")))).scalars())
            orgs = (await db.execute(select(Organization).where(Organization.id.in_(org_ids or [None])))).scalars().all()
            since = datetime.now(timezone.utc) - timedelta(days=7)
            for org in orgs:
                calls = (await db.execute(select(CallLog).where(CallLog.org_id == org.id, CallLog.started_at >= since,
                         CallLog.call_type == "outbound").order_by(CallLog.started_at.desc()))).scalars().all()
                agents = {a.id: a for a in (await db.execute(select(Agent).where(Agent.org_id == org.id))).scalars()}
                talked, samples, outcomes = 0, [], {}
                for c in calls:
                    outcomes[c.outcome or "none"] = outcomes.get(c.outcome or "none", 0) + 1
                    turns = [t for t in c.transcript or [] if isinstance(t, dict)]
                    first_vm = next((i for i, t in enumerate(turns) if t.get("role") == "user"
                                     and (voicemail_greeting_match(str(t.get("text") or "")) or is_voicemail_text(str(t.get("text") or "")))), None)
                    if first_vm is None:
                        continue
                    after = [t for t in turns[first_vm + 1:] if t.get("role") == "assistant"]
                    if len(after) >= 1 or (c.duration_seconds or 0) > 25:
                        talked += 1
                        if len(samples) < 8:
                            a = agents.get(c.agent_id)
                            samples.append({
                                "at": c.started_at.strftime("%m-%d %H:%M") if c.started_at else "", "dur": c.duration_seconds,
                                "outcome": c.outcome, "agent": (a.name if a else "")[:40],
                                "vm_action": getattr(a, "voicemail_action", None) if a else None,
                                "turns": [[t.get("role", "")[:1], str(t.get("text") or "")[:140]] for t in turns[:10]]})
                durs = {}
                for c in calls:
                    if c.outcome == "voicemail":
                        b = "0-10" if (c.duration_seconds or 0) <= 10 else "11-20" if c.duration_seconds <= 20 else "21-40" if c.duration_seconds <= 40 else "41+"
                        durs[b] = durs.get(b, 0) + 1
                longest = sorted([c for c in calls if c.outcome in ("voicemail", "insufficient_conversation", "no_decision", "no_answer")],
                                 key=lambda c: -(c.duration_seconds or 0))[:10]
                for c in longest:
                    turns = [t for t in c.transcript or [] if isinstance(t, dict)]
                    log.info("todd_vm_long", dur=c.duration_seconds, outcome=c.outcome,
                             at=c.started_at.strftime("%m-%d %H:%M") if c.started_at else "",
                             turns=[[t.get("role", "")[:1], str(t.get("text") or "")[:160]] for t in turns[:12]])
                log.info("todd_vm_durations", voicemail_durations=durs)
                log.info("todd_vm_check", org=org.name, calls=len(calls), outcomes=outcomes, vm_talked_through=talked,
                         agents={a.name[:40]: getattr(a, "voicemail_action", None) for a in agents.values()})
                for s in samples:
                    log.info("todd_vm_sample", org=org.name[:30], **s)
            if not orgs:
                log.info("todd_vm_check", note="no account found for Todd")
    except Exception as exc:
        log.warning("todd_vm_check_failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
