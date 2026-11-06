"""Admin corrections to a call: what was actually said, and a trimmed recording (the original is kept)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog

log = structlog.get_logger(__name__)


async def apply_correction(db, call, turns: list[dict], keep: float | None, by: str | None = None) -> None:
    from app.services import recordings

    meta = dict(call.response_analysis or {})
    record = dict(meta.get("_correction") or {})
    record.setdefault("original_transcript", call.transcript)
    record.update(at=datetime.now(timezone.utc).isoformat(), by=by)
    if keep is not None and call.recording_key:
        record["original_recording_key"] = await recordings.replace_with_trimmed(call.recording_key, keep)
        record["kept_seconds"] = keep
    if turns:
        call.transcript = turns
    meta["_correction"] = record
    call.response_analysis = meta
    await db.commit()
    if turns:
        from app.services.outbound_call import _analyze

        await _analyze(str(call.id), force=True)
        await db.refresh(call)
    log.info("call_corrected", call_log_id=str(call.id), turns=len(turns), kept_seconds=keep)


# One-off: a PorchLight call cut off by a deploy on 2026-11-06 (transcript provided by the admin from the recording).
_STEVEN = uuid.UUID("c5361037-8732-44dc-a647-1d37fa6d3dc1")
_STEVEN_TURNS = [
    ("user", "Hello?"),
    ("assistant", "Hey Steven, this is Sofia from Danny Burgess's team at PorchLight. Your home search came up as we "
                  "were going through an older list, and Danny wanted me to reach out. Are you still looking around, "
                  "or leaning towards somewhere else?"),
    ("user", "What are you talking about? Leaning towards what?"),
    ("user", "Is this AI, or is this a person or AI?"),
    ("assistant", "Yes, I'm an AI assistant helping Danny's team with follow-up."),
    ("user", "I don't know the name of the company."),
    ("assistant", "I'm with PorchLight Bay Area."),
    ("user", "PorchLight Bay Area. And what do you do, actually?"),
    ("assistant", "We help folks find homes that match what they're looking for. Are you still looking around the Bay "
                  "Area, or leaning towards somewhere else?"),
    ("user", "No, I'm still looking."),
    ("assistant", "Got it. What are your must-have features, like number of bedrooms or baths?"),
    ("user", "Three, three and three, and about twenty-seven or twenty-six hundred square feet."),
]


async def fix_steven_call() -> None:
    from app.database import AsyncSessionLocal
    from app.models.call_log import CallLog

    async with AsyncSessionLocal() as db:
        call = await db.get(CallLog, _STEVEN)
        if call is None or (call.response_analysis or {}).get("_correction"):
            return
        await apply_correction(db, call, [{"role": r, "text": t} for r, t in _STEVEN_TURNS], 83.5,
                               by="hamza@blacksync.ai")
