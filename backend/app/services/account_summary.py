"""
An account's calling summary as an email, sent by a platform admin when they choose (Admin > account > Send a
summary). Nothing here runs on a schedule.
"""

from __future__ import annotations

import html
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.config import settings
from app.models.call_log import CallLog
from app.models.lead import Lead
from app.services import email, email_templates as T

PERIODS = {"today": ("Today", 1), "7d": ("The last 7 days", 7), "30d": ("The last 30 days", 30)}
NOT_REACHED = ("no_answer", "voicemail", "screened", "failed", "missed_callback")
WARM = ("meeting_booked", "qualified", "interested", "callback", "information_requested", "potential_follow_up",
        "transferred")
_LABEL = {"meeting_booked": "Meeting booked", "qualified": "Qualified", "interested": "Interested",
          "callback": "Asked for a callback", "information_requested": "Asked for information",
          "potential_follow_up": "Potential follow-up", "transferred": "Transferred to your team"}


def _since(period: str, now: datetime) -> datetime:
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    return now - timedelta(days=PERIODS[period][1])


async def stats(db, org_id: uuid.UUID, period: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    since = _since(period, now)
    base = (CallLog.org_id == org_id, CallLog.started_at >= since, CallLog.call_type.in_(("outbound", "inbound")))
    rows = (await db.execute(select(CallLog.outcome, func.count(), func.coalesce(func.sum(CallLog.duration_seconds), 0))
                             .where(*base).group_by(CallLog.outcome))).all()
    by = {r[0] or "": int(r[1]) for r in rows}
    total = sum(by.values())
    reached = sum(n for o, n in by.items() if o and o not in NOT_REACHED)
    callbacks = (await db.execute(select(func.count()).select_from(CallLog).where(
        *base, CallLog.call_type == "inbound", CallLog.callback_match.is_not(None)))).scalar_one()
    warm = (await db.execute(
        select(CallLog, Lead).outerjoin(Lead, Lead.id == CallLog.lead_id)
        .where(*base, CallLog.outcome.in_(WARM)).order_by(CallLog.started_at.desc()).limit(8))).all()
    return {
        "period": period, "label": PERIODS[period][0], "calls": total, "conversations": reached,
        "talk_minutes": round(sum(int(r[2]) for r in rows) / 60, 1),
        "meetings": by.get("meeting_booked", 0),
        "interested": sum(by.get(o, 0) for o in WARM if o != "meeting_booked"),
        "voicemails": by.get("voicemail", 0), "callbacks": int(callbacks),
        "missed_callbacks": by.get("missed_callback", 0),
        "leads": [{"name": (lead.name if lead else None) or call.from_phone or call.to_phone or "Unknown",
                   "outcome": _LABEL.get(call.outcome, call.outcome), "summary": (call.summary or "")[:220],
                   "call_id": str(call.id)} for call, lead in warm],
    }


def render(org_name: str, s: dict, note: str = "") -> dict:
    e = html.escape

    def tile(value, label):
        return (f'<td width="33%" style="padding:6px;"><div style="background:#FAF7F4;border-radius:12px;padding:14px 10px;'
                f'text-align:center;"><div style="font:700 22px/1.2 {T.FONT};color:{T.INK};">{value}</div>'
                f'<div style="font:400 12px/1.4 {T.FONT};color:{T.FAINT};">{label}</div></div></td>')

    body = ""
    if note.strip():
        body += f'<p style="margin:0 0 16px 0;font:400 15px/1.6 {T.FONT};color:{T.INK};">{e(note.strip())}</p>'
    body += (f'<p style="margin:0 0 12px 0;font:400 14px/1.6 {T.FONT};color:{T.FAINT};">{e(s["label"])} for {e(org_name)}.</p>'
             '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
             + tile(s["calls"], "Calls") + tile(s["conversations"], "Conversations") + tile(s["meetings"], "Meetings booked")
             + "</tr><tr>" + tile(s["interested"], "Warm leads") + tile(s["callbacks"], "Callbacks answered")
             + tile(f'{s["talk_minutes"]:g}', "Minutes talked") + "</tr></table>")
    if s["missed_callbacks"]:
        body += (f'<p style="margin:14px 0 0 0;font:400 14px/1.6 {T.FONT};color:{T.INK};">'
                 f'{s["missed_callbacks"]} callback{"s" if s["missed_callbacks"] != 1 else ""} went unanswered and '
                 "should be called back by your team.</p>")
    if s["leads"]:
        body += f'<h2 style="margin:22px 0 8px 0;font:700 15px/1.4 {T.FONT};color:{T.INK};">Leads worth a look</h2>'
        for lead in s["leads"]:
            url = f'{(settings.app_url or "https://blacksync.si").rstrip("/")}/calls/{lead["call_id"]}'
            body += (f'<div style="border-top:1px solid #ECE7E2;padding:10px 0;font:400 14px/1.5 {T.FONT};color:{T.INK};">'
                     f'<strong>{e(lead["name"])}</strong> · {e(lead["outcome"] or "")}'
                     + (f'<br><span style="color:{T.FAINT};">{e(lead["summary"])}</span>' if lead["summary"] else "")
                     + f'<br><a href="{e(url)}" style="color:{T.ORANGE};text-decoration:none;">Open the call</a></div>')
    elif s["calls"]:
        body += (f'<p style="margin:16px 0 0 0;font:400 14px/1.6 {T.FONT};color:{T.FAINT};">'
                 "No warm leads in this period yet.</p>")
    subject = f'{org_name}: {s["calls"]} calls, {s["conversations"]} conversations ({s["label"].lower()})'
    return {"subject": subject[:200],
            "html": T.layout(title=subject, preheader=f'{s["meetings"]} meetings booked, {s["interested"]} warm leads',
                             heading="Your calling summary", body_html=body,
                             footer_note="Sent by the BlackSync team.")}


async def send(db, org, period: str, recipients: list[str], note: str = "") -> dict:
    s = await stats(db, org.id, period)
    mail = render(org.name or "Your account", s, note)
    sent, failed = [], []
    for to in recipients:
        ok = await email.send_email(to, mail["subject"], mail["html"], sender=settings.email_from_calls,
                                    kind="account_summary")
        (sent if ok else failed).append(to)
    return {"sent": sent, "failed": failed, "subject": mail["subject"], "stats": s}
