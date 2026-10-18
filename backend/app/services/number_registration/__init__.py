"""Database outbox for caller-ID registration. Never performs HTTP in purchase requests."""
import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
import structlog
from sqlalchemy import select, update, or_, exists
from app.database import AsyncSessionLocal
from app.models.billing import PhoneNumber
from app.models.number_registration import NumberRegistration as Job, RegistrationAuthorization as Authorization, RegistrationReceipt, ProviderBusiness
from .signalwire import Client, ProviderError, normalize_name

log = structlog.get_logger(__name__)
PROVIDERS = ('signalwire_cnam', 'hiya', 'first_orion', 'signalwire_attestation')
TERMINAL = {'removed', 'unsupported', 'rejected', 'failed'}


def now(): return datetime.now(timezone.utc)


def assignment_key(phone):
    stamp = phone.created_at
    if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=timezone.utc)
    raw = f'{phone.id}:{phone.org_id}:{stamp.astimezone(timezone.utc).isoformat()}'
    return hashlib.sha256(raw.encode()).hexdigest()


async def latest_authorization(db, org_id):
    return (await db.execute(select(Authorization).where(Authorization.org_id == org_id)
                            .order_by(Authorization.created_at.desc(), Authorization.id.desc()).limit(1).execution_options(populate_existing=True))).scalar_one_or_none()


async def enqueue_number(db, phone):
    """Called inside the same transaction as number assignment; conflict-safe under duplicate webhooks."""
    if phone.status != 'active': return
    for provider in PROVIDERS:
        if provider.startswith('signalwire') and phone.carrier != 'signalwire': continue
        values = dict(id=uuid.uuid4(), phone_number_id=phone.id, org_id=phone.org_id,
                      assignment_key=assignment_key(phone), number=phone.number,
                      carrier=phone.carrier or 'twilio', carrier_number_id=phone.provider_sid,
                      provider=provider, phase='register', status='queued', prerequisite='',
                      caller_name='', attempts=0, next_at=now(), response={}, created_at=now(), updated_at=now())
        dialect = db.bind.dialect.name
        if dialect in ('sqlite', 'postgresql'):
            if dialect == 'sqlite': from sqlalchemy.dialects.sqlite import insert
            else: from sqlalchemy.dialects.postgresql import insert
            await db.execute(insert(Job).values(**values).on_conflict_do_nothing(
                index_elements=['phone_number_id','assignment_key','provider']))
        elif not (await db.execute(select(Job.id).where(Job.phone_number_id==phone.id,
                Job.assignment_key==values['assignment_key'], Job.provider==provider))).first():
            db.add(Job(**values))


async def retire_number(db, phone):
    """Persist cleanup before release/reassignment commits; retain old org, number and carrier ID snapshots."""
    await db.execute(update(Job).where(Job.phone_number_id==phone.id, Job.status!='removed')
        .values(phase='remove', status='queued', next_at=now(), updated_at=now()))


async def wake_org(db, org_id):
    await db.execute(update(Job).where(Job.org_id==org_id, Job.status!='removed')
                     .values(next_at=now(), status='queued'))
    for phone in (await db.execute(select(PhoneNumber).where(PhoneNumber.org_id==org_id,
                                                           PhoneNumber.status=='active'))).scalars():
        await enqueue_number(db, phone)


def set_state(job, state, reason='', delay=300):
    job.status, job.prerequisite, job.updated_at = state, reason, now()
    job.next_at = now() + timedelta(seconds=delay)


async def _guard_lease(db, job):
    if not job.lease_token: return
    result = await db.execute(update(Job).where(Job.id==job.id, Job.lease_token==job.lease_token,
        Job.lease_until > now()).values(lease_until=now()+timedelta(minutes=3))
        .execution_options(synchronize_session=False))
    if not result.rowcount: raise ProviderError('lease_lost')


async def _receipt(db, job, method, path, status, body, request_id):
    await _guard_lease(db, job)
    db.add(RegistrationReceipt(registration_id=job.id, method=method, path=path,
        http_status=status, request_id=str(request_id) if request_id else None, response=body))
    job.response = body
    if method == 'POST' and status in (400,401,403,404,422) and not job.request_id:
        job.submission_intent_at = None  # explicit rejection: no ambiguous registration to clean up
    await db.commit()  # receipt and any intent survive a crash before the next state transition


def _valid_receipt(result, job):
    if not isinstance(result, dict) or not result.get('id') or result.get('phone_number_id') != job.carrier_number_id:
        raise ProviderError('invalid_cnam_receipt')
    if result.get('name') != job.caller_name: raise ProviderError('cnam_name_conflict')
    if result.get('status') not in {'pending','in_review','approved','rejected','failed'}:
        raise ProviderError('unrecognized_cnam_status')


