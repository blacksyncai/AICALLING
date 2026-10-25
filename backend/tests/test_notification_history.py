import asyncio
import uuid
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.call_alert import CallAlert
from app.models.email_message import EmailMessage
from app.services import call_alerts, email
from tests.test_call_alerts import setup, add_call


def queue(client, setup):
    org, owner, uid, base = setup
    cid = add_call(org)
    r = client.post(base+'/notify',json={'call_ids':[cid],'user_ids':[uid]})
    assert r.status_code == 200 and r.json()['queued'] == 1
    return cid, base


def test_history_links_exact_receipts_and_webhook_results(client,setup,monkeypatch):
    cid,base = queue(client,setup)
    async def send(*args,**kwargs): return True
    monkeypatch.setattr(call_alerts.email,'send_email',send)
    asyncio.run(call_alerts.tick())
    async def receipts():
        async with AsyncSessionLocal() as db:
            alert = await db.scalar(select(CallAlert).where(CallAlert.call_id==uuid.UUID(cid)))
            db.add_all([
                EmailMessage(resend_id='client-'+cid,notification_key=f'call-alert-{alert.id}',to_email='client@example.test',from_email='campaigns@blacksync.ai',subject='Same subject',kind='call_alert',status='delivered'),
                EmailMessage(resend_id='copy-'+cid,notification_key=f'call-alert-copy-{cid}',to_email='team@example.test',subject='Same subject',kind='call_alert_copy',status='bounced'),
                EmailMessage(resend_id='unrelated-'+cid,to_email='client@example.test',subject='Same subject',kind='call_alert',status='clicked')])
            await db.commit()
    asyncio.run(receipts())
    r=client.get(base+'/calls').json()['items'][0]
    assert r['alerts'][0]['status']=='sent'
    assert r['alerts'][0]['delivery']['status']=='delivered'
    assert r['alerts'][0]['delivery']['provider_id']=='client-'+cid
    assert r['internal_copy']['status']=='bounced'
    assert r['internal_copy']['delivery']['provider_id']=='copy-'+cid
    assert setup[1].get(base+'/calls').status_code==403


def test_copy_failure_is_visible_without_failing_or_resending_client(client,setup,monkeypatch):
    cid,base=queue(client,setup)
    sent=[]
    async def send(*args,**kw):
        sent.append(kw['kind'])
        return kw['kind']=='call_alert'
    monkeypatch.setattr(call_alerts.email,'send_email',send)
    asyncio.run(call_alerts.tick());asyncio.run(call_alerts.tick())
    r=client.get(base+'/calls').json()['items'][0]
    assert r['alerts'][0]['status']=='sent' and r['alerts'][0]['delivery'] is None
    assert r['internal_copy']['status']=='unconfirmed' and r['internal_copy']['error']
    assert sent.count('call_alert')==1 and sent.count('call_alert_copy')==1


def test_historical_sends_are_not_falsely_marked_delivered(client,setup):
    cid,base=queue(client,setup)
    async def old_send():
        async with AsyncSessionLocal() as db:
            a=await db.scalar(select(CallAlert).where(CallAlert.call_id==uuid.UUID(cid)))
            a.status='sent'
            await db.commit()
    asyncio.run(old_send())
    r=client.get(base+'/calls').json()['items'][0]
    assert r['alerts'][0]['delivery'] is None and r['internal_copy']['status']=='unknown'


def test_tracking_enriches_webhook_first_receipt_without_resetting_delivery(client):
    key='webhook-first-'+uuid.uuid4().hex
    async def go():
        async with AsyncSessionLocal() as db:
            db.add(EmailMessage(resend_id=key,to_email='client@example.test',kind='other',status='delivered'))
            await db.commit()
        await email._record(key,'client@example.test','Call update','call_alert',notification_key='call-alert-test',sender='campaigns@blacksync.ai')
        await email._record(key,'client@example.test','Call update','call_alert',notification_key='call-alert-test',sender='campaigns@blacksync.ai')
        async with AsyncSessionLocal() as db:
            rows=(await db.scalars(select(EmailMessage).where(EmailMessage.resend_id==key))).all()
            assert len(rows)==1 and rows[0].status=='delivered'
            assert rows[0].notification_key=='call-alert-test' and rows[0].from_email=='campaigns@blacksync.ai'
    asyncio.run(go())


def test_missing_provider_receipt_is_not_success(setup,monkeypatch):
    import httpx
    real=httpx.AsyncClient
    monkeypatch.setattr(email.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={})),**kw))
    assert asyncio.run(email.send_email('client@example.test','Update','<p>Update</p>')) is False


def test_real_sender_path_persists_both_receipts_in_history(client,setup,monkeypatch):
    import httpx
    cid,base=queue(client,setup)
    captured=[]
    def handler(request):
        captured.append(request)
        return httpx.Response(200,json={'id':f'{cid}-{len(captured)}'})
    real=httpx.AsyncClient
    monkeypatch.setattr(email.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    asyncio.run(call_alerts.tick())
    row=client.get(base+'/calls').json()['items'][0]
    assert row['alerts'][0]['delivery']['provider_id']==cid+'-1'
    assert row['internal_copy']['delivery']['provider_id']==cid+'-2'
    assert row['internal_copy']['status']=='sent'
    assert row['alerts'][0]['delivery']['from']=='BlackSync Campaigns <campaigns@blacksync.ai>'
    assert len(captured)==2
