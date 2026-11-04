"""Contacts with several phone numbers: import, sequencing through them, and per-number results."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from app.models.campaign import Campaign
from app.models.lead import Lead
from app.routers.campaigns import _record_attempt, dial_eligibility
from app.services import lead_phones
from app.services.contacts import next_status, parse_contacts_csv

NUMS = ["+14155550301", "+14155550302", "+14155550303", "+14155550304"]
CSV = ("First Name,Last Name,Phone,Phone 2,Phone 3,Phone 4,City\n"
       "Max,Well,(415) 555-0301,415-555-0302,4155550303,4155550304,Austin\n")


def _lead(n=4, status="new"):
    lead = Lead(id=uuid.uuid4(), name="Max", phone=NUMS[0], status=status, attempts=0)
    lead.phones = lead_phones.build(NUMS[:n])
    return lead


def _campaign(**kw):
    return Campaign(id=uuid.uuid4(), name="Expireds", try_other_numbers=True, rounds_per_number=2,
                    number_gap_minutes=10, max_attempts=2, retry_delay_minutes=1440, **kw)


def _no_answer(lead, number):
    lead.status = next_status(lead.status, "no_answer") or lead.status
    lead_phones.mark(lead, number, "no_answer")


def _run(lead, campaign, calls, answer=None):
    """Dial while the contact is eligible, jumping the clock to each due time. Returns the numbers dialed."""
    now = datetime(2026, 11, 4, 15, tzinfo=timezone.utc)
    dialed = []
    for _ in range(calls):
        state = dial_eligibility(lead, campaign, now)
        if state is None:
            break
        if state == "later":
            now = lead.next_attempt_at
        number = lead_phones.pick(lead, campaign)
        _record_attempt(lead, campaign, now, number)
        dialed.append(number)
        result = answer(len(dialed), number) if answer else "no_answer"
        if result == "no_answer":
            _no_answer(lead, number)
        else:
            lead.status = next_status(lead.status, result) or lead.status
            lead_phones.mark(lead, number, lead_phones.status_for_outcome(result))
            if result == "do_not_call":
                lead.do_not_call = True
    return dialed


def test_csv_row_with_four_numbers_keeps_all_four_in_order():
    rows, _ = parse_contacts_csv(CSV)
    assert [p["number"] for p in rows[0]["phones"]] == NUMS
    assert rows[0]["phone"] == NUMS[0] and rows[0]["custom_fields"] == {"city": "Austin"}


def test_dnc_flags_in_the_file_are_ignored_unless_skip_dnc_is_on():
    csv = "Name,Phone,Phone DNC,Phone 2,Phone 2 DNC\nAnn,4155550301,Y,4155550302,\n"
    rows, _ = parse_contacts_csv(csv)
    assert [(p["number"], p["status"]) for p in rows[0]["phones"]] == [(NUMS[0], "untried"), (NUMS[1], "untried")]
    rows, _ = parse_contacts_csv(csv, skip_dnc=True)
    phones = rows[0]["phones"]
    assert [(p["number"], p["status"]) for p in phones] == [(NUMS[1], "untried"), (NUMS[0], "do_not_call")]
    assert rows[0]["phone"] == NUMS[1]


def test_two_rounds_per_number_then_the_retry_schedule_from_number_one():
    lead, campaign = _lead(), _campaign()
    dialed = _run(lead, campaign, 30)
    a, b, c, d = NUMS
    assert dialed == [a, a, b, b, c, c, d, d] * 2  # max_attempts=2: two passes
    assert lead.attempts == 2
    assert dial_eligibility(lead, campaign, datetime(2030, 1, 1, tzinfo=timezone.utc)) is None


def test_dials_inside_a_pass_use_the_gap_and_the_next_pass_waits_for_the_schedule():
    lead, campaign = _lead(2), _campaign()
    now = datetime(2026, 11, 4, 15, tzinfo=timezone.utc)
    _record_attempt(lead, campaign, now, NUMS[0])
    assert lead.next_attempt_at == now + timedelta(minutes=10)
    for n in (NUMS[0], NUMS[1], NUMS[1]):
        _record_attempt(lead, campaign, now, n)
    assert lead.next_attempt_at == now + timedelta(minutes=1440)  # pass done: the campaign's retry wait


def test_answer_on_number_two_stops_the_rest():
    lead, campaign = _lead(), _campaign()
    dialed = _run(lead, campaign, 30, answer=lambda i, n: "interested" if n == NUMS[1] else "no_answer")
    assert dialed == [NUMS[0], NUMS[0], NUMS[1]]
    assert NUMS[2] not in dialed and NUMS[3] not in dialed


def test_wrong_number_moves_on_and_is_never_called_again():
    lead, campaign = _lead(3), _campaign()
    dialed = _run(lead, campaign, 30, answer=lambda i, n: "wrong_number" if i == 1 else "no_answer")
    assert dialed[0] == NUMS[0] and dialed[1] == NUMS[1]
    assert dialed.count(NUMS[0]) == 1
    assert lead_phones.numbers(lead)[0]["status"] == "wrong_number"


def test_do_not_call_stops_every_number():
    lead, campaign = _lead(), _campaign()
    dialed = _run(lead, campaign, 30, answer=lambda i, n: "do_not_call")
    assert dialed == [NUMS[0]]


def test_voicemail_is_not_reaching_the_person():
    lead, campaign = _lead(2), _campaign()
    dialed = _run(lead, campaign, 30, answer=lambda i, n: "voicemail")
    assert dialed[:4] == [NUMS[0], NUMS[0], NUMS[1], NUMS[1]]


def test_off_only_the_primary_is_called_like_before():
    lead, campaign = _lead(), _campaign()
    campaign.try_other_numbers = False
    dialed = _run(lead, campaign, 30)
    assert set(dialed) == {NUMS[0]} and len(dialed) == 2


def test_single_number_contact_is_unchanged():
    lead = Lead(id=uuid.uuid4(), name="Solo", phone=NUMS[0], status="new", attempts=0)
    campaign = _campaign()
    dialed = _run(lead, campaign, 30)
    assert dialed == [NUMS[0]] * 4  # two passes of two rounds on its only number


def test_a_contact_is_never_dialed_twice_at_once():
    from app.services.outbound_call import LeadBusy, outbound_call_service

    lead = _lead()
    lead.status, lead.last_called_at = "calling", datetime.now(timezone.utc)
    try:
        asyncio.run(outbound_call_service.dispatch_call(lead, None, to_phone=NUMS[1]))
        raise AssertionError("expected LeadBusy")
    except LeadBusy:
        pass


def _fresh(n: int) -> list[str]:
    """Numbers no other test uses (the suite shares one database)."""
    import random
    base = random.randint(2_000_000, 9_000_000)
    return [f"+1628{base + i:07d}" for i in range(n)]


def test_import_api_stores_numbers_counts_one_target_and_dedupes_by_contact(client):
    extra, a1, a2, a3 = _fresh(4)
    camp = client.post("/api/campaigns/", json={"name": "Multi " + uuid.uuid4().hex[:6]}).json()
    nums = _fresh(4)
    csv = "name,phone,phone 2,mobile,home\nMax," + ",".join(nums) + "\n"
    out = client.post("/api/contacts/import", json={"csv": csv, "campaign_id": camp["id"]}).json()
    assert out["created"] == 1
    assert client.get(f"/api/campaigns/{camp['id']}").json()["total_targets"] == 1
    found = client.get("/api/contacts/", params={"q": nums[2]}).json()["items"]
    assert len(found) == 1 and [p["number"] for p in found[0]["phones"]] == nums

    # Same person, one shared number plus a new one: a duplicate, or with update_existing the new number is added.
    again = f"name,phone,phone 2\nMax,{nums[3]},{extra}\n"
    assert client.post("/api/contacts/import", json={"csv": again}).json()["duplicates"] == 1
    out = client.post("/api/contacts/import", json={"csv": again, "update_existing": True}).json()
    assert out["updated"] == 1 and out["created"] == 0
    c = client.get(f"/api/contacts/{found[0]['id']}").json()
    assert [p["number"] for p in c["phones"]] == [*nums, extra]

    # Picking the columns: only "mobile" and "phone", in that order.
    csv2 = f"name,phone,phone 2,mobile\nAmy,{a1},{a2},{a3}\n"
    client.post("/api/contacts/import", json={"csv": csv2, "phone_columns": ["mobile", "phone"]})
    amy = client.get("/api/contacts/", params={"q": a3}).json()["items"][0]
    assert [p["number"] for p in amy["phones"]] == [a3, a1]


def test_call_result_is_recorded_on_the_number_it_dialed(client):
    from app.database import AsyncSessionLocal
    from app.services.outbound_call import _mark_number

    p1, p2, p3 = _fresh(3)
    c = client.post("/api/contacts/", json={"name": "Two", "phone": p1, "phones": [p2]}).json()
    assert [p["number"] for p in c["phones"]] == [p1, p2]

    async def go():
        async with AsyncSessionLocal() as db:
            await _mark_number(db, uuid.UUID(c["id"]), p2, "wrong_number")
            await db.commit()
    asyncio.run(go())
    phones = client.get(f"/api/contacts/{c['id']}").json()["phones"]
    assert [p["status"] for p in phones] == ["untried", "wrong_number"]

    upd = client.patch(f"/api/contacts/{c['id']}", json={"phones": [p2, p3]}).json()
    assert upd["phone"] == p2 and upd["phones"][0]["status"] == "wrong_number"


def test_on_pause_is_a_potential_follow_up_not_a_refusal():
    from app.services.response_review import review_response

    t = [{"role": "assistant", "text": "Are you still looking around Alameda, or leaning towards somewhere else?"},
         {"role": "user", "text": "No. It's not not doing any of that."},
         {"role": "assistant", "text": "Got it. Is it on pause, or off the table for now?"},
         {"role": "user", "text": "Yeah. It's on pause. Thanks for the call. Bye."}]
    r = review_response({"outcome": "not_interested", "sentiment": "negative", "response_analysis": {
        "evidence_quote": "No. It's not not doing any of that.", "response_scope": "offer", "certainty": "clear",
        "next_action": "none_agreed"}}, t)
    assert r["outcome"] == "potential_follow_up" and r["sentiment"] == "neutral"
    t2 = [{"role": "assistant", "text": "Still looking?"}, {"role": "user", "text": "Not right now. Take me off your list."}]
    r2 = review_response({"outcome": "not_interested", "sentiment": "negative", "response_analysis": {
        "evidence_quote": "Not right now. Take me off your list.", "response_scope": "offer", "certainty": "clear",
        "next_action": "none_agreed"}}, t2)
    assert r2["outcome"] == "not_interested"
