"""Workspace alert controls and explicit admin-only historical notifications."""
import uuid
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, or_, func
from app.config import settings
from app.models.account import Organization
from app.models.agent import Agent
from app.models.call_alert import CallAlert, CallAlertSettings, now
from app.models.call_log import CallLog
from app.models.lead import Lead
from app.services.auth import AdminDep, CtxDep, DbDep, ManagerDep
from app.services import call_alerts as alerts, email

router = APIRouter(prefix='/api/call-alerts', tags=['call-alerts'])
admin_router = APIRouter(prefix='/api/admin/orgs/{org_id}/call-alerts', tags=['admin'])

class SettingsIn(BaseModel):
    enabled: bool = False
    outcomes: list[str] = Field(default_factory=lambda: list(alerts.DEFAULT_OUTCOMES), max_length=5)
    user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    agent_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    crm_base_url: str = Field(default='', max_length=300)

class NotifyIn(BaseModel):
    call_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    user_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)

async def org_for(db, org_id):
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, 'Account not found.')
    return org

async def get_settings(db, org_id):
    await org_for(db, org_id)
    p = await db.get(CallAlertSettings, org_id)
    users = await alerts.members(db, org_id)
    agents = (await db.execute(select(Agent).where(Agent.org_id == org_id).order_by(Agent.name))).scalars().all()
    return {'enabled': bool(p and p.enabled), 'outcomes': p.outcomes if p else alerts.DEFAULT_OUTCOMES,
        'user_ids': p.user_ids if p else [], 'agent_ids': p.agent_ids if p else [],
        'crm_base_url': p.crm_base_url if p else '', 'sender': settings.email_from_calls,
        'email_ready': email.email_enabled(), 'available_outcomes': alerts.OUTCOMES,
        'members': [{'id': str(u.id), 'name': u.full_name or u.email, 'email': u.email} for u in users],
        'agents': [{'id': str(a.id), 'name': a.name} for a in agents]}

