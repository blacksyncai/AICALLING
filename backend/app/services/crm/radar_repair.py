"""TEMPORARY one-time job (remove after it has run): Compass voicemails from before the greeting was saved.

Re-transcribes each voicemail recording with Deepgram, saves the greeting on the call, and queues the Radar
"named voicemail" job again when the greeting says the contact's name. Logs counts only.
"""
import asyncio
import re

import httpx
import structlog
from sqlalchemy import select

log = structlog.get_logger(__name__)


async def _greeting(client, url, agent_text):
    """The callee's side only: of the two channels, the one that sounds least like the agent's own lines."""
    r = await client.post("https://api.deepgram.com/v1/listen",
                          params={"model": "nova-3", "smart_format": "true", "multichannel": "true"}, json={"url": url})
    r.raise_for_status()
    texts = [((c.get("alternatives") or [{}])[0].get("transcript") or "")
             for c in (r.json().get("results") or {}).get("channels") or []]
    if len(texts) < 2:
        return None  # mono: can't tell the greeting from the agent
    agent = set(re.findall(r"[a-z']+", agent_text.casefold()))

    def overlap(t):
        words = re.findall(r"[a-z']+", t.casefold())
        return sum(w in agent for w in words) / max(len(words), 1)
    return min(texts, key=overlap)


async def run():
    from app.config import settings
    from app.database import AsyncSessionLocal
    from app.models.account import Organization
    from app.models.call_log import CallLog
    from app.models.lead import Lead
    from app.models.radar_automation import RadarAutomation, RadarExecution, now
    from app.services import recordings
    from app.services.crm import verification
    from app.agent.runtime import voicemail_greeting_turn

    try:
        async with AsyncSessionLocal() as db:
            org = (await db.execute(select(Organization).where(Organization.name.ilike("Compass Multi Family%")))).scalars().first()
            if not org or not settings.deepgram_api_key:
                return
            rules = {r.id: r for r in (await db.execute(select(RadarAutomation).where(
                RadarAutomation.org_id == org.id, RadarAutomation.status == "active"))).scalars()
                if (r.spec.get("condition") or {}).get("value") == "named_voicemail"}
            jobs = (await db.execute(select(RadarExecution).where(
                RadarExecution.org_id == org.id, RadarExecution.status == "skipped",
                RadarExecution.automation_id.in_(list(rules) or [None])))).scalars().all()
            jobs = [j for j in jobs if rules[j.automation_id].version == j.version][:1000]
            sem, counts, seconds = asyncio.Semaphore(5), {"checked": 0, "no_recording": 0, "failed": 0, "named": 0}, 0.0
            async with httpx.AsyncClient(timeout=60, headers={"Authorization": f"Token {settings.deepgram_api_key}"}) as client:
                async def heard(call):
                    async with sem:
                        url = await recordings.playback_url(call.recording_key)
                        agent = " ".join(str(t.get("text") or "") for t in call.transcript or [] if t.get("role") == "assistant")
                        return await _greeting(client, url, agent) if url else None
                calls = {}
                for j in jobs:
                    call = calls.get(j.call_id) or await db.get(CallLog, j.call_id)
                    calls[j.call_id] = call
                vm = [c for c in calls.values() if c and c.recording_key]
                counts["no_recording"] = sum(1 for c in calls.values() if c and not c.recording_key)
                texts = await asyncio.gather(*(heard(c) for c in vm), return_exceptions=True)
                for call, text in zip(vm, texts):
                    counts["checked"] += 1
                    if isinstance(text, Exception) or not text:
                        counts["failed"] += 1
                        continue
                    seconds += float(call.duration_seconds or 0)
                    turn = voicemail_greeting_turn(call.transcript, text)
                    lead = await db.get(Lead, call.lead_id) if call.lead_id else None
                    # The greeting alone must say "you've reached / leave a message"-style words and the name.
                    if not turn or not lead or verification.classify([turn], lead.name)["status"] != "named_voicemail":
                        continue
                    if turn:
                        call.transcript = list(call.transcript or []) + [turn]
                    row = await verification.record(db, call, lead)
                    if row and row.status == "named_voicemail":
                        counts["named"] += 1
                        for j in jobs:
                            if j.call_id == call.id:
                                j.status, j.error, j.attempts, j.next_at = "queued", "", 0, now()
                    await db.commit()
            log.info("radar_vm_retranscribe", jobs=len(jobs), audio_minutes=round(seconds / 60, 1), **counts)
    except Exception as exc:
        log.warning("radar_vm_retranscribe_failed", error=str(exc)[:500])
