import json
from types import SimpleNamespace

import httpx
import pytest

from app.config import settings
from app.services import signalwire, telephony
from tests.test_accounts import _new_account

REAL_CLIENT = httpx.AsyncClient
NUMBER = '+14155550123'


@pytest.fixture
def purchase_api(monkeypatch):
    for key, value in {'signalwire_space':'example.signalwire.com', 'signalwire_project_id':'project-test',
                       'signalwire_api_token':'secret', 'signalwire_sip_outbound_trunk_id':'ST_sw',
                       'twilio_account_sid':'AC_test', 'twilio_auth_token':'secret'}.items():
        monkeypatch.setattr(settings, key, value)
    state = SimpleNamespace(calls=[], allowed=[], status=200, route_failure=False)
    def handler(request):
        state.calls.append(request)
        assert request.url.host == 'example.signalwire.com'
        if state.status != 200:
            return httpx.Response(state.status, json={'error':'rejected'})
        if request.method == 'GET':
            assert request.url.params['areacode'] == '415'
            assert 'area_code' not in request.url.params
            return httpx.Response(200,json={'data':[
                {'e164':NUMBER,'national_number_formatted':'(415) 555-0123','capabilities':['voice'],'rate_center':'SF','region':'CA'},
                {'e164':'+14155550124','capabilities':['fax']} ]})
        if request.method == 'POST':
            assert json.loads(request.content) == {'number':NUMBER}
            return httpx.Response(200,json={'id':'PN-sw','number':NUMBER})
        return httpx.Response(204)
    monkeypatch.setattr(signalwire.httpx,'AsyncClient',lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))
    async def routing(): pass
    async def allow(number):
        if state.route_failure:
            raise signalwire.SignalWireError('Routing unavailable')
        state.allowed.append(number)
    monkeypatch.setattr(signalwire,'ensure_dynamic_routing',routing)
    monkeypatch.setattr(signalwire,'allow_number',allow)
    return state


def test_signalwire_primary_explicit_twilio_backup(purchase_api):
    assert telephony.purchase_carriers() == ['signalwire','twilio']
    assert telephony.purchase_carrier() == 'signalwire'
    assert telephony.purchase_carrier('twilio') == 'twilio'
    with pytest.raises(telephony.TelephonyError): telephony.purchase_carrier('unknown')


def test_admin_search_purchase_assign_and_release(client,purchase_api):
    org,_ = _new_account(client,name='SW purchase')
    result = client.get('/api/admin/phone-numbers/available?area_code=415')
    assert result.status_code == 200,result.text
    assert [n['number'] for n in result.json()['numbers']] == [NUMBER]
    result = client.post(f"/api/admin/orgs/{org['id']}/phone-numbers",json={'mode':'purchase','number':NUMBER,'carrier':'signalwire'})
    assert result.status_code == 201,result.text
    row = result.json()
    assert row['carrier'] == 'signalwire' and row['source'] == 'purchased'
    assert purchase_api.allowed == [NUMBER]
    assert client.post(f"/api/admin/orgs/{org['id']}/phone-numbers",json={'mode':'purchase','number':NUMBER}).status_code == 502
    assert sum(r.method == 'POST' for r in purchase_api.calls) == 1
    assert client.delete(f"/api/admin/phone-numbers/{row['id']}?return_to_twilio=true").status_code == 200
    assert purchase_api.calls[-1].method == 'DELETE'
    assert purchase_api.calls[-1].url.path.endswith('/phone_numbers/PN-sw')


def test_failed_routing_compensates_and_does_not_assign(client,purchase_api):
    org,_ = _new_account(client,name='SW routing failure')
    purchase_api.route_failure = True
    result = client.post(f"/api/admin/orgs/{org['id']}/phone-numbers",json={'mode':'purchase','number':NUMBER})
    assert result.status_code == 502,result.text
    assert client.get(f"/api/admin/orgs/{org['id']}/phone-numbers").json()['numbers'] == []
    assert [r.method for r in purchase_api.calls] == ['POST','DELETE']


