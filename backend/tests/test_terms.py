"""Terms of Service: required and recorded on the server before a first subscription's checkout."""

import uuid

from app.services.billing.terms import TERMS_VERSION
from tests.test_billing import _account, stripe  # noqa: F401  (fixture)


def _rows(org_id):
    import asyncio

    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.terms import TermsAcceptance

    async def go():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(TermsAcceptance).where(TermsAcceptance.org_id == uuid.UUID(org_id)))).scalars().all()

    return asyncio.run(go())


def test_checkout_needs_terms_and_records_them(client, make_client, stripe):  # noqa: F811
    org, c = _account(client, make_client, "Terms Co")
    # No tick, or a stale version: no checkout session is created.
    r = c.post("/api/billing/plans/solo/checkout")
    assert r.status_code == 400 and "Terms of Service" in r.text
    r = c.post("/api/billing/plans/solo/checkout", json={"accept_terms": False, "terms_version": TERMS_VERSION})
    assert r.status_code == 400
    r = c.post("/api/billing/plans/solo/checkout", json={"accept_terms": True, "terms_version": "2020-01-01"})
    assert r.status_code == 409
    assert not stripe.sessions and not _rows(org["id"])

    r = c.post("/api/billing/plans/solo/checkout", json={"accept_terms": True, "terms_version": TERMS_VERSION})
    assert r.status_code == 200 and r.json()["url"]
    row = _rows(org["id"])[0]
    me = c.get("/api/auth/me").json()
    assert str(row.user_id) == me["user"]["id"] and row.terms_version == TERMS_VERSION and row.accepted_at
    assert (row.plan_key, row.billing_interval, row.amount_cents, row.context) == ("solo", "month", 9800, "checkout")
    meta = stripe.sessions[-1]["metadata"]
    assert meta["terms_acceptance_id"] == str(row.id) and meta["terms_version"] == TERMS_VERSION

    status = c.get("/api/billing/terms").json()
    assert status["version"] == TERMS_VERSION and status["accepted_version"] == TERMS_VERSION
    assert status["renewal_needed"] is False


def test_unbuyable_plans_record_nothing(client, make_client, stripe):  # noqa: F811
    org, c = _account(client, make_client, "Terms Managed Co")
    r = c.post("/api/billing/plans/managed/checkout", json={"accept_terms": True, "terms_version": TERMS_VERSION})
    assert r.status_code == 409 and not _rows(org["id"])


def test_renewal_only_after_a_material_change(client, make_client, monkeypatch):
    from app.services.billing import terms

    org, c = _account(client, make_client, "Terms Renewal Co")
    assert c.get("/api/billing/terms").json()["renewal_needed"] is False  # not subscribed: nothing to renew
    monkeypatch.setattr(terms, "REACCEPT_FROM", "2099-01-01")
    assert c.get("/api/billing/terms").json()["renewal_needed"] is False  # still only for live subscribers
    assert c.post("/api/billing/terms/accept", json={"terms_version": "old"}).status_code == 409
    assert c.post("/api/billing/terms/accept", json={"terms_version": TERMS_VERSION}).json()["ok"]
    assert _rows(org["id"])[0].context == "renewal"


def test_web_and_server_agree_on_the_terms_version():
    import pathlib
    import re

    web = (pathlib.Path(__file__).resolve().parents[2] / "web/src/lib/terms.ts").read_text()
    assert re.search(r'TERMS_VERSION = "([^"]+)"', web).group(1) == TERMS_VERSION