async def _signalwire(db, job, phone, authorization):
    client = Client(receipt=lambda *args: _receipt(db, job, *args))
    if not job.carrier_number_id or job.carrier_number_id.startswith('sw:'):
        # Configured SIP caller IDs are not carrier phone-number IDs. Resolve the real inventory record.
        from app.services.signalwire import list_numbers
        inventory = [n for n in await asyncio.wait_for(list_numbers(), timeout=20) if n['number'] == job.number]
        if len(inventory) != 1: raise ProviderError('real_carrier_number_id_required')
        job.carrier_number_id = inventory[0]['sid']
        await db.commit()
    carrier_number = await client.number(job.carrier_number_id, missing_ok=job.phase=='remove')
    if carrier_number is None:
        set_state(job, 'removed'); return
    if carrier_number.get('number') != job.number: raise ProviderError('carrier_number_mismatch')
    latest = await client.latest(job.carrier_number_id)
    if job.phase == 'remove':
        if not job.submission_intent_at and not job.request_id:
            set_state(job, 'removed'); return
        if latest and (latest.get('name') != job.caller_name or
                       (job.request_id and latest.get('id') != job.request_id)):
            raise ProviderError('cleanup_conflict_review_required')
        if not latest and not job.request_id and job.submission_intent_at:
            set_state(job, 'verification_required', 'unknown_submission_cleanup_reconciliation_required', delay=300)
            return
        if latest and not job.request_id:
            _valid_receipt(latest, job)
            job.request_id = latest['id']
        if not carrier_number.get('cnam') and (not latest or latest.get('status') not in {'pending','in_review'}):
            set_state(job, 'removed'); return
        if carrier_number.get('cnam') not in (None,'',job.caller_name):
            raise ProviderError('cleanup_applied_name_conflict')
        if not job.removal_intent_at:
            job.removal_intent_at = now()
            await db.commit()
            await _guard_lease(db, job)
            await db.commit()
            await client.remove(job.carrier_number_id)
        # A 204 queues removal. Poll applied CNAM until null, never equate acceptance with removal.
        set_state(job, 'pending', 'carrier_removal_pending'); return

    if not job.caller_name:
        job.caller_name = normalize_name(authorization.caller_name)
        job.authorization_id = authorization.id
        await db.commit()
    if (latest and latest.get('name') != job.caller_name and latest.get('id') == job.previous_request_id
            and latest.get('status') in {'approved','rejected','failed'} and not carrier_number.get('cnam')):
        latest = None  # previous identity was ours and its applied name has been removed
    if latest:
        if latest.get('name') != job.caller_name:
            # A pre-existing externally managed request must not be superseded automatically.
            raise ProviderError('existing_cnam_request_conflict')
        _valid_receipt(latest, job)
        job.request_id = latest['id']
    else:
        if job.submission_intent_at:
            # A timed-out POST may have succeeded. Keep GET reconciliation, never blind POST retry.
            set_state(job, 'verification_required', 'submission_receipt_unknown_reconciling', delay=300)
            return
        fresh_phone = await db.get(PhoneNumber, job.phone_number_id, populate_existing=True)
        fresh_auth = await latest_authorization(db, job.org_id)
        if (not fresh_phone or fresh_phone.status != 'active' or fresh_phone.org_id != job.org_id
                or assignment_key(fresh_phone) != job.assignment_key or not fresh_auth
                or fresh_auth.revoked_at or fresh_auth.id != authorization.id):
            job.phase = 'remove'
            set_state(job, 'queued', 'assignment_or_authorization_changed', delay=0)
            return
        job.submission_intent_at = now()
        await db.commit()
        await _guard_lease(db, job)
        await db.commit()
        latest = await client.submit(job.carrier_number_id, job.caller_name)
        _valid_receipt(latest, job)
        job.request_id = latest['id']
        await db.commit()
    # A release or reassignment can race an in-flight HTTP request. Preserve its
    # receipt but immediately reconcile the old identity, never leave it approved.
    fresh_phone = await db.get(PhoneNumber, job.phone_number_id, populate_existing=True)
    fresh_auth = await latest_authorization(db, job.org_id)
    if (not fresh_phone or fresh_phone.status != 'active' or fresh_phone.org_id != job.org_id
            or assignment_key(fresh_phone) != job.assignment_key or not fresh_auth
            or fresh_auth.revoked_at or job.provider not in fresh_auth.providers):
        job.phase = 'remove'
        set_state(job, 'queued', 'assignment_or_authorization_changed', delay=0)
        return
    provider_status = latest['status']
    if provider_status == 'approved':
        carrier_number = await client.number(job.carrier_number_id)
        if carrier_number.get('number') != job.number: raise ProviderError('carrier_number_mismatch')
        if carrier_number.get('cnam') == job.caller_name:
            set_state(job, 'approved', delay=86400)
        else:
            set_state(job, 'pending', 'approved_waiting_for_applied_cnam')
    elif provider_status in ('rejected','failed'):
        set_state(job, provider_status, latest.get('required_action') or latest.get('reason') or provider_status)
    else:
        set_state(job, 'pending', latest.get('required_action') or '')


