import asyncio
import uuid

from app.database import AsyncSessionLocal
from app.models.billing import PhoneNumber
from app.services import caller_reputation, plivo


def test_sweep_registers_new_plivo_numbers_and_shows_progress(client, monkeypatch):
    org_id = uuid.UUID(client.get('/api/auth/me').json()['org']['id'])
    number = f'+1415{uuid.uuid4().int % 10_000_000:07d}'
    other = f'+1415{uuid.uuid4().int % 10_000_000:07d}'

    async def seed():
        async with AsyncSessionLocal() as db:
            db.add(PhoneNumber(org_id=org_id, number=number, status='active', source='purchased', carrier='plivo'))
            db.add(PhoneNumber(org_id=org_id, number=other, status='active', source='purchased', carrier='signalwire'))
            await db.commit()
    asyncio.run(seed())

    enabled = []
    monkeypatch.setattr(plivo, 'ready', lambda: True)

    async def profile():
        return 'prof-1'

    async def status(n):
        return {'status': 'NOT_REGISTERED', 'carriers': {}}

    async def enable(n, p):
        enabled.append((n, p))
        return {'status': 'PENDING', 'carriers': {'at&t': {'status': 'PENDING', 'reason': '', 'reason_code': ''}}}
    monkeypatch.setattr(plivo, 'reputation_profile', profile)
    monkeypatch.setattr(plivo, 'reputation_status', status)
    monkeypatch.setattr(plivo, 'enable_reputation', enable)
    asyncio.run(caller_reputation.sweep())
    assert (number, 'prof-1') in enabled and all(n != other for n, _ in enabled)  # Plivo numbers only

    rows = {n['number']: n for n in client.get('/api/phone-numbers').json()['numbers']}
    assert rows[number]['spam_protection']['status'] == 'PENDING'
    assert rows[other]['spam_protection'] is None

    async def active(n):
        return {'status': 'ACTIVE', 'carriers': {'at&t': {'status': 'ACTIVE', 'reason': '', 'reason_code': ''},
                                                 't-mobile': {'status': 'ACTIVE', 'reason': '', 'reason_code': ''}}}
    monkeypatch.setattr(plivo, 'reputation_status', active)
    enabled.clear()
    asyncio.run(caller_reputation.sweep())
    assert not any(n == number for n, _ in enabled)  # already attached: only re-read
    rows = {n['number']: n for n in client.get('/api/phone-numbers').json()['numbers']}
    assert rows[number]['spam_protection']['status'] == 'ACTIVE'


def test_profile_lookup_matches_plivos_real_list_shape(monkeypatch):
    # Plivo's GET Profile/ list omits enable_caller_reputation (seen in production): match on status.
    async def fake(method, path, **kw):
        assert (method, path) == ('GET', 'Profile/')
        return {'api_id': 'x', 'meta': {}, 'profiles': [
            {'profile_uuid': 'pending-one', 'enable_caller_reputation': None, 'caller_reputation_status': 'PENDING'},
            {'profile_uuid': 'd23f7e75', 'enable_caller_reputation': None, 'caller_reputation_status': 'APPROVED'}]}
    monkeypatch.setattr(plivo, '_request', fake)
    assert asyncio.run(plivo.reputation_profile()) == 'd23f7e75'


def test_new_number_registers_right_after_purchase(client, monkeypatch):
    """The real post-purchase path: register_soon -> profile lookup -> attach -> status saved."""
    org_id = uuid.UUID(client.get('/api/auth/me').json()['org']['id'])
    number = f'+1512{uuid.uuid4().int % 10_000_000:07d}'
    calls = []

    async def fake(method, path, **kw):
        calls.append((method, path, kw.get('json')))
        if path == 'Profile/':
            return {'profiles': [{'profile_uuid': 'prof-9', 'enable_caller_reputation': None,
                                  'caller_reputation_status': 'APPROVED'}]}
        if method == 'GET':
            return {'number': number[1:], 'caller_reputation_status': None, 'caller_reputation_by_carrier': None}
        return {'caller_reputation_status': 'PENDING',
                'caller_reputation_by_carrier': {'at&t': {'status': 'PENDING'}, 't-mobile': {'status': 'PENDING'}}}
    monkeypatch.setattr(plivo, '_request', fake)
    monkeypatch.setattr(caller_reputation, 'DELAY_SECONDS', 0)

    async def go():
        async with AsyncSessionLocal() as db:
            row = PhoneNumber(org_id=org_id, number=number, status='active', source='purchased', carrier='plivo')
            db.add(row)
            await db.commit()
            caller_reputation.register_soon(row.id)
        for _ in range(50):
            if not caller_reputation._PENDING:
                break
            await asyncio.sleep(0.05)
    asyncio.run(go())
    assert ('POST', f'Number/{number[1:]}/', {'caller_reputation': 'enabled', 'profile_uuid': 'prof-9'}) in calls
    row = next(n for n in client.get('/api/phone-numbers').json()['numbers'] if n['number'] == number)
    assert row['spam_protection']['status'] == 'PENDING'
