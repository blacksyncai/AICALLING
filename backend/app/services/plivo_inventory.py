"""Reconcile authoritative Plivo removals without treating outages as deletions."""
import asyncio
from datetime import datetime, timedelta, timezone
import structlog
from sqlalchemy import select, or_
from app.config import settings
from app.database import AsyncSessionLocal
from app.models.billing import PhoneNumber
from app.models.campaign import Campaign
from app.services import plivo, telephony

log = structlog.get_logger(__name__)
INTERVAL = 300
CONFIRM_AFTER = timedelta(seconds=60)
PURCHASE_GRACE = timedelta(minutes=2)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


async def cleanup(db, row):
    # Idempotent and retried after restart; never issue a Plivo DELETE here.
    from app.services.billing.subscriptions import sync_phone_quantity
    from app.services.billing import stripe_api
    if row.stripe_subscription_id:
        await stripe_api.set_cancel_at_period_end(row.stripe_subscription_id, True)
    await sync_phone_quantity(db, row.org_id)
    if not settings.livekit_sip_plivo_trunk_id:
        raise telephony.TelephonyError("Plivo media cleanup is not configured.")
    await telephony._livekit_numbers(remove=[row.number], trunk_id=settings.livekit_sip_plivo_trunk_id, strict=True)
    row.provider_cleanup_pending = False
    await db.commit()


async def detach(db, row):
    campaigns = (await db.scalars(select(Campaign).where(Campaign.org_id == row.org_id))).all()
    for campaign in campaigns:
        if campaign.phone_number_id == row.id:
            campaign.phone_number_id = None
            if campaign.status == 'running':
                campaign.status, campaign.pause_reason = 'paused', 'number_released'
        if row.number in (campaign.caller_number_pool or []):
            campaign.caller_number_pool = [n for n in campaign.caller_number_pool if n != row.number]
            campaign.caller_rotation_cursor = 0
            if campaign.number_rotation_enabled and len(campaign.caller_number_pool) < 2 and campaign.status == 'running':
                campaign.status, campaign.pause_reason = 'paused', 'number_released'
    row.inbound_agent_id, row.inbound_campaign_id = None, None
    row.provider_cleanup_pending = True
    await telephony.release(db, row, return_to_twilio=False, sync_media=False)
    log.info('plivo_inventory_number_retired', number_id=str(row.id), org_id=str(row.org_id))


async def sweep():
    if not settings.plivo_auth_id or not settings.plivo_auth_token:
        return 0
    # Complete successful pagination is a prerequisite before inspecting any absence.
    inventory = await plivo.inventory_numbers()
    now = datetime.now(timezone.utc)
    retired = 0
    async with AsyncSessionLocal() as db:
        ids = (await db.scalars(select(PhoneNumber.id).where(PhoneNumber.carrier == 'plivo',
            or_(PhoneNumber.status == 'active', PhoneNumber.provider_cleanup_pending.is_(True))))).all()
        for key in ids:
            row = await db.scalar(select(PhoneNumber).where(PhoneNumber.id == key).with_for_update().execution_options(populate_existing=True))
            try:
                if row is None or row.carrier != 'plivo':
                    await db.rollback()
                    continue
                if row.status == 'active':
                    if row.number in inventory:
                        row.provider_missing_since = None
                        row.provider_check_account = settings.plivo_auth_id
                    elif row.provider_check_account and row.provider_check_account != settings.plivo_auth_id:
                        # A different project cannot establish that the owning project released this number.
                        row.provider_missing_since = None
                        log.warning('plivo_inventory_account_mismatch', number_id=str(row.id))
                    elif now - utc(row.created_at) >= PURCHASE_GRACE:
                        if await plivo.number_exists(row.number):
                            row.provider_missing_since = None
                        elif row.provider_check_account != settings.plivo_auth_id or not row.provider_missing_since:
                            row.provider_check_account = settings.plivo_auth_id
                            row.provider_missing_since = now
                        elif now - utc(row.provider_missing_since) >= CONFIRM_AFTER:
                            await detach(db, row)
                            retired += 1
                await db.commit()
                if row.status == 'released' and row.provider_cleanup_pending:
                    await cleanup(db, row)
            except Exception as exc:
                await db.rollback()
                log.warning('plivo_inventory_number_sync_failed', number_id=str(key), error=type(exc).__name__)
    return retired


def start_worker():
    async def loop():
        while True:
            try:
                await sweep()
            except Exception as exc:
                log.warning('plivo_inventory_sync_failed', error=type(exc).__name__)
            await asyncio.sleep(INTERVAL)
    return asyncio.create_task(loop())