async def process(db, job):
    phone = await db.get(PhoneNumber, job.phone_number_id)
    current = bool(phone and phone.status=='active' and phone.org_id==job.org_id
                   and assignment_key(phone)==job.assignment_key)
    authorization = await latest_authorization(db, job.org_id)
    authorized = bool(authorization and not authorization.revoked_at and job.provider in authorization.providers)
    if job.provider == 'signalwire_attestation' and current:
        order = (await db.execute(select(ProviderBusiness).where(ProviderBusiness.org_id==job.org_id,
            ProviderBusiness.provider=='signalwire_attestation'))).scalar_one_or_none()
        reason = 'signalwire_business_verification_order_pending_attestation_unknown' if order and order.external_id else 'signalwire_business_verification_order_required_attestation_unknown'
        set_state(job, 'verification_required', reason, delay=86400); return
    if not current or not authorized:
        if job.submission_intent_at or job.request_id: job.phase = 'remove'
        elif not current:
            set_state(job, 'removed'); return
        else:
            set_state(job, 'verification_required', 'customer_registration_authorization_required', delay=3600); return
    if job.phase == 'remove' and job.provider != 'signalwire_cnam' and not job.submission_intent_at and not job.request_id:
        set_state(job, 'removed'); return
    if job.provider == 'signalwire_attestation':
        set_state(job, 'verification_required', 'signalwire_business_verification_order_required_attestation_unknown', delay=86400); return
    if job.provider in ('hiya','first_orion'):
        # No fabricated auth/payload/status contracts. Partner execution is deliberately blocked
        # until the official contract and approved production credentials are available.
        set_state(job, 'verification_required', job.provider + '_approved_partner_credentials_and_api_contract_required', delay=3600); return
    if job.phase != 'remove':
        if not job.submission_intent_at and 'signalwire_cnam' not in authorization.fees_authorized:
            set_state(job, 'verification_required', 'carrier_fee_authorization_required', delay=3600); return
        if job.authorization_id and job.caller_name != authorization.caller_name:
            job.phase = 'remove'
        elif job.status == 'removed':
            return
        # Old registrations must be cleared before this assignment can publish a different owner's identity.
        older = (await db.execute(select(Job.id).where(Job.phone_number_id==job.phone_number_id,
            Job.provider==job.provider, Job.id!=job.id, Job.status!='removed'))).first()
        if older:
            set_state(job, 'queued', 'previous_assignment_cleanup_pending', delay=60); return
    await _signalwire(db, job, phone, authorization)
    # Changing an authorized caller name clears the old identity before a new submission.
    if job.status == 'removed' and current and authorized and job.phase=='remove':
        job.previous_request_id = job.request_id
        job.phase, job.caller_name, job.request_id = 'register', '', None
        job.submission_intent_at, job.removal_intent_at = None, None
        job.authorization_id = None
        set_state(job, 'queued', delay=0)


async def claim(db):
    due = or_(Job.lease_until.is_(None), Job.lease_until < now())
    states = ('queued','pending','retry','verification_required','approved')
    candidates = (await db.execute(select(Job.id).where(Job.status.in_(states), Job.next_at<=now(), due)
                                   .order_by(Job.next_at, Job.created_at).limit(20))).scalars().all()
    for job_id in candidates:
        token = str(uuid.uuid4())
        result = await db.execute(update(Job).where(Job.id==job_id, Job.status.in_(states),
            Job.next_at<=now(), due).values(lease_token=token, lease_until=now()+timedelta(minutes=3))
            .execution_options(synchronize_session=False))
        await db.commit()
        if result.rowcount: return job_id, token
    return None


