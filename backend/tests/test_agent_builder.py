import asyncio
import json
import uuid

from app.services import llm
from tests.test_accounts import _login, _new_account

SECTION_KEYS = ["identity", "reason", "flow", "qualification", "objections", "knowledge",
                "booking", "transfer", "voicemail", "callback", "closing", "compliance"]


def _text(content):
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _spec(**over):
    spec = {
        "agent_name": "Jordan",
        "first_message": "Hi {{name}}, this is Jordan, the AI assistant for Skyline Realty. Do you have a quick minute?",
        "sections": {k: f"{k.title()} instructions for the call." for k in SECTION_KEYS},
        "extraction_fields": [{"name": "budget", "description": "Price range"},
                              {"name": "preferred_area", "description": "Neighborhoods"},
                              {"name": "timeline", "description": "dup of a standard field"}],
        "success_criteria": "Successful if a buyer consultation is booked.",
        "title": "Buyer Follow-Up",
        "primary_objective": "Book a buyer consultation with an agent.",
        "target_audience": "Buyer leads from the website.",
        "qualification_questions": ["What price range are you comfortable with?", "When are you hoping to move?"],
        "desired_outcomes": ["Buyer consultation booked", "Callback scheduled"],
        "transfer_rules": "Transfer when they want to talk to an agent today.",
        "booking_rules": "Book 30 minute consultations.",
        "follow_up_logic": "If not ready, offer a callback next month.",
    }
    spec["sections"]["compliance"] = "Be honest. If asked, say you're an AI assistant. Use do_not_call when asked."
    spec.update(over)
    return spec


def _draft_data(**over):
    data = {
        "business": {"name": "Skyline Realty", "industry": "real_estate", "website": "", "description": "Austin homes"},
        "goal": {"direction": "outbound", "use_case": "buyer_follow_up", "answers": {"lead_age": "New leads"}},
        "behavior": {"agent_name": "", "language": "en", "style": "friendly", "qualification_depth": "standard",
                     "booking": False, "transfer_number": "+15125550100", "transfer_when": "",
                     "callback": True, "ai_disclosure": True},
        "integrations": {"selected": ["webhooks"]},
    }
    data.update(over)
    return data


def _mock_chat(monkeypatch, replies):
    sent = []
    it = iter(replies)

    async def fake_chat(payload, timeout=45.0):
        sent.append(payload)
        return _text(next(it))

    monkeypatch.setattr(llm, "_chat", fake_chat)
    return sent


# ── Catalog ───────────────────────────────────────────────────────────────────


