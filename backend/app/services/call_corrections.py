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


# ── One-off: Maxwell's reminder for his 12:00 PM call with Jose Morales (approved by the admin, Nov 17 2026) ──

REMINDER_DEADLINE = "2026-11-17T18:00:00+00:00"  # 12:00 PM Central: after that a reminder is pointless
REMINDER_KEY = "reminder:maxwell:jose-morales:2026-11-17"
REMINDER_SUBJECT = "Reminder: call with Jose Morales today at 12:00 PM"
REMINDER_SENDER = "BlackSync <notifications@blacksync.ai>"
REMINDER_TO = (("maxwelljones214@gmail.com", REMINDER_KEY), ("hamza@blacksync.ai", REMINDER_KEY + ":copy"))
REMINDER_HTML = """<!doctype html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Reminder: call with Jose Morales today at 12:00 PM</title></head>
<body style="margin:0;padding:24px 12px;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#18181b;">
  <div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:12px;border:1px solid #e4e4e7;overflow:hidden;">
    <div style="padding:24px;">
      <p style="margin:0 0 16px;font-size:16px;line-height:1.5;">Hey Maxwell,</p>
      <p style="margin:0 0 20px;font-size:16px;line-height:1.5;">Friendly reminder: you have a scheduled call coming up <strong>today at 12:00 PM Central</strong> with Jose Morales.</p>

      <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;background:#fafafa;border:1px solid #e4e4e7;border-radius:10px;">
        <tr><td style="padding:14px 16px 6px;font-size:13px;color:#71717a;width:90px;vertical-align:top;">Who</td><td style="padding:14px 16px 6px;font-size:15px;font-weight:600;">Jose Morales</td></tr>
        <tr><td style="padding:6px 16px;font-size:13px;color:#71717a;vertical-align:top;">When</td><td style="padding:6px 16px;font-size:15px;">Tuesday, November 17 at 12:00 PM Central</td></tr>
        <tr><td style="padding:6px 16px;font-size:13px;color:#71717a;vertical-align:top;">Phone</td><td style="padding:6px 16px;font-size:15px;"><a href="tel:+12057711681" style="color:#ea580c;text-decoration:none;">(205) 771-1681</a></td></tr>
        <tr><td style="padding:6px 16px 14px;font-size:13px;color:#71717a;vertical-align:top;">Property</td><td style="padding:6px 16px 14px;font-size:15px;">8722 Highlands Drive, Trussville, AL 35173</td></tr>
      </table>

      <p style="margin:20px 0 8px;font-size:14px;font-weight:600;">Where things stand</p>
      <p style="margin:0 0 20px;font-size:15px;line-height:1.55;color:#3f3f46;">His listing expired, and Vivian talked with him about taking another look at why it didn't sell. He's potentially open to an in-person visit, but said he needs to consult first, so he chose a call back today at 12 to talk it through.</p>

      <p style="margin:0;font-size:15px;line-height:1.5;">Good luck on the call!<br><span style="color:#71717a;">— BlackSync</span></p>
    </div>
  </div>
</body>
</html>
"""


async def send_maxwell_reminder() -> int:
    """Send the approved reminder once per recipient, only before the call. Returns how many went out."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.email_message import EmailMessage
    from app.services.email import email_enabled, send_email

    if datetime.now(timezone.utc) >= datetime.fromisoformat(REMINDER_DEADLINE) or not email_enabled():
        return 0
    sent = 0
    for to, key in REMINDER_TO:
        async with AsyncSessionLocal() as db:
            if await db.scalar(select(EmailMessage.id).where(EmailMessage.notification_key == key)):
                continue  # already sent (a restart must never send it twice)
        if await send_email(to, REMINDER_SUBJECT, REMINDER_HTML, sender=REMINDER_SENDER, kind="reminder",
                            idempotency_key=key):
            sent += 1
            log.info("maxwell_reminder_sent", to_domain=to.split("@")[-1])
    return sent


# ── Brian Melin (PorchLight / RCI, Nov 19): agreed to 4:45 PM, the call ended before the booking was sent ─────────
BRIAN_CALL = "7211f71f-ae5a-413c-a32e-7b95177e7115"
BRIAN_START = "2026-11-20T00:45:00Z"  # Thu Nov 19, 4:45 PM Pacific (the slot Maya offered and he picked)
BRIAN_EMAIL = "brian26267@gmail.com"  # spelled and confirmed twice on the call


async def book_brian_melin() -> str | None:
    """Book the meeting Brian agreed to on Maya's calendar, once. Returns the receipt, or None when skipped."""
    from app.database import AsyncSessionLocal
    from app.models.agent import Agent
    from app.models.call_log import CallLog
    from app.models.lead import Lead
    from app.services import calendar as cal
    from app.services.secret_store import decrypt_value

    if datetime.now(timezone.utc) >= datetime.fromisoformat(BRIAN_START.replace("Z", "+00:00")):
        return None
    async with AsyncSessionLocal() as db:
        call = await db.get(CallLog, uuid.UUID(BRIAN_CALL))
        if call is None or (call.extracted_data or {}).get("_manual_booking") or call.meeting_link:
            return None  # already booked: a restart must never book twice
        agent = await db.get(Agent, call.agent_id)
        lead = await db.get(Lead, call.lead_id) if call.lead_id else None
        fields = (lead.custom_fields or {}) if lead else {}
        receipt = await cal.create_booking(
            BRIAN_START, BRIAN_EMAIL, (lead.name if lead else "") or "Brian Melin", agent.calcom_event_type_id,
            decrypt_value(agent.calcom_api_key_enc), agent.calendar_timezone, provider=agent.calendar_provider,
            phone=call.to_phone or "", address=str(fields.get("property_address") or fields.get("address") or ""))
        label = "Thursday, November 19 at 4:45 PM"
        call.transcript = list(call.transcript or []) + [{
            "role": "tool", "tool": "book_appointment", "args": {"slot": label, "email": BRIAN_EMAIL, "by": "admin"},
            "result": {"output": {"booked": label, "link": receipt}, "success": True}}]
        call.meeting_link, call.agreed_meeting_time, call.prospect_email = receipt, label, BRIAN_EMAIL
        call.outcome, call.status = "meeting_booked", "completed"
        call.extracted_data = {**(call.extracted_data or {}), "_booking_status": "confirmed", "_manual_booking": receipt}
        call.response_analysis = {**(call.response_analysis or {}), "_manual_outcome": "meeting_booked",
                                  "next_action": "meeting_booked"}
        if lead is not None:
            lead.status = "meeting_booked"
            lead.email = lead.email or BRIAN_EMAIL
        await db.commit()
        log.info("brian_melin_booked", receipt=receipt[:120])
        return receipt
