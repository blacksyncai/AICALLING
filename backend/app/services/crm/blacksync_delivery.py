"""Recover completed calls from the database and deliver them independently of process lifetime."""
from __future__ import annotations

import datetime as dt
from sqlalchemy import select
from app.models.crm import CrmCallDelivery, CrmConnection
from app.models.call_log import CallLog
from app.models.lead import Lead
from app.models.agent import Agent
from app.services.crm.http import CrmError

UTC = dt.timezone.utc


def completed_call_data(call, lead=None, agent=None):
    return {
        "call_id": str(call.id), "outcome": call.outcome, "summary": call.summary,
        "duration_seconds": call.duration_seconds, "to_phone": call.from_phone if call.call_type == "inbound" else call.to_phone,
        "agent_name": agent.name if agent else "AI agent", "started_at": call.started_at,
        "meeting_time": call.agreed_meeting_time, "meeting_link": call.meeting_link,
        "prospect_email": call.prospect_email, "extracted_data": call.extracted_data or {},
        "response_analysis": getattr(call, "response_analysis", None) or {},
        "contact": {"id": str(lead.id), "name": lead.name, "phone": lead.phone,
                    "email": lead.email, "company": lead.company} if lead else None,
        "direction": "inbound" if call.call_type == "inbound" else "outbound",
        "transcript": "\n".join(
            f"{'Agent' if turn.get('role') == 'assistant' else 'Customer'}: {turn.get('text') or ''}"
            for turn in (call.transcript or [])
            if isinstance(turn, dict) and turn.get('role') in ('assistant', 'user') and turn.get('text')
        ),
    }


async def recover_calls(db, conn):
    missing = select(CrmCallDelivery.id).where(CrmCallDelivery.connection_id == conn.id,
                                              CrmCallDelivery.call_id == CallLog.id).exists()
    calls = (await db.execute(select(CallLog.id).where(
        CallLog.org_id == conn.org_id, CallLog.call_type.in_(("inbound", "outbound")),
        CallLog.events_sent_at.isnot(None), CallLog.ended_at >= conn.created_at, ~missing,
    ).order_by(CallLog.ended_at).limit(100))).scalars().all()
    for call_id in calls:
        db.add(CrmCallDelivery(connection_id=conn.id, call_id=call_id))
    await db.flush()


async def deliver_connection(db, conn):
    from app.services.crm import sync
    if not sync.conn_settings(conn)["log_calls"]:
        return
    await recover_calls(db, conn)
    now = dt.datetime.now(UTC)
    statuses = ["pending", "blocked"] if conn.status == "connected" else ["pending"]
    jobs = (await db.execute(select(CrmCallDelivery).where(
        CrmCallDelivery.connection_id == conn.id, CrmCallDelivery.status.in_(statuses),
        CrmCallDelivery.next_attempt_at <= now,
    ).order_by(CrmCallDelivery.next_attempt_at).limit(10))).scalars().all()
    for job in jobs:
        call = await db.get(CallLog, job.call_id)
        if not call or call.org_id != conn.org_id:
            job.status = "blocked"
            continue
        lead = await db.get(Lead, call.lead_id) if call.lead_id else None
        if lead and lead.org_id != conn.org_id:
            job.status = "blocked"
            continue
        agent = await db.get(Agent, call.agent_id) if call.agent_id else None
        job.attempts += 1
        try:
            await sync.push_call_to(db, conn, completed_call_data(call, lead, agent), raise_errors=True)
            job.status, job.sent_at = "sent", now
        except CrmError as exc:
            job.status = "blocked" if exc.status and 400 <= exc.status < 500 and exc.status not in (408, 429) else "pending"
            job.next_attempt_at = now + dt.timedelta(seconds=min(3600, 30 * 2 ** min(job.attempts, 7)))
            if job.status == "blocked":
                break
        except (ValueError, TypeError, KeyError):
            job.status = "blocked"
            break


async def poll_deliveries():
    from app.database import AsyncSessionLocal
    from app.services.crm.sync import log
    async with AsyncSessionLocal() as db:
        ids = list((await db.execute(select(CrmConnection.id).where(
            CrmConnection.provider == "blacksync_cloud"))).scalars().all())
    for connection_id in ids:
        async with AsyncSessionLocal() as db:
            # Serialize contact lookup/creation and receipt writes across workers.
            conn = (await db.execute(select(CrmConnection).where(CrmConnection.id == connection_id)
                                    .with_for_update(skip_locked=True))).scalar_one_or_none()
            if not conn:
                continue
            try:
                await deliver_connection(db, conn)
                await db.commit()
            except Exception as exc:
                await db.rollback()
                log.warning("blacksync_delivery_failed", connection=str(connection_id), error=type(exc).__name__)
