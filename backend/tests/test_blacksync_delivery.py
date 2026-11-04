"""Exercise persisted receipt selection and retry state against a real SQLite schema."""
import asyncio
import datetime as dt
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import white_label, number_registration, call_alert, account, agent, billing, builder, calendar, call_log, campaign, crm, crm_command, radar_automation, stress_test, terms, email_message, invite, lead, lead_finder, messaging, oauth, playbook, support
from app.models.account import Organization
from app.models.call_log import CallLog
from app.models.crm import CrmCallDelivery, CrmConnection
from app.services.crm import sync
from app.services.crm.blacksync_delivery import deliver_connection, recover_calls
from app.services.crm.http import CrmError

UTC = dt.timezone.utc


class AsyncDb:
    # Keep the database tests independent of the sandbox's async SQLite worker thread.
    def __init__(self, session): self.session = session
    def add(self, value): self.session.add(value)
    async def execute(self, query): return self.session.execute(query)
    async def flush(self): self.session.flush()
    async def get(self, model, key): return self.session.get(model, key)


@pytest.fixture
def records():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        org = Organization(name='Test org')
        session.add(org); session.flush()
        conn = CrmConnection(org_id=org.id, provider='blacksync_cloud', status='connected', created_at=dt.datetime.now(UTC)-dt.timedelta(hours=1))
        session.add(conn); session.flush()
        call = CallLog(org_id=org.id, call_type='outbound', livekit_room_name='room', to_phone='+14155550123', status='completed', outcome='interested',
                       ended_at=dt.datetime.now(UTC), events_sent_at=dt.datetime.now(UTC), duration_seconds=120,
                       transcript=[{'role':'assistant','text':'Hello'},{'role':'user','text':'Interested'}])
        session.add(call); session.commit()
        yield session, AsyncDb(session), conn, call
    engine.dispose()


def test_finished_call_is_recovered_once_and_receipt_survives_new_session(records):
    session, db, conn, call = records
    asyncio.run(recover_calls(db, conn)); session.commit()
    asyncio.run(recover_calls(db, conn)); session.commit()
    rows = list(session.scalars(select(CrmCallDelivery)))
    assert len(rows) == 1 and rows[0].call_id == call.id and rows[0].status == 'pending'
    session.expire_all()
    assert session.get(CrmCallDelivery, rows[0].id).status == 'pending'


def test_transient_error_is_saved_and_retried_with_same_call_id(records, monkeypatch):
    session, db, conn, call = records
    sent = []
    async def send(db, connection, payload, **kwargs):
        sent.append(payload)
        if len(sent) == 1: raise CrmError('Unavailable', 503)
    monkeypatch.setattr(sync, 'push_call_to', send)
    asyncio.run(deliver_connection(db, conn)); session.commit()
    job = session.scalar(select(CrmCallDelivery))
    assert job.status == 'pending' and job.attempts == 1
    assert job.sent_at is None
    asyncio.run(deliver_connection(db, conn))
    assert len(sent) == 1  # backoff is persisted, not a tight retry loop
    job.next_attempt_at = dt.datetime.now(UTC)-dt.timedelta(seconds=1); session.commit()
    asyncio.run(deliver_connection(db, conn)); session.commit()
    assert job.status == 'sent' and job.attempts == 2
    assert sent[0]['call_id'] == sent[1]['call_id'] == str(call.id)
    asyncio.run(deliver_connection(db, conn)); assert len(sent) == 2


def test_bad_credentials_block_delivery_instead_of_marking_it_sent(records, monkeypatch):
    session, db, conn, call = records
    async def send(*args, **kwargs): raise CrmError('Unauthorized', 401)
    monkeypatch.setattr(sync, 'push_call_to', send)
    asyncio.run(deliver_connection(db, conn)); session.commit()
    job = session.scalar(select(CrmCallDelivery))
    assert job.status == 'blocked' and job.sent_at is None


def test_other_accounts_browser_calls_and_old_calls_are_not_queued(records):
    session, db, conn, call = records
    other_org = Organization(name='Other org'); session.add(other_org); session.flush()
    for org_id, kind, when in [(other_org.id,'outbound',dt.datetime.now(UTC)),(conn.org_id,'web',dt.datetime.now(UTC)),(conn.org_id,'outbound',conn.created_at-dt.timedelta(days=1))]:
        session.add(CallLog(org_id=org_id,call_type=kind,livekit_room_name=str(uuid.uuid4()),status='completed',ended_at=when,events_sent_at=when))
    session.commit(); asyncio.run(recover_calls(db,conn)); session.commit()
    assert list(session.scalars(select(CrmCallDelivery.call_id))) == [call.id]


def test_disabled_sync_does_not_deliver_or_create_jobs(records, monkeypatch):
    session, db, conn, call = records
    conn.settings={'log_calls':False}; session.commit()
    asyncio.run(deliver_connection(db,conn)); session.commit()
    assert session.scalar(select(CrmCallDelivery)) is None
