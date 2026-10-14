"""Daily activity heat map: metric definitions, tenancy, time zones and the call-log day filter."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from tests.test_accounts import _login, _new_account


def _run(coro):
    return asyncio.run(coro)


def _add(*rows):
    from app.database import AsyncSessionLocal

    async def go():
        async with AsyncSessionLocal() as db:
            for r in rows:
                db.add(r)
            await db.commit()

    _run(go())


def _call(org_id, agent_id, started_at, *, outcome="completed", answered=True, duration=60,
          call_type="outbound", transcript=None):
    from app.models.call_log import CallLog
    return CallLog(
        id=uuid.uuid4(), org_id=org_id, agent_id=agent_id, call_type=call_type, livekit_room_name="r",
        status="completed", outcome=outcome, started_at=started_at,
        answered_at=started_at + timedelta(seconds=5) if answered else None,
        duration_seconds=duration, ended_at=started_at + timedelta(seconds=duration or 1),
        transcript=transcript,
    )


def _usage(org_id, call_id, amount, created_at):
    from app.models.account import CreditTransaction
    return CreditTransaction(org_id=org_id, amount=-amount, balance_after=0, kind="usage",
                             note="call", call_id=call_id, created_at=created_at)


def _owner(client, make_client, name="Activity Co"):
    org, email = _new_account(client, name=name)
    owner = _login(make_client, email)
    org_id = uuid.UUID(owner.get("/api/auth/me").json()["org"]["id"])
    a1 = owner.post("/api/agents/", json={"template": "sales_sdr"}).json()
    a2 = owner.post("/api/agents/", json={"template": "receptionist"}).json()
    return owner, org_id, a1, a2


def _day(base_days_ago: int, hour: int = 15, minute: int = 0):
    """A UTC time `base_days_ago` days back — safely inside every range whatever the clock says."""
    d = (datetime.now(timezone.utc) - timedelta(days=base_days_ago)).date()
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc)


def _by_date(body):
    return {d["date"]: d for d in body["days"]}


def test_empty_org_has_no_days(client, make_client):
    owner, *_ = _owner(client, make_client, "Empty Co")
    r = owner.get("/api/activity/daily?metric=calls&range=30d")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["days"] == [] and body["totals"]["value"] == 0
    assert body["timezone"] == "America/New_York" and body["metric_available"] is True
    assert body["agent"] is None


def test_validation(client, make_client):
    owner, *_ = _owner(client, make_client, "Validate Co")
    assert owner.get("/api/activity/daily?metric=bogus").status_code == 422
    assert owner.get("/api/activity/daily?range=7d").status_code == 422
    assert owner.get("/api/activity/daily?agent_id=not-a-uuid").status_code == 422
    assert owner.get(f"/api/activity/daily?agent_id={uuid.uuid4()}").status_code == 404
    assert owner.get("/api/activity/daily?agent_id=").status_code == 200
    body = owner.get("/api/activity/daily?range=12m").json()
    start, end = datetime.fromisoformat(body["start"]), datetime.fromisoformat(body["end"])
    assert (end - start).days == 364
    body = owner.get("/api/activity/daily?range=30d").json()
    assert (datetime.fromisoformat(body["end"]) - datetime.fromisoformat(body["start"])).days == 29


def test_metrics_per_day_and_agent_filter(client, make_client):
    owner, org_id, a1, a2 = _owner(client, make_client)
    A1, A2 = uuid.UUID(a1["id"]), uuid.UUID(a2["id"])
    t = _day(5)  # 15:00 UTC = 11:00 Eastern, same calendar day
    transfer_tool = [{"role": "user", "text": "hi"}, {"role": "tool", "tool": "transfer_call", "args": {}}]
    booked = _call(org_id, A1, t, outcome="meeting_booked")
    rows = [
        booked,
        _call(org_id, A1, t + timedelta(minutes=5), outcome="no_answer", answered=False, duration=0),
        _call(org_id, A1, t + timedelta(minutes=6), outcome="voicemail", answered=False, duration=25),  # talk time → connected
        _call(org_id, A2, t + timedelta(minutes=7), outcome="transferred", transcript=transfer_tool),
        # Marked "transferred" without the transfer tool ever running: not a real hand-off.
        _call(org_id, A2, t + timedelta(minutes=8), outcome="transferred", transcript=[{"role": "user", "text": "x"}]),
        # Browser test calls are not part of the activity map.
        _call(org_id, A1, t + timedelta(minutes=9), call_type="web", outcome="meeting_booked"),
    ]
    _add(*rows)
    _add(_usage(org_id, booked.id, 3, t + timedelta(minutes=2)), _usage(org_id, rows[3].id, 2, t + timedelta(minutes=9)))

    key = t.date().isoformat()
    d = _by_date(owner.get("/api/activity/daily?metric=calls&range=30d").json())[key]
    assert (d["calls"], d["connected"], d["appointments"], d["transfers"], d["credits"]) == (5, 4, 1, 1, 5)
    assert d["value"] == 5
    assert {a["name"]: a["value"] for a in d["agents"]} == {a1["name"]: 3, a2["name"]: 2}

    for metric, want in (("connected", 4), ("appointments", 1), ("transfers", 1), ("credits", 5)):
        body = owner.get(f"/api/activity/daily?metric={metric}&range=90d").json()
        assert body["metric"] == metric and body["metric_available"] is True
        assert _by_date(body)[key]["value"] == want, metric
        assert body["totals"]["value"] == want

    # Credits come from the ledger, not duration: the agent-1 day shows 3, agent-2 shows 2.
    body = owner.get(f"/api/activity/daily?metric=credits&range=12m&agent_id={A1}").json()
    assert body["agent"] == {"id": str(A1), "name": a1["name"]}
    d = _by_date(body)[key]
    assert (d["value"], d["calls"], d["appointments"], d["transfers"]) == (3, 3, 1, 0)
    body = owner.get(f"/api/activity/daily?metric=transfers&range=12m&agent_id={A2}").json()
    assert _by_date(body)[key]["value"] == 1 and _by_date(body)[key]["calls"] == 2


def test_tenant_isolation(client, make_client):
    owner1, org1, a1, _ = _owner(client, make_client, "Tenant One")
    owner2, org2, b1, _ = _owner(client, make_client, "Tenant Two")
    t = _day(3)
    other = _call(org2, uuid.UUID(b1["id"]), t, outcome="meeting_booked")
    _add(other, _usage(org2, other.id, 7, t))
    _add(_call(org1, uuid.UUID(a1["id"]), t))

    body = owner1.get("/api/activity/daily?metric=calls&range=30d").json()
    assert body["totals"]["calls"] == 1 and body["totals"]["appointments"] == 0 and body["totals"]["credits"] == 0
    # Another org's agent can't be used as a filter (and leaks nothing).
    assert owner1.get(f"/api/activity/daily?agent_id={b1['id']}").status_code == 404
    # The other org sees only its own.
    body2 = owner2.get("/api/activity/daily?metric=credits&range=30d").json()
    assert body2["totals"]["calls"] == 1 and body2["totals"]["credits"] == 7

    # A platform admin viewing the sub-account gets that account's numbers.
    assert client.post("/api/auth/switch-org", json={"org_id": str(org2)}).status_code == 200
    try:
        body3 = client.get("/api/activity/daily?metric=appointments&range=30d").json()
        assert body3["totals"]["value"] == 1 and body3["totals"]["calls"] == 1
    finally:
        client.post("/api/auth/switch-org", json={"org_id": None})


def test_timezone_boundary(client, make_client):
    owner, org_id, a1, _ = _owner(client, make_client, "Late Night Co")
    t = _day(6, hour=3, minute=30)  # 03:30 UTC = 23:30 the previous evening in New York
    call = _call(org_id, uuid.UUID(a1["id"]), t)
    _add(call)
    utc_day = t.date().isoformat()
    ny_day = (t.date() - timedelta(days=1)).isoformat()

    days = _by_date(owner.get("/api/activity/daily?range=30d").json())
    assert list(days) == [ny_day]

    # The call log's day filter uses the same boundaries.
    assert owner.get(f"/api/calls/?date={ny_day}").json()["total"] == 1
    assert owner.get(f"/api/calls/?date={utc_day}").json()["total"] == 0
    assert owner.get("/api/calls/?date=not-a-date").status_code == 422

    # Switching the org to UTC moves the call onto the UTC date.
    r = owner.patch("/api/account/org", json={"timezone": "UTC"})
    assert r.status_code == 200 and r.json()["timezone"] == "UTC"
    body = owner.get("/api/activity/daily?range=30d").json()
    assert body["timezone"] == "UTC" and list(_by_date(body)) == [utc_day]
    assert owner.get(f"/api/calls/?date={utc_day}").json()["total"] == 1
    assert owner.get(f"/api/calls/?date={ny_day}").json()["total"] == 0

    assert owner.patch("/api/account/org", json={"timezone": "Mars/Olympus"}).status_code == 400
    assert owner.get("/api/auth/me").json()["org"]["timezone"] == "UTC"
    # Renaming alone leaves the time zone alone.
    assert owner.patch("/api/account/org", json={"name": "Late Night LLC"}).json()["timezone"] == "UTC"


def test_unlimited_account_credits_unavailable(client):
    # The super-admin's house account has unlimited calling: no ledger usage, so no fake zeros.
    body = client.get("/api/activity/daily?metric=credits&range=30d").json()
    if body["totals"]["credits"] == 0:
        assert body["metric_available"] is False and body["note"]
        assert body["credits_tracked"] is False


def test_call_log_sort_by_duration(client, make_client):
    owner, org_id, a1, _ = _owner(client, make_client, name="Sort Co")
    A1, t = uuid.UUID(a1["id"]), _day(2)
    _add(_call(org_id, A1, t, duration=30), _call(org_id, A1, t + timedelta(minutes=1), duration=120),
         _call(org_id, A1, t + timedelta(minutes=2), outcome="no_answer", answered=False, duration=None))
    dur = lambda q: [c["duration_seconds"] for c in owner.get(f"/api/calls/?{q}").json()["items"]]  # noqa: E731
    assert dur("sort=longest") == [120, 30, None]
    assert dur("sort=shortest") == [None, 30, 120]
    assert dur("") == [None, 120, 30]  # newest first
    assert owner.get("/api/calls/?sort=bogus").status_code == 422
