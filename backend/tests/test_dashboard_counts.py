"""The dashboard overview and the AI Calling Activity chart count calls the same way."""

from datetime import timedelta

from tests.test_accounts import _login, _new_account
from tests.test_meetings_analytics import _seed


def test_overview_matches_activity_chart(client, make_client):
    org, email = _new_account(client, name="Counts Co")
    c = _login(make_client, email)
    agent = c.get("/api/agents/").json()[0]
    _seed(org["id"], agent["id"], [
        {"call_type": "outbound", "duration_seconds": 60, "outcome": "meeting_booked"},
        {"call_type": "outbound", "duration_seconds": 0, "outcome": "no_answer"},
        {"call_type": None, "duration_seconds": 45, "outcome": "interested"},     # older row, no type
        {"call_type": "web", "duration_seconds": 120, "outcome": "meeting_booked"},  # browser test
        {"call_type": "web", "duration_seconds": 30, "outcome": "completed"},
        {"call_type": "outbound", "duration_seconds": 30, "ago": timedelta(days=40)},  # outside 30d
    ])
    ov = c.get("/api/calls/overview?days=30").json()
    assert ov["total_calls"] == 3 and ov["browser_tests"] == 2
    assert ov["connected_calls"] == 2 and ov["meetings_booked"] == 1 and ov["follow_ups"] == 1

    act = c.get("/api/activity/daily?metric=calls&range=12m").json()
    assert act["totals"]["calls"] == 4  # the 3 above + the one from 40 days ago; no browser tests
    act30 = sum(d["calls"] for d in act["days"] if d["date"] >= ov["calls_per_day"][0]["date"])
    assert act30 == ov["total_calls"]