def test_catalog_shape(client):
    cat = client.get("/api/agent-builder/catalog").json()
    keys = [i["key"] for i in cat["industries"]]
    assert keys == ["real_estate", "mortgage", "home_services", "healthcare", "insurance", "financial_services",
                    "recruiting", "logistics", "automotive", "professional_services", "other"]
    for key in keys:
        ucs = cat["use_cases"][key]
        directions = {u["direction"] for u in ucs}
        assert {"outbound", "inbound"} <= directions, key
        assert any(u["key"] == "custom" for u in ucs), key
        for u in ucs:
            assert 2 <= len(u["objectives"]) <= 4
            assert 3 <= len(u["qualification_questions"]) <= 6
            assert set(u["actions"]) <= {"book_appointment", "transfer", "callback", "send_info"}
            assert 2 <= len(u["followups"]) <= 4
            for f in u["followups"]:
                assert f["type"] in ("boolean", "choice", "text") and "default" in f

    re_ucs = {u["key"]: u for u in cat["use_cases"]["real_estate"]}
    assert {"speed_to_lead", "buyer_follow_up", "seller_follow_up", "lead_reactivation", "circle_prospecting",
            "expired_listings", "fsbo_prospecting", "cold_prospecting", "past_client_check_in",
            "appointment_confirmation", "buyer_inquiry", "seller_inquiry", "property_questions",
            "appointment_scheduling", "lead_qualification", "call_routing", "appointment_setting"} <= set(re_ucs)
    outbound_labels = [u["label"] for u in cat["use_cases"]["real_estate"] if u["direction"] == "outbound"]
    assert outbound_labels[:9] == ["Buyer Lead Follow-Up", "Seller Lead Follow-Up", "Speed to Lead", "FSBO Prospecting",
                                   "Expired Listings", "Circle Prospecting", "Lead Reactivation",
                                   "Appointment Setting", "General Prospecting"]
    assert re_ucs["custom"]["label"] == "Create Your Own"
    assert cat["use_case_aliases"]["general_prospecting"] == "cold_prospecting"
    fsbo, buyer = re_ucs["fsbo_prospecting"], re_ucs["buyer_follow_up"]
    assert set(fsbo["qualification_questions"]).isdisjoint(buyer["qualification_questions"])
    assert any("yourself" in q for q in fsbo["qualification_questions"])
    assert any("pre-approved" in q for q in buyer["qualification_questions"])

    assert {s["key"] for s in cat["styles"]} == {"friendly", "professional", "direct", "consultative", "custom"}
    integ = {i["key"]: i for i in cat["integrations"]}
    assert integ["calcom"]["status"] == "needs_setup"  # no Cal.com key in tests
    assert integ["transfer"]["status"] == integ["webhooks"]["status"] == integ["csv"]["status"] == "available"
    crms = [i for i in cat["integrations"] if i["category"] == "crm"]
    assert len(crms) == 11 and all(i["status"] == "coming_soon" and i["industries"] for i in crms)
    assert integ["follow_up_boss"]["detail"].startswith("Connect today through Zapier")
    assert integ["google_calendar"]["status"] == integ["calendly"]["status"] == "coming_soon"


def test_catalog_calendar_available_when_configured(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "calcom_api_key", "cal_test")
    monkeypatch.setattr(settings, "calcom_event_type_id", "123")
    integ = {i["key"]: i for i in client.get("/api/agent-builder/catalog").json()["integrations"]}
    assert integ["calcom"]["status"] == "available"


# ── Drafts ────────────────────────────────────────────────────────────────────


def test_drafts_crud_and_isolation(client, make_client):
    r = client.post("/api/agent-builder/drafts", json={"data": {"business": {"name": "A"}}})
    assert r.status_code == 201
    draft = r.json()
    assert draft["step"] == 1 and draft["agent_id"] is None and draft["data"]["business"]["name"] == "A"

    r = client.patch(f"/api/agent-builder/drafts/{draft['id']}", json={"step": 3, "data": {"goal": {"use_case": "x"}}})
    assert r.status_code == 200
    assert r.json()["step"] == 3 and r.json()["data"] == {"goal": {"use_case": "x"}}  # data replaces
    assert client.patch(f"/api/agent-builder/drafts/{draft['id']}", json={"step": 9}).status_code == 422
    assert client.get(f"/api/agent-builder/drafts/{draft['id']}").json()["step"] == 3
    assert draft["id"] in {d["id"] for d in client.get("/api/agent-builder/drafts").json()["drafts"]}

    _, email = _new_account(client, name="Other Co")
    other = _login(make_client, email)
    assert other.get(f"/api/agent-builder/drafts/{draft['id']}").status_code == 404
    assert other.patch(f"/api/agent-builder/drafts/{draft['id']}", json={"step": 2}).status_code == 404
    assert other.delete(f"/api/agent-builder/drafts/{draft['id']}").status_code == 404
    assert other.post("/api/agent-builder/generate", json={"draft_id": draft["id"]}).status_code == 404
    assert other.get("/api/agent-builder/drafts").json() == {"drafts": []}

    assert client.delete(f"/api/agent-builder/drafts/{draft['id']}").status_code == 204
    assert client.get(f"/api/agent-builder/drafts/{draft['id']}").status_code == 404