async def run_one():
    async with AsyncSessionLocal() as db:
        acquired = await claim(db)
        if not acquired: return False
        job_id, token = acquired
        job = await db.get(Job, job_id)
        try:
            await process(db, job)
        except ProviderError as exc:
            if exc.code == 'lease_lost':
                await db.rollback()
                return True
            if exc.code == 'unsupported_number': set_state(job, 'unsupported', exc.code)
            elif exc.code == 'carrier_validation_failed': set_state(job, 'failed', exc.code)
            elif exc.retryable:
                job.attempts += 1
                set_state(job, 'retry' if job.attempts < 12 else 'verification_required', exc.code,
                          delay=min(3600, 30 * 2**min(job.attempts,7)))
            else: set_state(job, 'verification_required', exc.code, delay=3600)
        except Exception as exc:
            await db.rollback()
            job = await db.get(Job, job_id)
            job.attempts += 1
            set_state(job, 'retry' if job.attempts < 12 else 'failed', 'registration_worker_error', delay=300)
            log.warning('number_registration_error', job_id=str(job_id), error_type=type(exc).__name__)
        # Lease is substantially longer than bounded provider HTTP calls. Token-fenced finalization.
        if job.lease_token != token:
            await db.rollback()
            return True
        try:
            await _guard_lease(db, job)
        except ProviderError:
            await db.rollback()
            return True
        job.lease_token, job.lease_until = None, None
        await db.commit()
        return True


async def reconcile_assignments(db):
    """Repair missed enqueue events and persist cleanup for released/reassigned numbers."""
    has_assignment = exists(select(Job.id).where(Job.phone_number_id==PhoneNumber.id,
        Job.org_id==PhoneNumber.org_id, Job.created_at>=PhoneNumber.created_at))
    active = (await db.execute(select(PhoneNumber).where(PhoneNumber.status=='active',
        PhoneNumber.source.in_(['purchased','imported']), ~has_assignment).limit(100))).scalars().all()
    for phone in active: await enqueue_number(db, phone)
    jobs = (await db.execute(select(Job).join(PhoneNumber,Job.phone_number_id==PhoneNumber.id).where(
        Job.phase=='register', Job.status!='removed', or_(PhoneNumber.status!='active',
        PhoneNumber.org_id!=Job.org_id, PhoneNumber.created_at>Job.created_at)).limit(100))).scalars().all()
    for job in jobs:
        phone = await db.get(PhoneNumber, job.phone_number_id)
        if not phone or phone.status!='active' or phone.org_id!=job.org_id or assignment_key(phone)!=job.assignment_key:
            job.phase = 'remove'
            set_state(job, 'queued', delay=0)
    await db.commit()


def start_worker():
    async def loop():
        while True:
            try:
                async with AsyncSessionLocal() as db: await reconcile_assignments(db)
                for _ in range(8):
                    if not await run_one(): break
            except Exception as exc:
                log.warning('number_registration_loop_error', error_type=type(exc).__name__)
            await asyncio.sleep(15)
    return asyncio.create_task(loop())


STATUS_LABELS = {'queued':'Registering Caller ID', 'retry':'Registering Caller ID',
    'pending':'Pending Provider Approval', 'approved':'Caller ID Registered',
    'verification_required':'Verification Required', 'unsupported':'Verification Required',
    'rejected':'Registration Failed', 'failed':'Registration Failed', 'removed':'Verification Required'}


async def summaries(db, numbers):
    ids = [n.id for n in numbers]
    jobs = (await db.execute(select(Job).where(Job.phone_number_id.in_(ids)))).scalars().all() if ids else []
    result = {}
    authorizations = {org_id: await latest_authorization(db, org_id) for org_id in {n.org_id for n in numbers}}
    for phone in numbers:
        own = [j for j in jobs if j.phone_number_id==phone.id and j.org_id==phone.org_id
               and j.assignment_key==assignment_key(phone)]
        a = authorizations.get(phone.org_id)
        selected = set(a.providers) if a and not a.revoked_at else set()
        states = [j.status for j in own if j.provider in selected and j.provider != 'signalwire_attestation']
        state = next((s for s in ('failed','rejected','verification_required','unsupported','queued','retry','pending') if s in states),
                     'approved' if states and all(s=='approved' for s in states) else 'verification_required')
        result[phone.id] = {'status': STATUS_LABELS[state],
            'attestation': {'level': 'unknown', 'status': 'action_required' if phone.carrier == 'signalwire' else 'unknown',
                'required_action': 'signalwire_business_verification_order_required' if phone.carrier == 'signalwire' else 'carrier_verification_required'},
            'providers': [
            {'provider': j.provider, 'status': j.status, 'prerequisite': j.prerequisite,
             'request_id': j.request_id} for j in own]}
    return result
