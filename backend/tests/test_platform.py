import json

from app.services import llm


def _tool_call(name, args, call_id="c1"):
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
    ]}}]}


def _text(content):
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def test_seeded_agent_and_templates(client):
    agents = client.get("/api/agents/").json()
    assert agents, "a default agent is seeded on first boot"
    templates = client.get("/api/agents/templates/list").json()
    assert {t["template"] for t in templates} >= {"sales_sdr", "receptionist", "blank"}


def test_update_and_duplicate_agent(client, agent_id):
    r = client.patch(f"/api/agents/{agent_id}", json={
        "name": "Renamed", "temperature": 0.2,
        "extraction_fields": [{"name": "budget", "description": "Monthly budget"}],
    })
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed"
    assert r.json()["extraction_fields"] == [{"name": "budget", "description": "Monthly budget"}]
    dup = client.post(f"/api/agents/{agent_id}/duplicate").json()
    assert dup["name"] == "Renamed (copy)" and dup["id"] != agent_id


def test_playground_runs_booking_tools(client, agent_id, monkeypatch):
    sent = []
    replies = iter([
        _tool_call("check_availability", {"preferred_date": ""}),
        _text("I have two slots — which works?"),
    ])

    async def fake_chat(payload, timeout=45.0):
        sent.append(payload)
        return next(replies)

    monkeypatch.setattr(llm, "_chat", fake_chat)
    r = client.post(f"/api/agents/{agent_id}/chat", json={
        "messages": [{"role": "assistant", "content": "Hi!"}, {"role": "user", "content": "Book me a demo"}],
        "variables": {"name": "Jamie", "company": "Globex"},
    })
    body = r.json()
    assert r.status_code == 200, body
    assert body["reply"] == "I have two slots — which works?"
    assert body["tool_events"][0]["tool"] == "check_availability"
    assert len(body["state"]["slots"]) == 2  # mock slots when Cal.com isn't configured
    system = sent[0]["messages"][0]["content"]
    assert "Jamie" in system and "Globex" in system and "KNOWLEDGE BASE" in system
    assert {t["function"]["name"] for t in sent[0]["tools"]} == {"end_call", "check_availability", "book_appointment"}


def test_playground_end_call(client, agent_id, monkeypatch):
    replies = iter([_tool_call("end_call", {"outcome": "not_interested"}), _text("Take care!")])

    async def fake_chat(payload, timeout=45.0):
        return next(replies)

    monkeypatch.setattr(llm, "_chat", fake_chat)
    body = client.post(f"/api/agents/{agent_id}/chat", json={"messages": [{"role": "user", "content": "no thanks"}]}).json()
    assert body["ended"] is True and body["outcome"] == "not_interested"


def test_voice_and_phone_need_config(client, agent_id):
    r = client.post(f"/api/agents/{agent_id}/web-call", json={})
    assert r.status_code == 400 and "Voice isn't configured" in r.json()["detail"]
    r = client.post(f"/api/agents/{agent_id}/phone-call", json={"to_phone": "+14155550123"})
    assert r.status_code == 400


def test_csv_import(client, agent_id):
    cid = client.post("/api/campaigns/", json={"name": "C", "agent_id": agent_id}).json()["id"]
    csv = "Full Name,Phone Number,Company,City\nJane Doe,(415) 555-0123,Acme,SF\nNo Phone,,X,Y\nBob,+447700900123,,London\n"
    r = client.post(f"/api/campaigns/{cid}/leads/import", json={"csv": csv})
    assert r.json() == {"created": 2, "skipped": 1}
    leads = {l["name"]: l for l in client.get(f"/api/campaigns/{cid}/leads").json()["leads"]}
    assert leads["Jane Doe"]["phone"] == "+14155550123"
    assert leads["Jane Doe"]["custom_fields"] == {"city": "SF"}
    assert client.get(f"/api/campaigns/{cid}").json()["total_targets"] == 2
    # Dialing is refused until phone calling is configured.
    assert client.post(f"/api/campaigns/{cid}/start").status_code == 400


def test_outcome_webhook_runs_analysis(client, agent_id, monkeypatch):
    import asyncio
    import uuid

    from app.database import AsyncSessionLocal
    from app.models.call_log import CallLog

    call_id = uuid.uuid4()

    async def make_call():
        async with AsyncSessionLocal() as db:
            db.add(CallLog(id=call_id, agent_id=uuid.UUID(agent_id), call_type="web",
                           livekit_room_name="web-test", status="connected"))
            await db.commit()

    asyncio.run(make_call())

    async def fake_chat(payload, timeout=45.0):
        assert payload["response_format"] == {"type": "json_object"}
        return _text(json.dumps({
            "summary": "Prospect was keen and booked a demo.", "outcome": "meeting_booked",
            "sentiment": "positive", "successful": True, "extracted": {"team_size": "12"},
        }))

    monkeypatch.setattr(llm, "_chat", fake_chat)
    transcript = [{"role": "assistant", "text": "Hi"}, {"role": "user", "text": "Sure, book it"}]
    r = client.post(f"/api/webhook/calls/{call_id}/outcome", json={"outcome": "completed", "transcript": transcript})
    assert r.status_code == 200

    call = client.get(f"/api/calls/{call_id}").json()
    assert call["outcome"] == "meeting_booked"  # analyzer refined the generic outcome
    assert call["summary"].startswith("Prospect was keen")
    assert call["extracted_data"]["team_size"] == "12"
    assert call["transcript"] == transcript

    overview = client.get("/api/calls/overview").json()
    assert overview["meetings_booked"] >= 1
    assert client.get(f"/api/calls/?agent_id={agent_id}").json()["total"] >= 1


def test_settings_status(client):
    s = client.get("/api/settings/status").json()
    assert s["capabilities"]["chat_test"] is True
    assert s["capabilities"]["web_call"] is False
    assert client.get("/api/settings/voices").json()["source"] == "fallback"


def test_slot_matching_never_guesses():
    from app.services import calendar
    slots = calendar.remember_slots(calendar.mock_slots("2030-01-08"), calendar.mock_slots("2030-01-09"))  # Tue + Wed
    label = lambda q: (calendar.pick_slot(slots, q) or {}).get("label")
    assert label("Tuesday, January 8 at 6 in the evening") == "Tuesday, January 8 at 6:00 PM UTC"
    assert label("wednesday at 3") == "Wednesday, January 9 at 3:00 PM UTC"
    assert label("second") == slots[1]["label"]
    assert label("tuesday") is None   # two Tuesday slots: ask, don't guess
    assert label("6 pm") is None      # Tuesday or Wednesday?


def test_email_and_tool_name_guards():
    from app.agent.runtime import email_was_given, normalize_email, strip_tool_mentions
    assert normalize_email("Jamie at Globex dot com") == "jamie@globex.com"
    assert email_was_given("jamie@globex.com", ["it's jamie at globex dot com"])
    assert not email_was_given("jamie@globex.com", ["tuesday works"])  # never invented
    assert strip_tool_mentions("Have a great day! end_call") == "Have a great day!"


def test_cannot_end_as_booked_without_booking(client, agent_id, monkeypatch):
    replies = iter([_tool_call("end_call", {"outcome": "meeting_booked"}), _text("Let me grab a time first.")])

    async def fake_chat(payload, timeout=45.0):
        return next(replies)

    monkeypatch.setattr(llm, "_chat", fake_chat)
    body = client.post(f"/api/agents/{agent_id}/chat", json={"messages": [{"role": "user", "content": "ok"}]}).json()
    assert body["ended"] is False
    assert "no meeting is booked" in body["tool_events"][0]["result"]
