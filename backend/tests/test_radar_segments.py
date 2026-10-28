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


class DealHttp:
    """FUB with one deal board: two active deals in stage 50, one archived, one in another stage."""
    PIPE = {"id": 9, "name": "Cold Call Verified Contacts",
            "stages": [{"id": 50, "name": "Verified Via Voicemail"}, {"id": 51, "name": "Verified Via AI convo"}]}
    DEALS = [
        {"id": 1, "pipelineId": 9, "stageId": 50, "status": "Active", "people": [{"id": 1, "name": "Ann Cold"}]},
        {"id": 2, "pipelineId": 9, "stageId": 50, "status": "Active", "people": [{"id": 2, "name": "Bob Other"}]},
        {"id": 3, "pipelineId": 9, "stageId": 50, "status": "Archived", "people": [{"id": 4, "name": "Trash Tim"}]},
        {"id": 4, "pipelineId": 9, "stageId": 51, "status": "Active", "people": [{"id": 3, "name": "No Phone"}]},
    ]

    def __init__(self):
        self.calls = []

    async def request(self, method, path, params=None, **kw):
        self.calls.append((path, params))
        if path == "/v1/pipelines":
            return {"pipelines": [self.PIPE], "_metadata": {}}
        if path == "/v1/pipelines/9":
            return self.PIPE
        if path == "/v1/deals":
            return {"deals": [d for d in self.DEALS if not params.get("stageId") or d["stageId"] == params["stageId"]],
                    "_metadata": {}}
        if path.startswith("/v1/people/"):
            return next(p for p in PEOPLE if p["id"] == int(path.rsplit("/", 1)[1]))
        return {path.rsplit("/", 1)[1]: [], "_metadata": {}}


def test_fub_deal_stage_is_a_list_option():
    opts = asyncio.run(FollowUpBoss().segment_options(DealHttp(), {}))
    assert {"value": "9:50", "label": "Cold Call Verified Contacts · Verified Via Voicemail"} in opts["deal"]


def test_fub_deal_stage_lists_the_people_on_active_deals():
    signals = asyncio.run(FollowUpBoss().segment_signals(DealHttp(), {}, "deal", "9:50"))
    assert [s.name for s in signals] == ["Ann Cold", "Bob Other"]  # archived deal and other stage left out


def test_assistant_deal_summary_counts_by_stage():
    from app.services.crm.fub_deals import summary
    out = asyncio.run(summary(DealHttp(), "9"))
    assert out["total_active_deals"] == 3
    assert out["by_stage"] == {"Verified Via Voicemail": 2, "Verified Via AI convo": 1}
    assert out["deals"][0]["people"][0]["name"] == "Ann Cold"


def test_list_deals_is_a_read_tool_for_fub():
    from app.services.crm.assistant import capabilities
    from app.services.crm.assistant_schema import CommandSpec, READS
    assert {"action": "list_deals", "writes": False} in capabilities("followupboss")
    assert "list_deals" in READS
    CommandSpec(action="list_deals", pipeline_id="9", stage_id="50")
