"""Pipeline board: contacts ordered by their longest call, with that length on each contact."""

import uuid
from datetime import datetime, timedelta, timezone

from tests.test_activity import _add, _call, _owner


def test_longest_call_first(client, make_client):
    owner, org_id, agent, _ = _owner(client, make_client, name="Longest Co")
    ids = {}
    for name in ("Short Sam", "Long Lee", "Never Called"):
        c = owner.post("/api/contacts", json={"name": name, "phone": f"+1415557{uuid.uuid4().int % 10000:04d}"}).json()
        ids[name] = c["id"]
    now = datetime.now(timezone.utc)
    rows = [_call(org_id, uuid.UUID(agent["id"]), now - timedelta(hours=h), duration=d) for h, d in ((3, 40), (2, 300), (1, 12))]
    rows[0].lead_id = rows[2].lead_id = uuid.UUID(ids["Short Sam"])  # 40s, then a later 12s call
    rows[1].lead_id = uuid.UUID(ids["Long Lee"])  # one 5-minute call
    _add(*rows)

    items = owner.get("/api/contacts", params={"sort": "longest_call"}).json()["items"]
    assert [i["name"] for i in items] == ["Long Lee", "Short Sam", "Never Called"]
    sam = items[1]
    assert sam["longest_call_seconds"] == 40 and sam["last_call_seconds"] == 12
    assert items[2]["longest_call_seconds"] is None
    # The default order is unchanged (newest contact first).
    assert owner.get("/api/contacts").json()["items"][0]["name"] == "Never Called"
