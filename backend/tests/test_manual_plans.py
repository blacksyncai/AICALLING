"""Plans an admin sets by hand for customers who paid outside the app."""

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

from app.database import AsyncSessionLocal
from app.models.account import Organization
from app.models.billing import BillingSubscription
from app.services.billing import manual_plans
from tests.test_phone_numbers import _account


def test_month_math_keeps_the_start_day():
    assert manual_plans.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert manual_plans.add_months(date(2026, 1, 31), 2) == date(2026, 3, 31)
    assert manual_plans.add_months(date(2026, 11, 15), 2) == date(2027, 1, 15)
    assert manual_plans.cycle(date(2026, 9, 10), date(2026, 11, 7)) == (date(2026, 10, 10), date(2026, 11, 10))
    assert manual_plans.cycle(date(2026, 11, 7), date(2026, 11, 7)) == (date(2026, 11, 7), date(2026, 12, 7))


def _org(org_id):
    async def go():
        async with AsyncSessionLocal() as db:
            org = await db.get(Organization, uuid.UUID(org_id))
            row = await db.get(BillingSubscription, uuid.UUID(org_id))
            return org.credits_balance, row
    return asyncio.run(go())


def _renew(at):
    async def go():
        async with AsyncSessionLocal() as db:
            return await manual_plans.renew_due(db, at)
    return asyncio.run(go())


def test_admin_sets_a_plan_with_a_past_start_and_it_renews_monthly(client, make_client):
    org, owner = _account(client, make_client, "Payment Link Co")
    today = datetime.now(timezone.utc).date()
    start = manual_plans.add_months(today, -1) - timedelta(days=3)  # started a month and a bit ago
    assert owner.post(f"/api/admin/billing/orgs/{org['id']}/manual-plan",
                      json={"plan_key": "growth", "start_date": start.isoformat()}).status_code in (401, 403)
    r = client.post(f"/api/admin/billing/orgs/{org['id']}/manual-plan",
                    json={"plan_key": "growth", "start_date": start.isoformat(), "note": "Paid by Stripe link"})
    assert r.status_code == 200, r.text
    balance, row = _org(org["id"])
    assert row.plan_key == "growth" and row.status == "active" and balance == 400  # the current cycle's credits
    end = manual_plans.cycle(start, today)[1]
    assert r.json()["next_renewal"].startswith(end.isoformat())
    # The account's own limits follow the plan.
    ent = owner.get("/api/billing/entitlements").json()
    assert ent["plan"] == "growth" and ent["limits"]["agents"] == 5

    # Nothing happens before the renewal day; on it, a new cycle's credits replace the old ones.
    assert _renew(datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc) - timedelta(hours=1)) == 0
    assert _renew(datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=1)) == 1
    balance, row = _org(org["id"])
    assert balance == 400 and row.current_period_end.date() == manual_plans.add_months(end, 1)
    # Customers can't change it through Stripe.
    assert owner.post("/api/billing/plans/solo/preview").status_code in (404, 405, 409)


def test_future_start_and_custom_credits_and_cancel(client, make_client):
    org, _ = _account(client, make_client, "Future Start Co")
    start = datetime.now(timezone.utc).date() + timedelta(days=5)
    r = client.post(f"/api/admin/billing/orgs/{org['id']}/manual-plan",
                    json={"plan_key": "solo", "start_date": start.isoformat(), "credits_per_month": 250})
    assert r.status_code == 200, r.text
    balance, row = _org(org["id"])
    assert balance == 0 and row.current_period_end.date() == start  # credits arrive on the start date
    at = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc) + timedelta(minutes=5)
    assert _renew(at) == 1
    balance, row = _org(org["id"])
    assert balance == 250 and row.current_period_end.date() == manual_plans.add_months(start, 1)

    r = client.delete(f"/api/admin/billing/orgs/{org['id']}/manual-plan")
    assert r.status_code == 200 and r.json()["cancel_at_period_end"] is True
    _renew(datetime.combine(manual_plans.add_months(start, 1), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=1))
    _, row = _org(org["id"])
    assert row.status == "canceled"

    assert client.post(f"/api/admin/billing/orgs/{org['id']}/manual-plan",
                       json={"plan_key": "nope", "start_date": start.isoformat()}).status_code == 409
