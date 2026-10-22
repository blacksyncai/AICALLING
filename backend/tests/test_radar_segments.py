import asyncio

from app.services.crm.providers import FollowUpBoss
from app.services.crm.radar import build_segment


class FakeHttp:
    def __init__(self, people):
        self.people, self.calls = people, []

    async def request(self, method, path, params=None, **kw):
        self.calls.append((path, params))
        return {"people": self.people, "_metadata": {}}


PEOPLE = [
    {"id": 1, "name": "Ann Cold", "phones": [{"value": "+14155550101"}], "assignedPondId": 7, "stage": "Lead",
     "created": "2026-01-02T00:00:00Z"},
    {"id": 2, "name": "Bob Other", "phones": [{"value": "+14155550102"}], "assignedPondId": 9, "stage": "Lead"},
    {"id": 3, "name": "No Phone", "phones": [], "assignedPondId": 7},
    {"id": 4, "name": "Trash Tim", "phones": [{"value": "+14155550104"}], "assignedPondId": 7, "stage": "Trash"},
]


def test_fub_pond_lists_everyone_in_it():
    http = FakeHttp(PEOPLE)
    signals = asyncio.run(FollowUpBoss().segment_signals(http, {}, "pond", "7"))
    assert [s.name for s in signals] == ["Ann Cold", "Trash Tim"]  # other pond and no-phone left out
    assert http.calls[0][1]["assignedPondId"] == "7"
    out = build_segment(signals, "Cold call (pond)", "Everyone in the pond")
    play = out["plays"][0]
    assert play["key"] == "segment" and play["count"] == 1  # Trash is do-not-call
    assert play["items"][0]["external_id"] == "1" and out["scanned"] == 2
