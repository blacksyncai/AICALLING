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
