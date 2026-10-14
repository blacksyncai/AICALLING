"""
One-off, read-only check that calls we report as logged in Follow Up Boss are really there.

For each Follow Up Boss connection it reads the account the key belongs to, the push settings, today's push
results, and — for the people we last logged calls on — the calls Follow Up Boss actually has. Results go to
the server log (ids, counts and times only; no names, numbers or keys). Nothing is written anywhere.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select

log = structlog.get_logger(__name__)


async def verify_fub() -> None:
    from app.database import AsyncSessionLocal
    from app.models.call_log import CallLog
    from app.models.crm import CrmConnection, CrmSyncLog
    from app.services.crm.sync import conn_settings, http_for

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    async with AsyncSessionLocal() as db:
        conns = (await db.execute(select(CrmConnection).where(CrmConnection.provider == "followupboss"))).scalars().all()
        for conn in conns:
            cfg = conn_settings(conn)
            calls = (await db.execute(select(func.count()).select_from(CallLog).where(
                CallLog.org_id == conn.org_id, CallLog.started_at >= since))).scalar_one()
            rows = (await db.execute(select(CrmSyncLog).where(
                CrmSyncLog.connection_id == conn.id, CrmSyncLog.kind == "call", CrmSyncLog.created_at >= since)
                .order_by(CrmSyncLog.created_at.desc()))).scalars().all()
            skipped = sum(1 for r in rows if r.message.startswith("Skipped"))
            errors = sum(1 for r in rows if r.status == "error")
            log.info("crm_verify_conn", org=str(conn.org_id), status=conn.status, method=conn.method,
                     calls_24h=calls, pushed_24h=len(rows) - skipped - errors, skipped_24h=skipped, errors_24h=errors,
                     log_calls=cfg["log_calls"], only_connected=cfg["only_connected"], min_seconds=cfg.get("min_seconds"),
                     only_outcomes=cfg.get("only_outcomes"), skip_outcomes=cfg.get("skip_outcomes"),
                     create_contacts=cfg["create_contacts"])
            if errors:
                last = next(r for r in rows if r.status == "error")
                log.info("crm_verify_last_error", org=str(conn.org_id), message=last.message[-160:])
            try:
                _, http = http_for(conn)
                me = await http.request("GET", "/v1/me")
                acct = me.get("account") if isinstance(me.get("account"), dict) else {}
                log.info("crm_verify_account", org=str(conn.org_id), key_user_id=me.get("id"), key_user_role=me.get("role"),
                         account_id=acct.get("id") or me.get("accountId"), subdomain=acct.get("subdomain") or acct.get("domain"))
                for r in [r for r in rows if r.external_id][:4]:
                    found = await http.request("GET", "/v1/calls", params={"personId": int(r.external_id), "limit": 5,
                                                                           "sort": "-created"})
                    items = found.get("calls") or []
                    ours = [c for c in items if "BlackSync" in (c.get("note") or "")]
                    person = await http.request("GET", f"/v1/people/{int(r.external_id)}",
                                                params={"fields": "id,stage,assignedUserId,lastActivity"})
                    log.info("crm_verify_person", org=str(conn.org_id), person_id=r.external_id,
                             pushed_at=r.created_at.isoformat() if r.created_at else None,
                             fub_calls=len(items), blacksync_calls=len(ours),
                             newest_created=(ours[0].get("created") if ours else None),
                             newest_user_id=(ours[0].get("userId") if ours else None),
                             stage=person.get("stage"), assigned_user_id=person.get("assignedUserId"),
                             last_activity=person.get("lastActivity"))
            except Exception as exc:  # read-only check: never let it affect anything else
                log.warning("crm_verify_failed", org=str(conn.org_id), error=str(exc)[:200])


_TASKS: set = set()


def start_once(delay: float = 30.0) -> asyncio.Task:
    async def run():
        await asyncio.sleep(delay)
        try:
            await verify_fub()
        except Exception as exc:
            log.warning("crm_verify_failed", error=str(exc)[:200])
    task = asyncio.create_task(run())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return task
