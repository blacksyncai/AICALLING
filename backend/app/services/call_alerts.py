"""Opt-in important-call email alerts; no dialing or CRM writes."""
import asyncio
import html
import uuid
from datetime import timedelta
from urllib.parse import urlparse

import structlog
from sqlalchemy import exists, select, update
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.account import Membership, Organization, User
from app.models.agent import Agent
from app.models.call_alert import CallAlert, CallAlertSettings, now
from app.models.call_log import CallLog
from app.models.lead import Lead
from app.services import email, email_templates as t

log = structlog.get_logger(__name__)
OUTCOMES = {'meeting_booked': 'Appointment booked', 'qualified': 'Qualified follow-up',
            'callback': 'Callback requested', 'interested': 'Interested lead', 'transferred': 'Call transferred'}
DEFAULT_OUTCOMES = ['meeting_booked', 'qualified', 'callback']


def clean_crm_url(value):
    if not value.strip():
        return ''
    p = urlparse(value.strip())
    host = (p.hostname or '').lower()
    if p.scheme != 'https' or not host.endswith('.followupboss.com') or p.username or p.password or p.port or p.path not in ('', '/') or p.query or p.fragment:
        raise ValueError('Use your FUB workspace address, like https://yourteam.followupboss.com.')
    return f'https://{host}'


async def members(db, org_id):
    return (await db.execute(select(User).join(Membership, Membership.user_id == User.id)
        .where(Membership.org_id == org_id).order_by(User.first_name, User.email))).scalars().all()


async def payload(db, org, call, prefs):
    if call.org_id != org.id or call.call_type not in ('outbound', 'inbound') or not call.ended_at:
        raise ValueError('Choose a completed phone call in this account; browser tests are excluded.')
    lead = await db.get(Lead, call.lead_id) if call.lead_id else None
    if lead and lead.org_id != org.id:
        raise ValueError('The call contact does not belong to this account.')
    agent = await db.get(Agent, call.agent_id) if call.agent_id else None
    label = OUTCOMES.get(call.outcome, (call.outcome or call.status).replace('_', ' ').title())
    name = (lead.name if lead else '') or call.to_phone or 'Contact'
    summary = (call.summary or '').strip() or 'No call summary is available yet. Open the call to review it.'
    link = f"{settings.app_url.rstrip('/')}/calls/{call.id}"
    crm = ''
    ref = str((lead.crm_refs or {}).get('followupboss') or '') if lead else ''
    if prefs and prefs.crm_base_url and ref.isdigit():
        crm = f'{clean_crm_url(prefs.crm_base_url)}/2/people/view/{ref}'
    subject = f'{label}: {name}'[:240]
    details = [('Workspace', org.name), ('Contact', name), ('Phone', call.to_phone or ''),
               ('Agent', agent.name if agent and agent.org_id == org.id else 'AI agent'),
               ('Appointment', call.agreed_meeting_time or '')]
    content = t.p(html.escape(summary[:6000]).replace('\n', '<br>'))
    content += ''.join(t.p(f'<strong>{html.escape(k)}:</strong> {html.escape(v)}', size=13) for k,v in details if v)
    if crm:
        content += t.button(html.escape(crm, quote=True), 'View in Follow Up Boss')
    content += t.button(html.escape(link, quote=True), 'Review call in BlackSync')
    content += t.divider() + t.p('You received this because your workspace enabled call alerts or an account administrator sent you this call summary. Manage automatic alerts in Account → Call alerts.', size=12)
    return {'call_id': str(call.id), 'subject': subject, 'summary': summary[:6000], 'outcome': label,
            'contact': name, 'crm_url': crm, 'call_url': link,
            'html': t.layout(title=html.escape(subject), preheader=html.escape(summary[:150]), heading=html.escape(label), body_html=content)}


async def enqueue(db, org_id, call_ids, user_ids, requested_by=None, automatic=False):
    allowed = {u.id for u in await members(db, org_id)}
    if not set(user_ids) <= allowed:
        raise ValueError('Recipients must be current members of this account.')
    count = 0
    for call_id in dict.fromkeys(call_ids):
        call = await db.get(CallLog, call_id)
        if not call or call.org_id != org_id or call.call_type not in ('outbound', 'inbound') or not call.ended_at:
            raise ValueError('Choose completed phone calls in this account.')
        for user_id in dict.fromkeys(user_ids):
            if await db.scalar(select(CallAlert.id).where(CallAlert.call_id == call_id, CallAlert.user_id == user_id)):
                continue
            try:
                async with db.begin_nested():
                    db.add(CallAlert(org_id=org_id, call_id=call_id, user_id=user_id,
                        requested_by=requested_by, automatic=automatic))
                    await db.flush()
                count += 1
            except IntegrityError:
                pass
    return count


def matches_outcome(call, outcomes):
    from app.services.response_review import routing_outcome
    return call.outcome in outcomes or routing_outcome(call) in outcomes


