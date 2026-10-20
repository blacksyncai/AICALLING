import asyncio
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pytest
from fastapi import HTTPException
from app.routers.calls import _range_bound

UTC = timezone.utc
NY = ZoneInfo('America/New_York')

def test_picker_uses_account_zone_and_explicit_offsets():
    assert _range_bound(datetime(2026, 10, 18, 10), NY) == datetime(2026, 10, 18, 14, tzinfo=UTC)
    assert _range_bound(datetime.fromisoformat('2026-10-18T10:00:00+02:00'), NY) == datetime(2026, 10, 18, 8, tzinfo=UTC)

def test_dst_gap_rejected_and_repeated_hour_included():
    with pytest.raises(HTTPException): _range_bound(datetime(2026, 3, 8, 2, 30), NY)
    start = _range_bound(datetime(2026, 11, 1, 1, 15), NY)
    end = _range_bound(datetime(2026, 11, 1, 1, 45), NY, end=True)
    assert (end-start).total_seconds() == 90*60

@pytest.mark.parametrize('params', [
    {'started_from': 'bad'},
    {'started_from': '2026-10-18T12:00', 'started_before': '2026-10-18T11:00'},
    {'started_from': '2026-10-18T12:00', 'started_before': '2026-10-18T12:00'},
    {'date': '2026-10-18', 'started_from': '2026-10-18T12:00'},
    {'started_from': '2026-03-08T02:30'},
])
def test_invalid_ranges(client, monkeypatch, params):
    monkeypatch.setattr('app.routers.calls.org_zone', lambda org: NY)
    assert client.get('/api/calls/', params=params).status_code in (400, 422)

def test_range_boundaries_pagination_filters_and_tenant_isolation(client, agent_id, monkeypatch):
    from app.database import AsyncSessionLocal
    from app.models.call_log import CallLog
    from app.models.account import Organization
    from sqlalchemy import delete
    monkeypatch.setattr('app.routers.calls.org_zone', lambda org: NY)
    org_id = uuid.UUID(client.get('/api/auth/me').json()['org']['id'])
    other = uuid.uuid4()
    ids = [uuid.uuid4() for _ in range(5)]
    async def seed():
        async with AsyncSessionLocal() as db:
            db.add(Organization(id=other, name='Other tenant'))
            await db.flush()
            for i, minute in enumerate([59, 0, 30, 0, 15]):
                hour = [13, 14, 14, 15, 14][i]
                db.add(CallLog(id=ids[i], org_id=other if i==4 else org_id, agent_id=uuid.UUID(agent_id),
                               livekit_room_name=f'range-{ids[i]}', started_at=datetime(2026,10,18,hour,minute,tzinfo=UTC),
                               call_type='web', outcome='interested', status='completed', duration_seconds=20))
            await db.commit()
    async def cleanup():
        async with AsyncSessionLocal() as db:
            await db.execute(delete(CallLog).where(CallLog.id.in_(ids)))
            await db.execute(delete(Organization).where(Organization.id==other))
            await db.commit()
    asyncio.run(seed())
    try:
        q={'started_from':'2026-10-18T10:00','started_before':'2026-10-18T11:00','agent_id':agent_id,'call_type':'web','outcome':'interested','page_size':1}
        a=client.get('/api/calls/',params=q);assert a.status_code==200,a.text
        assert a.json()['total']==2 and a.json()['items'][0]['id']==str(ids[2])
        b=client.get('/api/calls/',params={**q,'page':2}).json()
        assert b['total']==2 and b['items'][0]['id']==str(ids[1])
        assert client.get('/api/calls/',params={**q,'outcome':'failed'}).json()['total']==0
        for key in ('started_from','started_before'):
            open_q={k:v for k,v in q.items() if k!=key}
            assert client.get('/api/calls/',params=open_q).json()['total']==3
        day=client.get('/api/calls/',params={'date':'2026-10-18','agent_id':agent_id}).json()
        assert day['total']==4
    finally:
        asyncio.run(cleanup())
