"""Read-only queue forecast. Times are eligibility bounds, never promised dial times."""
from collections import defaultdict
from datetime import datetime, timedelta, time, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from sqlalchemy import select, func
from app.models.lead import Lead
from app.models.call_log import CallLog
from app.services import quiet_hours, entitlements


def next_eligible(campaign, phone, due):
    from app.routers.campaigns import next_window_start
    due = due if due.tzinfo else due.replace(tzinfo=timezone.utc)
    due = due.astimezone(timezone.utc)
    candidate = next_window_start(campaign, due)
    deadline = due + timedelta(days=8)
    for _ in range(32):
        if candidate is None or candidate > deadline:
            return None
        if quiet_hours.ok_to_call(phone, candidate):
            return candidate
        openings = []
        for name in quiet_hours.zones_for(phone):
            zone = ZoneInfo(name)
            local = candidate.astimezone(zone)
            if not quiet_hours.EARLIEST <= local.hour < quiet_hours.LATEST:
                day = local.date() + timedelta(days=1 if local.hour >= quiet_hours.LATEST else 0)
                openings.append(datetime.combine(day, time(quiet_hours.EARLIEST), zone).astimezone(timezone.utc))
        if not openings:
            return None
        candidate = next_window_start(campaign, max(openings))
    return None


async def forecast(db, campaign, org, now=None):
    from app.routers.campaigns import dial_eligibility, calling_rules, retry_waits, RETRY_STATUSES, _aware, _IN_FLIGHT
    now = now or datetime.now(timezone.utc)
    now = _aware(now).astimezone(timezone.utc)
    rules = calling_rules(campaign)
    result = {'generated_at':now.isoformat(), 'timezone':rules['timezone'], 'campaign_status':campaign.status,
              'automatic':campaign.status=='running', 'direction':campaign.direction or 'outbound',
              'next_at':None, 'next_count':0, 'ready_now':0, 'new_contacts':0, 'redials':0,
              'waiting_for_outcome':0, 'no_matching_window':0, 'active_calls':0,
              'concurrency':campaign.max_concurrent_calls or 1, 'windows':[], 'contacts':[],
              'retry_plan':[{'retry':i+1,'delay_minutes':m} for i,m in enumerate(retry_waits(campaign))],
              'max_attempts':rules['max_attempts'], 'reason':None}
    if campaign.direction=='inbound':
        result['reason']='inbound'
        return result
    if campaign.status in ('cancelled','completed'):
        result['automatic']=False
        result['reason']=campaign.status
        return result
    try:
        zone=ZoneInfo(rules['timezone'])
    except (ValueError,KeyError):
        result['automatic']=False
        result['reason']='invalid_timezone'
        return result
    if org.status!='active':
        result['automatic']=False
        result['reason']='account_suspended'
    elif not campaign.agent_id:
        result['automatic']=False
        result['reason']='agent_required'
    elif campaign.status!='running':
        result['reason']=campaign.status
    cap=await entitlements.concurrency_cap(db,org)
    if cap is not None: result['concurrency']=min(result['concurrency'],cap)
    result['active_calls']=int(await db.scalar(select(func.count()).select_from(CallLog).where(
        CallLog.org_id==org.id,CallLog.campaign_id==campaign.id,CallLog.status.in_(_IN_FLIGHT),
        CallLog.started_at>=now-timedelta(minutes=20))) or 0)
    rows=(await db.execute(select(Lead.id,Lead.name,Lead.phone,Lead.status,Lead.attempts,Lead.next_attempt_at,Lead.last_called_at)
        .where(Lead.org_id==org.id,Lead.campaign_id==campaign.id,
               Lead.status.in_(('new','calling',*RETRY_STATUSES)),
               (Lead.do_not_call.is_(None)|Lead.do_not_call.is_(False))).order_by(Lead.created_at,Lead.id))).all()
    stale=[row.id for row in rows if row.status=='calling' and (not row.last_called_at or _aware(row.last_called_at)<now-timedelta(minutes=20))]
    answered=set((await db.scalars(select(CallLog.lead_id).where(CallLog.org_id==org.id,
        CallLog.lead_id.in_(stale),CallLog.answered_at.is_not(None)))).all()) if stale else set()
    entries=[]
    for row in rows:
        status=row.status
        if status=='calling':
            if row.last_called_at and _aware(row.last_called_at)>=now-timedelta(minutes=20):
                result['waiting_for_outcome']+=1
                continue
            if row.id in answered: continue
            status='no_answer'  # mirror queue recovery without mutating the contact
        lead=SimpleNamespace(status=status,do_not_call=False,attempts=row.attempts,next_attempt_at=row.next_attempt_at)
        if dial_eligibility(lead,campaign,now) is None: continue
        retry=status in RETRY_STATUSES
        due=max(now,_aware(row.next_attempt_at)) if retry and row.next_attempt_at else now
        eligible=next_eligible(campaign,row.phone,due)
        result['redials' if retry else 'new_contacts']+=1
        if eligible is None:
            result['no_matching_window']+=1
            continue
        if eligible<=now: result['ready_now']+=1
        attempts=max(row.attempts or 0,1) if retry else row.attempts or 0
        entries.append({'id':str(row.id),'name':row.name or row.phone,'kind':'redial' if retry else 'first_call',
                        'attempt':attempts+1,'retry':attempts if retry else 0,
                        'due_at':_aware(row.next_attempt_at).isoformat() if retry and row.next_attempt_at else None,
                        'eligible_at':eligible.isoformat()})
    entries.sort(key=lambda e:(e['eligible_at'],e['id']))
    if entries:
        result['next_at']=entries[0]['eligible_at']
        result['next_count']=sum(e['eligible_at']==result['next_at'] for e in entries)
    groups=defaultdict(list)
    for entry in entries:
        local=datetime.fromisoformat(entry['eligible_at']).astimezone(zone)
        groups[local.replace(minute=0,second=0,microsecond=0).astimezone(timezone.utc)].append(entry)
    result['window_count']=len(groups)
    result['windows']=[{'start_at':max(start,now).isoformat(),'end_at':(start+timedelta(hours=1)).isoformat(),
                        'contacts':len(group),'redials':sum(e['kind']=='redial' for e in group),
                        'first_calls':sum(e['kind']=='first_call' for e in group)}
                       for start,group in sorted(groups.items())[:12]]
    result['contacts']=entries[:20]
    result['contact_count']=len(entries)
    return result