async def collect(db):
    prefs = (await db.execute(select(CallAlertSettings).where(CallAlertSettings.enabled.is_(True)))).scalars().all()
    for p in prefs:
        org = await db.get(Organization, p.org_id)
        if not org or org.status != 'active' or not p.enabled_at:
            continue
        allowed = {str(u.id): u.id for u in await members(db, p.org_id)}
        for user_id in p.user_ids:
            if user_id not in allowed:
                continue
            stmt = select(CallLog.id).where(CallLog.org_id == p.org_id,
                CallLog.call_type.in_(('outbound', 'inbound')), CallLog.ended_at.is_not(None),
                CallLog.events_sent_at >= p.enabled_at, CallLog.events_sent_at < now()-timedelta(seconds=60),
                ((CallLog.outcome.in_(p.outcomes)) | (
                    (CallLog.response_analysis["next_action"].as_string() == "callback_requested") &
                    (CallLog.response_analysis["version"].as_integer() == 1) &
                    CallLog.outcome.notin_(("do_not_call", "not_interested", "declined_conversation", "voicemail", "screened", "no_answer", "failed", "meeting_booked", "transferred"))
                ) if "callback" in p.outcomes else CallLog.outcome.in_(p.outcomes)), ~exists(select(CallAlert.id).where(
                    CallAlert.call_id == CallLog.id, CallAlert.user_id == allowed[user_id])))
            if p.agent_ids:
                stmt = stmt.where(CallLog.agent_id.in_([uuid.UUID(a) for a in p.agent_ids]))
            ids = (await db.execute(stmt.order_by(CallLog.events_sent_at).limit(100))).scalars().all()
            await enqueue(db, p.org_id, ids, [allowed[user_id]], automatic=True)
    await db.commit()


async def deliver(alert_id):
    async with AsyncSessionLocal() as db:
        # Atomic claim; the same Resend idempotency key is retained after lease recovery.
        claim = await db.execute(update(CallAlert).where(CallAlert.id == alert_id,
            CallAlert.status.in_(('queued','retry')), CallAlert.next_at <= now()).values(
                status='sending', next_at=now()+timedelta(minutes=5), attempts=CallAlert.attempts+1))
        await db.commit()
        if claim.rowcount != 1:
            return
        row = await db.get(CallAlert, alert_id)
        org = await db.get(Organization, row.org_id)
        call = await db.get(CallLog, row.call_id)
        user = await db.get(User, row.user_id)
        prefs = await db.get(CallAlertSettings, row.org_id)
        member = await db.scalar(select(Membership.id).where(Membership.org_id == row.org_id, Membership.user_id == row.user_id))
        if not member or not user or not org or org.status != 'active' or not call or call.org_id != row.org_id:
            row.status, row.error = 'cancelled', 'Account, call or recipient is no longer available.'
        elif row.automatic and (not prefs or not prefs.enabled or str(user.id) not in prefs.user_ids or not matches_outcome(call, prefs.outcomes) or (prefs.agent_ids and str(call.agent_id) not in prefs.agent_ids)):
            row.status, row.error = 'cancelled', 'Automatic alert settings changed.'
        elif not email.email_enabled():
            row.status, row.error = 'failed', 'Email delivery is not configured.'
        else:
            data = row.message_payload
            if data is None:
                data = {**(await payload(db, org, call, prefs)), 'to': user.email, 'sender': settings.email_from_calls}
                row.message_payload = data
                await db.commit()  # retries must use the same body/sender as the idempotency key
            if data['to'].strip().lower() != user.email.strip().lower():
                row.status, row.error = 'cancelled', 'Recipient email changed; review before sending.'
                await db.commit()
                return
            try:
                ok = await email.send_email(data['to'], data['subject'], data['html'], sender=data['sender'],
                    kind='call_alert', idempotency_key=f'call-alert-{row.id}')
            except Exception:
                ok = False
            if ok:
                row.status, row.error, row.sent_at = 'sent', '', now()
                await db.commit()  # persist client success independently of the optional internal copy
                copy = await send_admin_copy(org, call, data)
                row.copy_status, row.copy_to = copy['status'], copy['to']
                row.copy_error, row.copy_attempted_at = copy['error'], now()
            else:
                row.status = 'failed' if row.attempts >= 5 else 'retry'
                row.error = 'Email delivery was not confirmed. Check sender verification and email delivery logs.'
                row.next_at = now()+timedelta(minutes=2 ** row.attempts)
        await db.commit()


async def send_admin_copy(org, call, data):
    """A separate, labeled copy for the BlackSync team. One per call (same key for every recipient's alert), and
    a failure here never affects the client's alert."""
    to = (settings.call_alert_copy_email or '').strip()
    if not to:
        return {'status': 'disabled', 'to': '', 'error': ''}
    try:
        ok = await email.send_email(to, f'[{org.name}] {data["subject"]}'[:240], data['html'], sender=data['sender'],
            kind='call_alert_copy', idempotency_key=f'call-alert-copy-{call.id}')
        return {'status': 'sent' if ok else 'unconfirmed', 'to': to,
                'error': '' if ok else 'Internal copy send was not confirmed; check provider logs before retrying.'}
    except Exception as exc:
        log.warning('call_alert_copy_failed', call_id=str(call.id), error=type(exc).__name__)
        return {'status': 'unconfirmed', 'to': to, 'error': 'Internal copy send was not confirmed.'}


async def tick():
    async with AsyncSessionLocal() as db:
        await collect(db)
        await db.execute(update(CallAlert).where(CallAlert.status == 'sending', CallAlert.next_at < now()).values(status='retry'))
        # Resend's deduplication window is finite; never blindly retry old unknown sends.
        await db.execute(update(CallAlert).where(CallAlert.status.in_(('queued','retry')),
            CallAlert.created_at < now()-timedelta(hours=20)).values(status='failed', error='Delivery window expired; review email logs.'))
        ids = (await db.execute(select(CallAlert.id).where(CallAlert.status.in_(('queued','retry')),
            CallAlert.next_at <= now()).order_by(CallAlert.created_at).limit(50))).scalars().all()
        await db.commit()
    for key in ids:
        try:
            await deliver(key)
        except Exception as exc:
            log.warning('call_alert_delivery_failed', alert_id=str(key), error=type(exc).__name__)


def start_worker():
    async def loop():
        while True:
            try:
                await tick()
            except Exception as exc:
                log.warning('call_alert_worker_failed', error=type(exc).__name__)
            await asyncio.sleep(30)
    return asyncio.create_task(loop())