# ── Generate ──────────────────────────────────────────────────────────────────




def test_generate_validates_draft(client, monkeypatch):
    _mock_chat(monkeypatch, [])
    for data, word in [
        (_draft_data(business={"name": "", "industry": "real_estate"}), "business name"),
        (_draft_data(business={"name": "X", "industry": ""}), "industry"),
        (_draft_data(goal={"direction": "outbound", "use_case": ""}), "what the agent should do"),
        (_draft_data(goal={"use_case": "made_up"}), "use case"),
        (_draft_data(goal={"use_cases": ["custom"], "custom": {"description": "Call them"}}), "more detail"),
        (_draft_data(goal={"use_cases": ["custom"], "custom": {"description": ""}}), "what the agent should do"),
    ]:
        draft = client.post("/api/agent-builder/drafts", json={"data": data}).json()
        r = client.post("/api/agent-builder/generate", json={"draft_id": draft["id"]})
        assert r.status_code == 400 and word in r.json()["detail"], r.text
    assert client.post("/api/agent-builder/generate", json={"draft_id": str(uuid.uuid4())}).status_code == 404






def _generated_agent(client, monkeypatch, direction="outbound", transfer_number="+15125550100", transfer_enabled=True):
    """An agent built by the original 12-section builder — existing agents must keep working."""
    from app.agent.generator import assemble_prompt

    spec = _spec()
    agent_id = client.post("/api/agents/", json={"template": "blank"}).json()["id"]
    r = client.patch(f"/api/agents/{agent_id}", json={
        "system_prompt": assemble_prompt(spec["sections"]), "first_message": spec["first_message"],
        "transfer_number": transfer_number, "enable_booking": False, "knowledge_base": "Austin homes",
        "builder": {"industry": "real_estate", "use_case": "buyer_follow_up", "direction": direction,
                    "business_name": "Skyline Realty", "persona": "Jordan", "transfer_enabled": transfer_enabled,
                    "sections": spec["sections"], "plan": {"primary_objective": spec["primary_objective"]}},
    })
    assert r.status_code == 200, r.text
    return agent_id


# ── Improve / regenerate ──────────────────────────────────────────────────────


