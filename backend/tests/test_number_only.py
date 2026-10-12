"""A phone number bought on its own ($3.50/mo, no plan): checkout → bought on payment → released on cancel."""

from app.config import settings
from tests.test_billing import _hook, stripe  # noqa: F401  (fixture)
from tests.test_phone_numbers import _account, _num, twilio  # noqa: F401  (fixture)


def test_number_only_subscription_lifecycle(client, make_client, stripe, twilio, monkeypatch):  # noqa: F811
    client.patch("/api/admin/telephony/settings", json={"self_serve_numbers": True, "max_numbers_per_org": 3})
    try:
        org, owner = _account(client, make_client, "Number Only Co")
        n = _num()
        r = owner.post("/api/phone-numbers/purchase", json={"number": n})
        assert r.status_code == 200, r.text
        assert r.json()["checkout_url"]
        sess = stripe.sessions[-1]
        assert sess["mode"] == "subscription" and sess["metadata"]["purchase_type"] == "phone_number"
        assert sess["metadata"]["number"] == n and sess["subscription_data"]["metadata"]["number"] == n
        assert owner.get("/api/phone-numbers").json()["numbers"] == []

        sub = {"id": "sub_num_1", "customer": sess["customer"], "status": "active", "metadata": sess["metadata"],
               "items": {"data": [{"id": "si_1", "quantity": 1, "price": {"id": "price_phone"}}]}}
        stripe.subs["sub_num_1"] = sub
        done = {"id": "cs_num_1", "mode": "subscription", "payment_status": "paid", "customer": sess["customer"],
                "subscription": "sub_num_1", "metadata": sess["metadata"]}
        assert _hook(client, "checkout.session.completed", done).status_code == 200
        _hook(client, "checkout.session.completed", done)  # a retry doesn't buy a second number
        nums = owner.get("/api/phone-numbers").json()["numbers"]
        assert [x["number"] for x in nums] == [n]

        # It's not a plan: no subscription on the billing overview, no included credits on its invoice.
        _hook(client, "invoice.paid", {"id": "in_num_1", "customer": sess["customer"], "subscription": "sub_num_1",
                                       "billing_reason": "subscription_create"})
        overview = owner.get("/api/billing/overview").json()
        assert not (overview.get("subscription") or {}).get("plan_key")
        assert overview["credits"]["balance"] == 0

        # Cancelling the subscription releases the number.
        assert _hook(client, "customer.subscription.deleted", {**sub, "status": "canceled"}).status_code == 200
        assert owner.get("/api/phone-numbers").json()["numbers"] == []
    finally:
        client.patch("/api/admin/telephony/settings", json={"self_serve_numbers": False, "max_numbers_per_org": 5})
