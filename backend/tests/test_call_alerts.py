import asyncio
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.call_log import CallLog
from app.models.lead import Lead
from app.models.call_alert import CallAlert
from app.services import call_alerts
from tests.test_accounts import _new_account, _login

@pytest.fixture
def setup(client, make_client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings,'resend_api_key','test')
    monkeypatch.setattr(settings,'app_url','https://blacksync.si')
    org,email=_new_account(client,name='Alert Realty')
    owner=_login(make_client,email)
    uid=owner.get('/api/auth/me').json()['user']['id']
    return org,owner,uid,f"/api/admin/orgs/{org['id']}/call-alerts"

def add_call(org, outcome='meeting_booked', call_type='outbound', when=None):
    async def go():
        async with AsyncSessionLocal() as db:
            lead=Lead(org_id=uuid.UUID(org['id']),name='James <Test>',phone='+14155550123',crm_refs={'followupboss':'11204'})
            db.add(lead);await db.flush()
            c=CallLog(org_id=lead.org_id,lead_id=lead.id,livekit_room_name='alerts-'+uuid.uuid4().hex,
                call_type=call_type,status='completed',outcome=outcome,summary='Interested in a visit. <script>unsafe</script>',
                agreed_meeting_time='Monday at 2 PM',started_at=when or datetime.now(timezone.utc),
                ended_at=when or datetime.now(timezone.utc),events_sent_at=when or datetime.now(timezone.utc))
            db.add(c);await db.commit();return str(c.id)
    return asyncio.run(go())

def test_manual_preview_does_not_send_and_confirm_deduplicates(client,setup,monkeypatch):
    org,owner,uid,base=setup
    cid=add_call(org)
    assert owner.get(base).status_code==403
    body={'call_ids':[cid],'user_ids':[uid]}
    sent=[]
    async def fake(*args,**kwargs):sent.append((args,kwargs));return True
    monkeypatch.setattr(call_alerts.email,'send_email',fake)
    r=client.post(base+'/preview',json=body)
    assert r.status_code==200,r.text
    assert r.json()['recipients'][0]['id']==uid and r.json()['items'][0]['call_id']==cid
    assert not sent
    assert client.post(base+'/notify',json=body).json()['queued']==1
    assert client.post(base+'/notify',json=body).json()['queued']==0
    assert not sent
    asyncio.run(call_alerts.tick());asyncio.run(call_alerts.tick())
    assert len(sent)==1
    args,kw=sent[0]
    assert kw['sender']=='BlackSync Campaigns <campaigns@blacksync.ai>' and kw['kind']=='call_alert'
    assert kw['idempotency_key'].startswith('call-alert-')
    assert '&lt;script&gt;' in args[2] and '<script>unsafe' not in args[2]
    rows=client.get(base+'/calls').json()['items']
    assert rows[0]['alerts'][0]['status']=='sent'

def test_direct_fub_link_uses_saved_contact_id(client,setup):
    org,owner,uid,base=setup
    body={'enabled':False,'outcomes':['meeting_booked'],'user_ids':[uid],'crm_base_url':'https://example.followupboss.com'}
    assert owner.put('/api/call-alerts',json=body).status_code==200
    cid=add_call(org)
    p=client.post(base+'/preview',json={'call_ids':[cid],'user_ids':[uid]}).json()
    assert p['items'][0]['crm_url']=='https://example.followupboss.com/2/people/view/11204'
    assert p['items'][0]['call_url'].endswith('/calls/'+cid)

@pytest.mark.parametrize('url',['http://example.followupboss.com','https://example.followupboss.com.evil.test','https://evil.test','https://user@example.followupboss.com'])
def test_crm_link_cannot_be_arbitrary_external_url(client,setup,url):
    _,owner,uid,_=setup
    assert owner.put('/api/call-alerts',json={'crm_base_url':url,'user_ids':[uid]}).status_code==400

def test_cross_account_recipient_and_call_rejected(client,setup,make_client):
    org,_,uid,base=setup
    foreign,email=_new_account(client)
    other=_login(make_client,email);other_uid=other.get('/api/auth/me').json()['user']['id']
    cid=add_call(org);foreign_call=add_call(foreign)
    assert client.post(base+'/notify',json={'call_ids':[cid],'user_ids':[other_uid]}).status_code==400
    assert client.post(base+'/notify',json={'call_ids':[foreign_call],'user_ids':[uid]}).status_code==404
    assert client.put(base,json={'enabled':True,'user_ids':[other_uid]}).status_code==400

def test_browser_test_cannot_be_notified(client,setup):
    org,_,uid,base=setup
    cid=add_call(org,call_type='web')
    assert client.post(base+'/notify',json={'call_ids':[cid],'user_ids':[uid]}).status_code==400
    assert not client.get(base+'/calls').json()['items']