@pytest.mark.asyncio
async def test_rejection_does_not_retry_or_fall_back(purchase_api):
    purchase_api.status = 403
    with pytest.raises(signalwire.SignalWireError): await signalwire.buy(NUMBER)
    assert len(purchase_api.calls) == 1


@pytest.mark.asyncio
async def test_bad_search_rejected_without_network(purchase_api):
    with pytest.raises(signalwire.SignalWireError): await signalwire.search_available('41')
    assert not purchase_api.calls


@pytest.mark.asyncio
async def test_checkout_keeps_selected_carrier(monkeypatch):
    import uuid
    from app.services.billing import purchases
    captured = {}
    async def price(key): return 'price_phone'
    async def customer(db,org): return 'cus_test'
    async def checkout(**kwargs):
        captured.update(kwargs)
        return {'url':'https://checkout.test/phone'}
    monkeypatch.setattr(purchases.catalog,'sellable_price',price)
    monkeypatch.setattr(purchases,'ensure_customer',customer)
    monkeypatch.setattr(purchases.stripe_api,'create_checkout_session',checkout)
    org = SimpleNamespace(id=uuid.uuid4())
    await purchases.checkout_phone_number(None, org, uuid.uuid4(), NUMBER, carrier='signalwire')
    assert captured['metadata']['carrier'] == 'signalwire'
    assert captured['subscription_data']['metadata']['carrier'] == 'signalwire'
    assert 'signalwire' in captured['idempotency_key']


@pytest.mark.asyncio
async def test_signalwire_checkout_failure_never_buys_alternate(monkeypatch):
    import uuid
    from app.services.billing import purchases
    class DB:
        async def execute(self, query): return SimpleNamespace(scalar_one_or_none=lambda:None)
    calls = []
    async def buy(db,org,number,*,carrier):
        calls.append((number,carrier))
        raise telephony.TelephonyError("Couldn't confirm purchase")
    async def search(*args,**kwargs):
        pytest.fail('Must not select alternate numbers after an uncertain purchase')
    monkeypatch.setattr(telephony,'purchase',buy)
    monkeypatch.setattr(telephony,'search_available',search)
    with pytest.raises(RuntimeError):
        await purchases.provision_number(DB(),uuid.uuid4(),NUMBER,'sub_test',carrier='signalwire')
    assert calls == [(NUMBER,'signalwire')]


def test_customer_signalwire_without_twilio_keeps_checkout_choice(client, make_client, purchase_api, monkeypatch):
    from app.services.billing import purchases
    from tests.test_accounts import _login
    monkeypatch.setattr(settings,'twilio_account_sid','')
    monkeypatch.setattr(settings,'twilio_auth_token','')
    org,email = _new_account(client,name='SW customer checkout')
    owner = _login(make_client,email)
    captured = []
    async def checkout(db,org,user,number,*,carrier):
        captured.append((number,carrier))
        return 'https://checkout.test/phone'
    monkeypatch.setattr(purchases,'checkout_phone_number',checkout)
    client.patch('/api/admin/telephony/settings',json={'self_serve_numbers':True})
    try:
        data = owner.get('/api/phone-numbers').json()
        assert data['self_serve'] and data['purchase_carriers'] == ['signalwire']
        result = owner.get('/api/phone-numbers/available?area_code=415&carrier=signalwire')
        assert result.status_code == 200,result.text
        result = owner.post('/api/phone-numbers/purchase',json={'number':NUMBER,'carrier':'signalwire','confirm_charge':True})
        assert result.status_code == 200,result.text
        assert captured == [(NUMBER,'signalwire')]
        assert not any(r.method == 'POST' for r in purchase_api.calls) # wait for confirmed payment
    finally:
        client.patch('/api/admin/telephony/settings',json={'self_serve_numbers':False})