async def save_settings(db, org_id, body):
    await org_for(db, org_id)
    valid_users = {u.id for u in await alerts.members(db, org_id)}
    valid_agents = set((await db.execute(select(Agent.id).where(Agent.org_id == org_id))).scalars().all())
    if not set(body.user_ids) <= valid_users or not set(body.agent_ids) <= valid_agents:
        raise HTTPException(400, 'Choose users and agents from this account.')
    if not set(body.outcomes) <= set(alerts.OUTCOMES):
        raise HTTPException(400, 'Choose a supported alert outcome.')
    if body.enabled and (not body.outcomes or not body.user_ids):
        raise HTTPException(400, 'Choose at least one important outcome and recipient.')
    try:
        crm_url = alerts.clean_crm_url(body.crm_base_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    p = await db.get(CallAlertSettings, org_id)
    if not p:
        p = CallAlertSettings(org_id=org_id)
        db.add(p)
    if body.enabled and not p.enabled:
        p.enabled_at = now()
    p.enabled = body.enabled
    p.outcomes = list(dict.fromkeys(body.outcomes))
    p.user_ids = list(dict.fromkeys(str(x) for x in body.user_ids))
    p.agent_ids = list(dict.fromkeys(str(x) for x in body.agent_ids))
    p.crm_base_url = crm_url
    await db.commit()
    return await get_settings(db, org_id)

async def history(db, org_id, page, search='', outcome=''):
    await org_for(db, org_id)
    stmt = select(CallLog, Lead.name).outerjoin(Lead, Lead.id == CallLog.lead_id).where(
        CallLog.org_id == org_id, CallLog.ended_at.is_not(None), CallLog.call_type.in_(('outbound','inbound')))
    if search.strip():
        term=search.strip().lower()
        phone_term=''.join(c for c in term if c.isdigit()) if all(c.isdigit() or c in '+()- . ' for c in term) else term
        stmt=stmt.where(or_(func.lower(Lead.name).contains(term, autoescape=True),
                           func.lower(CallLog.to_phone).contains(phone_term or term, autoescape=True),
                           func.lower(Lead.phone).contains(phone_term or term, autoescape=True)))
    if outcome:
        from app.models.call_log import CALL_OUTCOMES
        if outcome not in CALL_OUTCOMES:
            raise HTTPException(400,'Choose a supported call outcome.')
        stmt=stmt.where(CallLog.outcome==outcome)
    rows=(await db.execute(stmt.order_by(CallLog.started_at.desc(), CallLog.id).offset((page-1)*30).limit(30))).all()
    notifications = (await db.execute(select(CallAlert).where(CallAlert.org_id == org_id,
        CallAlert.call_id.in_([c.id for c,_ in rows])))).scalars().all() if rows else []
    users = {str(u.id): u.full_name or u.email for u in await alerts.members(db, org_id)}
    from app.models.email_message import EmailMessage
    from app.routers.admin_emails import _track, _iso
    keys = [f'call-alert-{n.id}' for n in notifications] + [f'call-alert-copy-{c.id}' for c, _ in rows]
    messages = (await db.scalars(select(EmailMessage).where(EmailMessage.notification_key.in_(keys))
                               .order_by(EmailMessage.sent_at))).all() if keys else []
    by_key = {m.notification_key: m for m in messages}
    def delivery(key):
        m = by_key.get(key)
        return ({**_track(m), 'provider_id': m.resend_id, 'to': m.to_email, 'from': m.from_email} if m else None)
    def copy_for(call):
        tracked = delivery(f'call-alert-copy-{call.id}')
        attempts = [n for n in notifications if n.call_id == call.id and n.copy_status]
        # Provider receipt is authoritative; otherwise retain the last recorded attempt.
        successes = [n for n in attempts if n.copy_status == 'sent']
        candidates = successes or attempts
        last = max(candidates, key=lambda n: n.copy_attempted_at or n.created_at) if candidates else None
        return {'status': tracked['status'] if tracked else (last.copy_status if last else 'unknown'),
                'to': tracked['to'] if tracked else (last.copy_to if last else None),
                'error': '' if tracked else (last.copy_error if last else ''),
                'attempted_at': _iso(last.copy_attempted_at) if last else None, 'delivery': tracked}
    return {'page': page, 'items': [{'id': str(c.id), 'name': name or c.to_phone, 'outcome': c.outcome or c.status,
        'summary': (c.summary or '')[:1200], 'started_at': c.started_at.isoformat(), 'internal_copy': copy_for(c),
        'alerts': [{'id': str(n.id), 'user': users.get(str(n.user_id), 'Former member'), 'status': n.status,
                    'error': n.error, 'automatic': n.automatic, 'attempts': n.attempts,
                    'created_at': _iso(n.created_at), 'sent_at': _iso(n.sent_at),
                    'recipient': (n.message_payload or {}).get('to'), 'sender': (n.message_payload or {}).get('sender'),
                    'delivery': delivery(f'call-alert-{n.id}')} for n in notifications if n.call_id == c.id]}
        for c, name in rows]}


async def preview(db, org_id, body):
    org = await org_for(db, org_id)
    members = {u.id:u for u in await alerts.members(db, org_id)}
    if not set(body.user_ids) <= set(members):
        raise HTTPException(400,'Recipients must be current members of this account.')
    p = await db.get(CallAlertSettings, org_id)
    items=[]
    for call_id in dict.fromkeys(body.call_ids):
        c = await db.get(CallLog,call_id)
        if not c or c.org_id != org_id:
            raise HTTPException(404,'Call not found in this account.')
        try:
            data = await alerts.payload(db,org,c,p)
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc
        data.pop('html')
        items.append(data)
    return {'sender':settings.email_from_calls,'recipients':[{'id':str(members[x].id),'name':members[x].full_name or members[x].email,'email':members[x].email} for x in dict.fromkeys(body.user_ids)],'items':items}

@router.get('')
async def workspace_settings(ctx: ManagerDep, db: DbDep):
    return await get_settings(db,ctx.org.id)

@router.put('')
async def workspace_save(body: SettingsIn, ctx: ManagerDep, db: DbDep):
    return await save_settings(db,ctx.org.id,body)

@router.post('/mute')
async def mute(ctx: CtxDep, db: DbDep):
    p=await db.get(CallAlertSettings,ctx.org.id)
    if p:
        p.user_ids=[x for x in p.user_ids if x!=str(ctx.user.id)]
        await db.commit()
    return {'muted':True}

@admin_router.get('')
async def admin_settings(org_id: uuid.UUID, _: AdminDep, db: DbDep):
    return await get_settings(db,org_id)

@admin_router.put('')
async def admin_save(org_id: uuid.UUID, body: SettingsIn, _: AdminDep, db: DbDep):
    return await save_settings(db,org_id,body)

@admin_router.get('/calls')
async def admin_history(org_id: uuid.UUID, _: AdminDep, db: DbDep, page: int=Query(default=1,ge=1), q: str=Query(default="",max_length=120), outcome: str=""):
    return await history(db,org_id,page,q,outcome)

@admin_router.post('/preview')
async def admin_preview(org_id: uuid.UUID, body: NotifyIn, _: AdminDep, db: DbDep):
    return await preview(db,org_id,body)

@admin_router.post('/notify')
async def admin_notify(org_id: uuid.UUID, body: NotifyIn, user: AdminDep, db: DbDep):
    await preview(db,org_id,body)  # validate every item before any queue entries are written
    if not email.email_enabled():
        raise HTTPException(400,'Email delivery is not configured.')
    try:
        count=await alerts.enqueue(db,org_id,body.call_ids,body.user_ids,requested_by=user.id)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    await db.commit()
    return {'queued':count,'already_notified_or_queued':len(set(body.call_ids))*len(set(body.user_ids))-count}


@admin_router.post('/deliveries/{alert_id}/retry')
async def retry_notification(org_id: uuid.UUID, alert_id: uuid.UUID, _: AdminDep, db: DbDep):
    from datetime import timedelta, timezone
    row=await db.get(CallAlert,alert_id)
    if not row or row.org_id!=org_id:
        raise HTTPException(404,'Notification not found in this account.')
    created=row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else row.created_at
    if row.status not in ('failed','retry') or created < now()-timedelta(hours=20):
        raise HTTPException(409,'Only recent failed deliveries can be retried safely. Review email logs for older or uncertain messages.')
    row.status,row.error,row.attempts,row.next_at='queued','',0,now()
    await db.commit()
    return {'queued':True}