def test_automatic_alerts_are_opt_in_filter_outcomes_and_exclude_history(client,setup,monkeypatch):
    from app.models.call_alert import CallAlertSettings
    org,owner,uid,base=setup
    old=datetime.now(timezone.utc)-timedelta(days=1)
    add_call(org,when=old)
    assert owner.get('/api/call-alerts').json()['enabled'] is False
    assert owner.put('/api/call-alerts',json={'enabled':True,'user_ids':[uid],'outcomes':['meeting_booked']}).status_code==200
    # Move activation back a few minutes; only this call is new enough.
    async def adjust():
        async with AsyncSessionLocal() as db:
            p=await db.get(CallAlertSettings,uuid.UUID(org['id']));p.enabled_at=datetime.now(timezone.utc)-timedelta(minutes=10);await db.commit()
    asyncio.run(adjust())
    recent=datetime.now(timezone.utc)-timedelta(minutes=2)
    good=add_call(org,when=recent);add_call(org,outcome='completed',when=recent)
    sent=[]
    async def fake(*a,**kw):sent.append(a);return True
    monkeypatch.setattr(call_alerts.email,'send_email',fake)
    asyncio.run(call_alerts.tick());asyncio.run(call_alerts.tick())
    assert len(sent)==1
    rows=client.get(base+'/calls').json()['items']
    assert next(r for r in rows if r['id']==good)['alerts'][0]['status']=='sent'
    assert sum(len(r['alerts']) for r in rows)==1

def test_personal_mute_cancels_queued_automatic_alert(client,setup):
    org,owner,uid,base=setup
    cid=add_call(org)
    owner.put('/api/call-alerts',json={'enabled':True,'user_ids':[uid],'outcomes':['meeting_booked']})
    async def queue():
        async with AsyncSessionLocal() as db:
            await call_alerts.enqueue(db,uuid.UUID(org['id']),[uuid.UUID(cid)],[uuid.UUID(uid)],automatic=True);await db.commit()
            return await db.scalar(select(CallAlert.id).where(CallAlert.call_id==uuid.UUID(cid)))
    key=asyncio.run(queue());assert owner.post('/api/call-alerts/mute').status_code==200
    asyncio.run(call_alerts.deliver(key))
    assert client.get(base+'/calls').json()['items'][0]['alerts'][0]['status']=='cancelled'

def test_failed_delivery_is_visible_and_retries_keep_same_key(client,setup,monkeypatch):
    org,_,uid,base=setup
    cid=add_call(org);client.post(base+'/notify',json={'call_ids':[cid],'user_ids':[uid]})
    keys=[]
    async def fake(*a,**kw):keys.append(kw['idempotency_key']);return len(keys)>1
    monkeypatch.setattr(call_alerts.email,'send_email',fake)
    asyncio.run(call_alerts.tick())
    assert client.get(base+'/calls').json()['items'][0]['alerts'][0]['status']=='retry'
    async def retry_now():
        async with AsyncSessionLocal() as db:
            row=(await db.execute(select(CallAlert).where(CallAlert.call_id==uuid.UUID(cid)))).scalar_one()
            row.next_at=datetime.now(timezone.utc)-timedelta(seconds=1);await db.commit()
    asyncio.run(retry_now());asyncio.run(call_alerts.tick())
    assert keys[0]==keys[1]
    assert client.get(base+'/calls').json()['items'][0]['alerts'][0]['status']=='sent'


def test_expired_uncertain_deliveries_are_not_resent(client,setup,monkeypatch):
    org,_,uid,base=setup
    cid=add_call(org);client.post(base+'/notify',json={'call_ids':[cid],'user_ids':[uid]})
    async def expire():
        async with AsyncSessionLocal() as db:
            row=(await db.execute(select(CallAlert).where(CallAlert.call_id==uuid.UUID(cid)))).scalar_one()
            row.status='sending';row.created_at=datetime.now(timezone.utc)-timedelta(hours=22)
            row.next_at=datetime.now(timezone.utc)-timedelta(minutes=10);await db.commit()
    asyncio.run(expire())
    sent=[]
    async def fake(*a,**kw):sent.append(a);return True
    monkeypatch.setattr(call_alerts.email,'send_email',fake)
    asyncio.run(call_alerts.tick())
    assert not sent
    assert client.get(base+'/calls').json()['items'][0]['alerts'][0]['status']=='failed'


def test_manual_retry_preserves_email_body_and_resend_key(client,setup,monkeypatch):
    org,_,uid,base=setup
    cid=add_call(org);client.post(base+'/notify',json={'call_ids':[cid],'user_ids':[uid]})
    deliveries=[]
    async def fake(*args,**kw):deliveries.append((args,kw));return len(deliveries)>1
    monkeypatch.setattr(call_alerts.email,'send_email',fake)
    asyncio.run(call_alerts.tick())
    row=client.get(base+'/calls').json()['items'][0]['alerts'][0]
    async def revise():
        async with AsyncSessionLocal() as db:
            c=await db.get(CallLog,uuid.UUID(cid));c.summary='Changed after the first delivery attempt';await db.commit()
    asyncio.run(revise())
    assert client.post(base+f"/deliveries/{row['id']}/retry").status_code==200
    asyncio.run(call_alerts.tick())
    assert deliveries[0]==deliveries[1]


def test_email_service_passes_resend_idempotency_header(setup,monkeypatch):
    import httpx
    from app.services import email
    captured=[]
    async def record(*args):pass
    def handler(request):captured.append(request);return httpx.Response(200,json={'id':'test-email-id'})
    factory=httpx.AsyncClient
    monkeypatch.setattr(email.httpx,'AsyncClient',lambda **kw:factory(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(email,'_record',record)
    assert asyncio.run(email.send_email('recipient@example.test','Test','<p>Test</p>',idempotency_key='stable-key'))
    assert captured[0].headers['Idempotency-Key']=='stable-key'