def test_improve_returns_proposal_without_saving(client, monkeypatch):
    agent_id = _generated_agent(client, monkeypatch)
    before = client.get(f"/api/agents/{agent_id}").json()

    sent = _mock_chat(monkeypatch, [json.dumps({
        "summary": "Made objection handling shorter and dropped the AI line from compliance.",
        "first_message": before["first_message"],
        "changed_sections": {"objections": "Keep objection replies to one sentence.",
                             "compliance": "Be polite."},
    })])
    r = client.post(f"/api/agent-builder/agents/{agent_id}/improve", json={"instruction": "Be less pushy"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert "Be less pushy" in sent[0]["messages"][1]["content"]
    assert p["sections"]["objections"] == "Keep objection replies to one sentence."
    assert p["sections"]["flow"] == before["builder"]["sections"]["flow"]  # untouched
    assert "AI assistant" in p["sections"]["compliance"]  # disclosure kept
    assert "do_not_call" in p["sections"]["compliance"]
    assert "Keep objection replies to one sentence." in p["system_prompt"]
    assert p["system_prompt"].count("## ") == 12

    after = client.get(f"/api/agents/{agent_id}").json()
    assert after["system_prompt"] == before["system_prompt"] and after["builder"] == before["builder"]

    # Applying the proposal goes through the normal agent PATCH.
    r = client.patch(f"/api/agents/{agent_id}", json={
        "system_prompt": p["system_prompt"], "builder": {**before["builder"], "sections": p["sections"]},
    })
    assert r.status_code == 200 and r.json()["builder"]["sections"]["objections"].startswith("Keep objection")


def test_improve_plain_agent(client, agent_id, monkeypatch):
    _mock_chat(monkeypatch, [json.dumps({"summary": "Shorter.", "first_message": "Hi {{name}}!",
                                         "system_prompt": "# IDENTITY\nShort."})])
    p = client.post(f"/api/agent-builder/agents/{agent_id}/improve", json={"instruction": "Shorter"}).json()
    assert p == {"summary": "Shorter.", "first_message": "Hi {{name}}!", "system_prompt": "# IDENTITY\nShort."}


def test_regenerate_section(client, monkeypatch):
    agent_id = _generated_agent(client, monkeypatch)
    sent = _mock_chat(monkeypatch, [json.dumps({"text": "If you reach voicemail, leave a ten second message."})])
    r = client.post(f"/api/agent-builder/agents/{agent_id}/regenerate",
                    json={"section": "voicemail", "instruction": "shorter"})
    assert r.status_code == 200, r.text
    assert r.json() == {"section": "voicemail", "text": "If you reach voicemail, leave a ten second message."}
    assert "Skyline Realty" in sent[0]["messages"][1]["content"]
    assert client.post(f"/api/agent-builder/agents/{agent_id}/regenerate",
                       json={"section": "nope"}).status_code == 400


def test_editor_helpers_are_org_scoped(client, make_client, agent_id):
    _, email = _new_account(client, name="Nosy Co")
    other = _login(make_client, email)
    assert other.post(f"/api/agent-builder/agents/{agent_id}/improve", json={"instruction": "x"}).status_code == 404
    assert other.post(f"/api/agent-builder/agents/{agent_id}/regenerate", json={"section": "flow"}).status_code == 404
    assert other.get(f"/api/agent-builder/agents/{agent_id}/readiness").status_code == 404


# ── Readiness ─────────────────────────────────────────────────────────────────


def test_readiness_blockers_on_fresh_account(client, make_client):
    _, email = _new_account(client, name="Fresh Co")
    owner = _login(make_client, email)
    agent = owner.get("/api/agents/").json()[0]
    r = owner.get(f"/api/agent-builder/agents/{agent['id']}/readiness")
    assert r.status_code == 200
    body = r.json()
    checks = {c["key"]: c for c in body["checks"]}
    assert body["ready"] is False
    assert checks["credits"]["status"] == "blocker" and checks["credits"]["fix_href"] == "/profile?tab=billing"
    assert checks["phone"]["status"] == "blocker"  # outbound by default, no phone line
    assert checks["voice"]["status"] == "blocker"
    assert checks["prompt"]["status"] == "ok" and checks["account"]["status"] == "ok"
    assert all(c["detail"] for c in body["checks"])


def test_readiness_warnings_and_transfer(client, monkeypatch):
    from app.config import settings

    for k, v in {"livekit_url": "wss://x", "livekit_api_key": "k", "livekit_api_secret": "s",
                 "deepgram_api_key": "d", "cartesia_api_key": "c"}.items():
        monkeypatch.setattr(settings, k, v)
    agent_id = _generated_agent(client, monkeypatch, direction="inbound")
    client.patch(f"/api/agents/{agent_id}", json={"ai_disclosure": False, "enable_booking": True,
                                                  "transfer_number": "", "knowledge_base": ""})
    body = client.get(f"/api/agent-builder/agents/{agent_id}/readiness").json()
    checks = {c["key"]: c for c in body["checks"]}
    assert checks["voice"]["status"] == "ok"
    assert checks["phone"]["status"] == "warning"  # inbound-only
    assert checks["calendar"]["status"] == "warning"
    assert checks["knowledge"]["status"] == "warning" and checks["knowledge"]["fix_href"] == "/knowledge"
    assert checks["ai_disclosure"]["status"] == "warning"
    # The draft planned transfers; clearing the number makes that a blocker.
    assert checks["transfer"]["status"] == "blocker"
    assert body["ready"] is False


def test_readiness_transfer_without_number(client, monkeypatch):
    agent_id = _generated_agent(client, monkeypatch, transfer_number="")
    agent = client.get(f"/api/agents/{agent_id}").json()
    assert agent["builder"]["transfer_enabled"] is True and agent["transfer_number"] == ""
    checks = {c["key"]: c for c in client.get(f"/api/agent-builder/agents/{agent_id}/readiness").json()["checks"]}
    assert checks["transfer"]["status"] == "blocker" and checks["transfer"]["fix_href"] == f"/agents/{agent_id}"


# ── Agents PATCH, outcomes, runtime ──────────────────────────────────────────


def test_agents_patch_accepts_builder_and_disclosure(client, agent_id):
    r = client.patch(f"/api/agents/{agent_id}", json={"ai_disclosure": False, "builder": {"direction": "inbound"}})
    assert r.status_code == 200
    assert r.json()["ai_disclosure"] is False and r.json()["builder"] == {"direction": "inbound"}
    assert client.get(f"/api/agents/{agent_id}").json()["ai_disclosure"] is False


def test_runtime_includes_ai_disclosure():
    from types import SimpleNamespace

    from app.agent.runtime import agent_to_runtime, build_instructions

    agent = SimpleNamespace(id=uuid.uuid4(), name="Jordan", system_prompt="Be nice.", first_message="Hi",
                            knowledge_base="", language="en", llm_model="gpt-4.1", temperature=0.5, voice_id="",
                            voice_speed=1.0, background_audio=False, enable_booking=False,
                            calcom_event_type_id="", transfer_number="", max_duration_seconds=600,
                            ai_disclosure=True, builder={"business_name": "Skyline Realty"})
    cfg = agent_to_runtime(agent)
    assert cfg["ai_disclosure"] is True
    assert "AI assistant for Skyline Realty" in build_instructions(cfg, {})
    cfg["ai_disclosure"] = False
    assert "AI assistant for" not in build_instructions(cfg, {})


def test_do_not_call_outcome_marks_lead(client, agent_id, monkeypatch):
    from app.database import AsyncSessionLocal
    from app.models.call_log import CALL_OUTCOMES, CallLog
    from app.models.lead import Lead

    assert {"wrong_number", "do_not_call"} <= set(CALL_OUTCOMES)
    org_id = uuid.UUID(client.get("/api/auth/me").json()["org"]["id"])
    call_id, lead_id = uuid.uuid4(), uuid.uuid4()

    async def setup():
        async with AsyncSessionLocal() as db:
            db.add(Lead(id=lead_id, org_id=org_id, name="Pat Doe", phone="+15125550199"))
            await db.flush()
            db.add(CallLog(id=call_id, org_id=org_id, agent_id=uuid.UUID(agent_id), lead_id=lead_id,
                           call_type="web", livekit_room_name="web-dnc", status="connected"))
            await db.commit()

    async def lead_dnc():
        async with AsyncSessionLocal() as db:
            return (await db.get(Lead, lead_id)).do_not_call

    asyncio.run(setup())
    sent = []

    async def fake_chat(payload, timeout=45.0):
        sent.append(payload)
        return _text(json.dumps({"summary": "Asked not to be called.", "outcome": "do_not_call",
                                 "sentiment": "negative", "successful": False, "extracted": {}}))

    monkeypatch.setattr(llm, "_chat", fake_chat)
    transcript = [{"role": "assistant", "text": "Hi"}, {"role": "user", "text": "Stop calling me"}]
    r = client.post(f"/internal/calls/{call_id}/outcome", json={"outcome": "do_not_call", "transcript": transcript})
    assert r.status_code == 200
    assert asyncio.run(lead_dnc()) is True
    assert client.get(f"/api/calls/{call_id}").json()["outcome"] == "do_not_call"
    # Post-call analysis always asks for the standard fields.
    prompt = sent[0]["messages"][0]["content"]
    for name in ("lead_intent", "timeline", "key_objections", "next_action"):
        assert f'"{name}"' in prompt


# ── Assist (interactive follow-up questions) ────────────────────────────────


def _custom_goal(**over):
    goal = {
        "direction": "outbound",
        "use_cases": ["custom"],
        "use_case": "custom",
        "custom": {"description": "Call homeowners who requested a valuation, check if they're selling, "
                                  "and transfer interested ones to my team.",
                   "audience": "Homeowners", "tone": "", "outcome": ""},
        "extra_instructions": "",
        "assistant": [],
    }
    goal.update(over)
    return goal


def _assist_reply(**over):
    reply = {
        "understanding": "Got it. I'll build an agent focused on finding homeowners ready to sell.",
        "questions": [
            {"id": "audience", "question": "Who will the agent call?", "suggestions": ["Homeowners", "Past clients"]},
            {"id": "lead_source", "question": "Where did these leads come from?",
             "suggestions": ["Website", "Zillow", "Mailers"], "reason": "Helps the opener."},
            {"id": "lead_source", "question": "Duplicate id", "suggestions": ["A", "B"]},
            {"id": "Price Expectations", "question": "Should the agent ask about price?",
             "suggestions": ["Yes", "No", "If they bring it up", "Always", "Never"]},
            {"id": "timeline", "question": "Ask about their moving timeline?", "suggestions": ["Yes", "No"]},
        ],
        "ready": False,
        "recommendation": "Transfers work best within 30 seconds.",
        "irrelevant": ["old_one", "made_up"],
    }
    reply.update(over)
    return reply


def test_assist_returns_questions_and_filters_answered(client, monkeypatch):
    goal = _custom_goal(assistant=[
        {"id": "timeline", "question": "Ask about their moving timeline?", "answer": "Yes", "skipped": False},
        {"id": "old_one", "question": "Old question?", "answer": "Something", "skipped": False},
    ])
    draft = client.post("/api/agent-builder/drafts",
                        json={"data": _draft_data(business={"name": "", "industry": "real_estate"}, goal=goal)}).json()
    sent = _mock_chat(monkeypatch, [json.dumps(_assist_reply())])
    r = client.post("/api/agent-builder/assist", json={"draft_id": draft["id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["understanding"].startswith("Got it.")
    ids = [q["id"] for q in body["questions"]]
    # audience is filled in, timeline already answered, duplicates dropped, ids slugged, cap of 3.
    assert ids == ["lead_source", "price_expectations"]
    assert body["questions"][0]["reason"] == "Helps the opener."
    assert len(body["questions"][1]["suggestions"]) == 4
    assert body["ready"] is False and body["recommendation"].startswith("Transfers")
    assert body["irrelevant"] == ["old_one"]  # only ids that exist in the draft

    payload = sent[0]
    assert payload["response_format"] == {"type": "json_object"}
    prompt = payload["messages"][1]["content"]
    assert "requested a valuation" in prompt and "Homeowners" in prompt
    assert "Ask about their moving timeline?" in prompt and "audience" in prompt
    assert "never ask" in payload["messages"][0]["content"].lower()


def test_assist_caps_rounds_and_questions(client, monkeypatch):
    answered = [{"id": f"t{i}", "question": f"Question {i}?", "answer": "Yes", "skipped": False} for i in range(4)]
    draft = client.post("/api/agent-builder/drafts", json={"data": _draft_data(
        goal=_custom_goal(assistant=answered + [{"id": "t9", "question": "Q9?", "answer": None, "skipped": True}]))}).json()
    sent = _mock_chat(monkeypatch, [json.dumps(_assist_reply())])
    body = client.post("/api/agent-builder/assist", json={"draft_id": draft["id"]}).json()
    assert body["questions"] == [] and body["ready"] is True  # 5 asked → no more questions
    assert "at most 0 question" in sent[0]["messages"][1]["content"]

    draft = client.post("/api/agent-builder/drafts", json={"data": _draft_data(
        goal=_custom_goal(assist_rounds=2))}).json()
    _mock_chat(monkeypatch, [json.dumps(_assist_reply())])
    body = client.post("/api/agent-builder/assist", json={"draft_id": draft["id"]}).json()
    assert body["questions"] == [] and body["ready"] is True


def test_assist_with_presets(client, monkeypatch):
    goal = {"direction": "outbound", "use_cases": ["seller_follow_up", "expired_listings"],
            "use_case": "seller_follow_up", "extra_instructions": "Be casual."}
    draft = client.post("/api/agent-builder/drafts", json={"data": _draft_data(goal=goal)}).json()
    sent = _mock_chat(monkeypatch, [json.dumps(_assist_reply(questions=[], ready=True, recommendation=None))])
    body = client.post("/api/agent-builder/assist", json={"draft_id": draft["id"]}).json()
    assert body["ready"] is True and body["questions"] == [] and body["recommendation"] is None
    prompt = sent[0]["messages"][1]["content"]
    assert "[PRIMARY] Seller Lead Follow-Up" in prompt and "[ALSO] Expired Listings" in prompt
    assert "Be casual." in prompt


def test_assist_validation_retry_and_errors(client, monkeypatch, make_client):
    from app.config import settings

    # Nothing to work with yet → 400 before any AI call.
    empty = client.post("/api/agent-builder/drafts", json={"data": {"business": {"industry": "other"}}}).json()
    _mock_chat(monkeypatch, [])
    r = client.post("/api/agent-builder/assist", json={"draft_id": empty["id"]})
    assert r.status_code == 400 and "what the agent should do" in r.json()["detail"]
    short = client.post("/api/agent-builder/drafts", json={"data": _draft_data(
        goal=_custom_goal(custom={"description": "Call people"}))}).json()
    r = client.post("/api/agent-builder/assist", json={"draft_id": short["id"]})
    assert r.status_code == 400 and "more detail" in r.json()["detail"]

    draft = client.post("/api/agent-builder/drafts", json={"data": _draft_data(goal=_custom_goal())}).json()
    # Invalid twice (missing ready; one suggestion only) → one retry then 502.
    no_ready = _assist_reply()
    del no_ready["ready"]
    one_sugg = _assist_reply(questions=[{"id": "x", "question": "Q?", "suggestions": ["Only"]}])
    sent = _mock_chat(monkeypatch, [json.dumps(no_ready), json.dumps(one_sugg)])
    r = client.post("/api/agent-builder/assist", json={"draft_id": draft["id"]})
    assert r.status_code == 502 and "try again" in r.json()["detail"] and len(sent) == 2

    # Bad JSON first, valid on retry → 200.
    sent = _mock_chat(monkeypatch, ["{oops", json.dumps(_assist_reply())])
    assert client.post("/api/agent-builder/assist", json={"draft_id": draft["id"]}).status_code == 200
    assert len(sent) == 2

    # Org isolation.
    _, email = _new_account(client, name="Assist Other Co")
    other = _login(make_client, email)
    assert other.post("/api/agent-builder/assist", json={"draft_id": draft["id"]}).status_code == 404

    monkeypatch.setattr(settings, "openai_api_key", "")
    r = client.post("/api/agent-builder/assist", json={"draft_id": draft["id"]})
    assert r.status_code == 400 and r.json()["detail"] == "AI generation needs the OpenAI key to be configured."


# ── Generate: custom, multi-preset, old drafts ───────────────────────────────










def test_transfer_request_without_number_is_flagged():
    from app.agent import generator
    data = {"goal": {"custom": {"description": "Call old buyer leads"},
                     "assistant": [{"id": "q", "question": "Then?", "answer": "Warm transfer hot leads to my team"}]}}
    assert generator.transfer_requested(data)
    assert not generator.transfer_requested({"goal": {"custom": {"description": "Book appointments only"}}})
