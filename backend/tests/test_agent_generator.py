from app.services.public_errors import GENERIC
"""Production agent generator: pipeline, quality gate, isolation, references, versions, playbook library."""

import base64
import copy
import io
import json
import zipfile

from app.services import llm
from tests.sample_agent import CONVERSATION, DRAFT, STRATEGY
from tests.test_accounts import _login, _new_account


def _reply(content, finish="stop"):
    return {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}]}


def _route_chat(monkeypatch, strategy=STRATEGY, conversation=CONVERSATION, extra=None):
    """Answer by pipeline stage. `extra` is a list of (stage, reply) consumed before the defaults."""
    sent, queue = [], list(extra or [])

    async def fake_chat(payload, timeout=45.0):
        sent.append(payload)
        text = payload["messages"][1]["content"]
        stage = "repair" if "REPAIR" in text else ("strategy" if "STAGE 1" in text else "conversation")
        for i, (s, r) in enumerate(queue):
            if s == stage:
                queue.pop(i)
                return r
        return _reply(json.dumps(strategy if stage == "strategy" else conversation))

    monkeypatch.setattr(llm, "_chat", fake_chat)
    return sent


def _generate(client, data=None):
    draft = client.post("/api/agent-builder/drafts", json={"data": copy.deepcopy(data or DRAFT), "step": 7}).json()
    r = client.post("/api/agent-builder/generate", json={"draft_id": draft["id"]})
    assert r.status_code == 202, r.text
    status = client.get(f"/api/agent-builder/drafts/{draft['id']}/generation").json()
    return draft, status


def test_generates_complete_agent_end_to_end(client, monkeypatch):
    sent = _route_chat(monkeypatch)
    draft = client.post("/api/agent-builder/drafts", json={"data": copy.deepcopy(DRAFT), "step": 7}).json()
    ref = client.post(f"/api/agent-builder/drafts/{draft['id']}/references",
                      json={"name": "Our old script", "text": "Always ask whether the roof faces south before anything else."})
    assert ref.status_code == 201, ref.text

    assert client.post("/api/agent-builder/generate", json={"draft_id": draft["id"]}).status_code == 202
    status = client.get(f"/api/agent-builder/drafts/{draft['id']}/generation").json()
    assert status["status"] == "done" and status["agent_id"], status
    assert [s["key"] for s in status["stages"]] == ["context", "strategy", "conversation", "quality", "save"]

    # Two schema-guided stages, generous output budgets, JSON mode.
    assert len(sent) == 2
    assert all(p["response_format"] == {"type": "json_object"} and p["max_tokens"] >= 8000 for p in sent)
    prompt = sent[0]["messages"][1]["content"]
    assert "Brightline Home Solar" in prompt and "<customer_reference name=\"Our old script\">" in prompt
    assert "roof faces south" in prompt and "PLAYBOOK PATTERNS" in prompt and "<playbook" in prompt
    # Internal originals and their private details never reach the model.
    for private in ("ai.blacksync.cloud", "Valley Ridge", "Realty One", "equipment_finance_ai_sdr", "BLACKSYNC_API_KEY"):
        assert private not in prompt
    assert "transfer_call()" in prompt and "book_appointment" not in prompt.split("NOT AVAILABLE")[0].split("AVAILABLE TOOLS")[1]

    agent = client.get(f"/api/agents/{status['agent_id']}").json()
    sp = agent["system_prompt"]
    headings = [line[3:] for line in sp.splitlines() if line.startswith("## ")]
    assert headings == ["Agent Identity & Role", "Objectives and Success Criteria", "Voice & Conversational Conduct",
                        "Variables and Personalization", "Opening Script", "Dynamic Call Flow",
                        "Qualification Questions and Stop Rules", "Objection Handling & Direct Answers",
                        "Tools, Transfers, and Calendar", "Post-Call Structured Output",
                        "Compliance, Privacy, and Security", "Turn-Taking Edge Cases"]
    assert len(sp.split()) > 1500  # full operating instructions, not a description
    assert agent["first_message"] == "Hi, is this {{name}}?"
    assert "Stop and wait" in sp and "do_not_call" in sp and "Maya" in sp

    b = agent["builder"]
    assert b["schema"] == "v2" and set(b["sections"]) == {k for k, _ in b["section_order"]}
    assert all(c["status"] == "pass" for c in b["quality"]["checks"]), b["quality"]
    assert b["spec"]["strategy"]["facts"] and b["generation"]["references"] == ["Our old script"]
    # Booking was requested but no calendar is connected: no booking tools, readiness explains it.
    assert agent["enable_booking"] is False and b["booking_requested"] is True
    assert agent["transfer_number"] == "+15205550142"
    names = [f["name"] for f in agent["extraction_fields"]]
    assert "hold_back_reason" in names and "lead_intent" in names
    checks = {c["key"]: c for c in client.get(f"/api/agent-builder/agents/{agent['id']}/readiness").json()["checks"]}
    assert checks["calendar"]["status"] == "warning" and "calendar" in checks["calendar"]["detail"]

    versions = client.get(f"/api/agents/{agent['id']}/versions").json()["versions"]
    assert [v["source"] for v in versions] == ["generated"]
    # Generating again returns the finished result instead of creating a second agent.
    again = client.post("/api/agent-builder/generate", json={"draft_id": draft["id"]}).json()
    assert again["agent_id"] == agent["id"]


def test_truncated_answer_is_retried_with_more_room(client, monkeypatch):
    sent = _route_chat(monkeypatch, extra=[("strategy", _reply('{"agent_name": "Ma', finish="length"))])
    _, status = _generate(client)
    assert status["status"] == "done", status
    budgets = [p["max_tokens"] for p in sent if "STAGE 1" in p["messages"][1]["content"]]
    assert budgets[0] < budgets[1]
    assert "cut off" in sent[1]["messages"][-1]["content"]


def test_invalid_spec_gets_exact_error_and_retry(client, monkeypatch):
    bad = copy.deepcopy(STRATEGY)
    bad["tools"].append({"tool": "book_appointment", "use_when": "they want a meeting"})  # no calendar connected
    sent = _route_chat(monkeypatch, extra=[("strategy", _reply(json.dumps(bad)))])
    _, status = _generate(client)
    assert status["status"] == "done", status
    fix = [p for p in sent if "rejected" in p["messages"][-1]["content"]]
    assert fix and "book_appointment" in fix[0]["messages"][-1]["content"]


def test_leaked_reference_details_are_repaired(client, monkeypatch):
    leaky = copy.deepcopy(CONVERSATION)
    leaky["objections"][0]["response"] = "Jeff at Realty One sold a home on Valley Ridge Drive for top dollar."
    sent = _route_chat(monkeypatch, extra=[("conversation", _reply(json.dumps(leaky)))])
    draft, status = _generate(client)
    assert status["status"] == "done", status
    repair = [p for p in sent if "REPAIR" in p["messages"][-1]["content"]]
    assert repair and "reference-script details" in repair[0]["messages"][-1]["content"]
    agent = client.get(f"/api/agents/{status['agent_id']}").json()
    assert "Valley Ridge" not in agent["system_prompt"] and "Realty One" not in agent["system_prompt"]


def test_quality_failure_that_never_heals_is_reported(client, monkeypatch):
    leaky = copy.deepcopy(CONVERSATION)
    leaky["direct_answers"].append({"question": "Website?", "answer": "Go to https://ai.blacksync.cloud/api/zapier/quick_call_result/"})
    _route_chat(monkeypatch, conversation=leaky)
    draft, status = _generate(client)
    assert status["status"] == "failed" and "quality checks" in status["error"]
    assert client.get(f"/api/agent-builder/drafts/{draft['id']}").json()["agent_id"] is None


def test_customer_supplied_terms_are_not_leaks(client, monkeypatch):
    data = copy.deepcopy(DRAFT)
    data["behavior"]["agent_name"] = "Lilly"  # a playbook name, chosen by this customer → allowed
    strategy = {**copy.deepcopy(STRATEGY), "agent_name": "Lilly"}
    conversation = json.loads(json.dumps(CONVERSATION).replace("Maya", "Lilly"))
    _route_chat(monkeypatch, strategy=strategy, conversation=conversation)
    _, status = _generate(client, data)
    assert status["status"] == "done", status


def test_generation_errors_are_reported_on_the_draft(client, monkeypatch):
    async def boom(payload, timeout=45.0):
        raise RuntimeError("OpenAI error 500")

    monkeypatch.setattr(llm, "_chat", boom)
    draft, status = _generate(client)
    assert status["status"] == "failed" and "didn't respond" in status["error"]
    # Retry works once the service is back.
    _route_chat(monkeypatch)
    assert client.post("/api/agent-builder/generate", json={"draft_id": draft["id"]}).status_code == 202
    assert client.get(f"/api/agent-builder/drafts/{draft['id']}/generation").json()["status"] == "done"


def test_generation_needs_openai_and_is_org_scoped(client, make_client, monkeypatch):
    from app.config import settings

    draft = client.post("/api/agent-builder/drafts", json={"data": copy.deepcopy(DRAFT)}).json()
    _, email = _new_account(client, name="Elsewhere Inc")
    other = _login(make_client, email)
    assert other.get(f"/api/agent-builder/drafts/{draft['id']}/generation").status_code == 404
    assert other.post("/api/agent-builder/generate", json={"draft_id": draft["id"]}).status_code == 404
    monkeypatch.setattr(settings, "openai_api_key", "")
    r = client.post("/api/agent-builder/generate", json={"draft_id": draft["id"]})
    assert r.status_code == 400 and r.json()["detail"] == GENERIC


# ── Customer references ───────────────────────────────────────────────────────


def _docx(text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    return base64.b64encode(buf.getvalue()).decode()


def test_references_upload_parse_and_isolation(client, make_client):
    draft = client.post("/api/agent-builder/drafts", json={"data": {}}).json()
    url = f"/api/agent-builder/drafts/{draft['id']}/references"
    r = client.post(url, json={"filename": "script.docx", "content_base64": _docx("Ask about the HOA first &amp; be kind.")})
    assert r.status_code == 201 and r.json()["kind"] == "docx" and "HOA first & be kind" in r.json()["preview"]
    txt = base64.b64encode(b"Opening line: hi there, quick question about your quote.").decode()
    assert client.post(url, json={"filename": "notes.txt", "content_base64": txt}).json()["kind"] == "txt"
    assert client.post(url, json={"filename": "deck.pptx", "content_base64": txt}).status_code == 400
    assert client.post(url, json={"filename": "x.pdf", "content_base64": "%%%"}).status_code == 400
    assert client.post(url, json={"text": "short"}).status_code == 400
    refs = client.get(url).json()["references"]
    assert [x["kind"] for x in refs] == ["docx", "txt"]

    _, email = _new_account(client, name="Snoop LLC")
    other = _login(make_client, email)
    assert other.get(url).status_code == 404
    assert other.post(url, json={"text": "Trying to add to someone else's draft"}).status_code == 404
    assert other.delete(f"/api/agent-builder/references/{refs[0]['id']}").status_code == 404
    assert client.delete(f"/api/agent-builder/references/{refs[0]['id']}").status_code == 204
    assert len(client.get(url).json()["references"]) == 1


# ── Versions and v2 editing ──────────────────────────────────────────────────


def test_edits_are_versioned_and_restorable(client, monkeypatch):
    _route_chat(monkeypatch)
    _, status = _generate(client)
    aid = status["agent_id"]
    agent = client.get(f"/api/agents/{aid}").json()
    original = agent["system_prompt"]
    sections = {**agent["builder"]["sections"], "opening": "Say hello and ask how they are."}
    r = client.patch(f"/api/agents/{aid}", json={
        "system_prompt": original.replace("Maya", "Maya!"),
        "builder": {**agent["builder"], "sections": sections, "schema": "v1", "quality": None},
    })
    assert r.status_code == 200
    b = r.json()["builder"]
    assert b["schema"] == "v2" and b["quality"]["checks"]  # generator metadata is protected
    versions = client.get(f"/api/agents/{aid}/versions").json()["versions"]
    assert [v["source"] for v in versions] == ["edited", "generated"]
    first = versions[-1]
    full = client.get(f"/api/agents/{aid}/versions/{first['id']}").json()
    assert full["system_prompt"] == original
    restored = client.post(f"/api/agents/{aid}/versions/{first['id']}/restore").json()
    assert restored["system_prompt"] == original
    assert restored["builder"]["sections"]["opening"] == agent["builder"]["sections"]["opening"]
    assert client.get(f"/api/agents/{aid}/versions").json()["versions"][0]["source"] == "restored"


def test_regenerate_v2_section_is_leak_checked(client, monkeypatch):
    _route_chat(monkeypatch)
    _, status = _generate(client)
    aid = status["agent_id"]
    replies = iter([_reply(json.dumps({"text": "Mention that Realty One recommends us. Then ask about their roof."})),
                    _reply(json.dumps({"text": "Ask about their roof first, then their timeline. Stop and wait after each."}))])
    sent = []

    async def fake_chat(payload, timeout=45.0):
        sent.append(payload)
        return next(replies)

    monkeypatch.setattr(llm, "_chat", fake_chat)
    r = client.post(f"/api/agent-builder/agents/{aid}/regenerate", json={"section": "qualification", "instruction": "roof first"})
    assert r.status_code == 200, r.text
    assert r.json()["text"].startswith("Ask about their roof first")
    assert "Realty One" in sent[1]["messages"][-1]["content"]  # the rejection told the model what to remove
    assert client.post(f"/api/agent-builder/agents/{aid}/regenerate", json={"section": "voicemail"}).status_code == 400


def test_improve_v2_agent_keeps_v2_sections(client, monkeypatch):
    _route_chat(monkeypatch)
    _, status = _generate(client)
    aid = status["agent_id"]
    agent = client.get(f"/api/agents/{aid}").json()

    async def fake_chat(payload, timeout=45.0):
        return _reply(json.dumps({"summary": "Shorter opening.", "first_message": agent["first_message"],
                                  "changed_sections": {"opening": "Greet them, then ask one question and wait."}}))

    monkeypatch.setattr(llm, "_chat", fake_chat)
    p = client.post(f"/api/agent-builder/agents/{aid}/improve", json={"instruction": "Shorter opening"}).json()
    assert p["sections"]["opening"].startswith("Greet them") and set(p["sections"]) == set(agent["builder"]["sections"])
    assert "## Opening Script\n\nGreet them" in p["system_prompt"] and "## Agent Identity & Role" in p["system_prompt"]


# ── Internal playbook library (admin only) ───────────────────────────────────


def test_playbook_library_is_admin_only_and_versioned(client, make_client):
    from app.agent.playbooks import original

    pbs = client.get("/api/admin/playbooks").json()["playbooks"]
    slugs = {p["slug"] for p in pbs}
    assert {"corporate_sales_equipment_finance", "real_estate_sdr", "expired_listing_followup"} <= slugs
    pb = next(p for p in pbs if p["slug"] == "expired_listing_followup")
    detail = client.get(f"/api/admin/playbooks/{pb['id']}").json()
    assert detail["current"]["original_text"] == original("expired_listing_followup")  # verbatim archive
    assert "Valley Ridge" in detail["current"]["original_text"]
    assert "Valley Ridge" not in detail["current"]["patterns"] and "Jeff" not in detail["current"]["patterns"]
    assert "Valley Ridge" in detail["current"]["private_terms"]

    r = client.post(f"/api/admin/playbooks/{pb['id']}/versions", json={
        "patterns": detail["current"]["patterns"] + "\n- Extra: confirm the visit window the day before.",
        "private_terms": detail["current"]["private_terms"] + ["Ridgeview"], "note": "Add reminder"})
    assert r.status_code == 201 and r.json()["current_version"] == 2
    assert r.json()["current"]["original_text"] == original("expired_listing_followup")
    rolled = client.patch(f"/api/admin/playbooks/{pb['id']}", json={"current_version": 1, "active": False}).json()
    assert rolled["current_version"] == 1 and rolled["active"] is False and len(rolled["versions"]) == 2
    client.patch(f"/api/admin/playbooks/{pb['id']}", json={"active": True})

    _, email = _new_account(client, name="Customer Co")
    customer = _login(make_client, email)
    assert customer.get("/api/admin/playbooks").status_code in (401, 403)
    assert customer.get(f"/api/admin/playbooks/{pb['id']}").status_code in (401, 403)


def test_playbook_retrieval_prefers_relevant_patterns():
    import asyncio

    from app.database import AsyncSessionLocal
    from app.services.playbooks import relevant_patterns

    async def go():
        async with AsyncSessionLocal() as db:
            re_ = await relevant_patterns(db, "real_estate", "outbound", "expired listings seller follow up appointment")
            fin = await relevant_patterns(db, "financial_services", "outbound", "book a meeting with sales leaders")
            return re_, fin

    re_, fin = asyncio.run(go())
    assert 1 <= len(re_) <= 3 and re_[0]["slug"] in ("expired_listing_followup", "real_estate_sdr")
    assert fin[0]["slug"] == "corporate_sales_equipment_finance"
    assert all("original_text" not in p for p in re_ + fin)


def test_identity_check_passes_when_model_words_company_differently(client, monkeypatch):
    """Regression: the model paraphrasing the business name (or AI disclosure being off) used to fail the gate."""
    data = copy.deepcopy(DRAFT)
    data["business"]["name"] = "Blacksync AI LLC"
    data["behavior"]["ai_disclosure"] = False
    strategy = copy.deepcopy(STRATEGY)
    strategy["identity"]["company_context"] = "A solar installer in Tucson offering free assessments."
    strategy["identity"]["role"] = "an assistant who follows up on solar quotes."
    _route_chat(monkeypatch, strategy=strategy)
    _, status = _generate(client, data)
    assert status["status"] == "done", status
    agent = client.get(f"/api/agents/{status['agent_id']}").json()
    assert "You represent Blacksync AI LLC." in agent["builder"]["sections"]["identity"]


# ── Build With AI v3: specialty, name, mission, launch ────────────────────────


def test_catalog_lists_specialties_per_industry(client):
    sp = client.get("/api/agent-builder/catalog").json()["specialties"]
    re_labels = [s["label"] for s in sp["real_estate"]]
    assert re_labels[:2] == ["Real Estate ISA", "Expired Listings"] and 5 <= len(re_labels) <= 7
    hs = {s["key"]: s for s in sp["home_services"]}
    assert hs["inbound_answering"]["direction"] == "inbound" and hs["missed_call_recovery"]["direction"] == "outbound"
    assert all(5 <= len(v) <= 7 for v in sp.values())


def test_generated_agent_has_separate_name_and_specialty_and_starts_paused(client, monkeypatch):
    _route_chat(monkeypatch)
    data = copy.deepcopy(DRAFT)
    data.setdefault("goal", {})["specialty"] = {"key": "custom_badge", "label": "Solar Callbacks", "use_cases": []}
    _, status = _generate(client, data)
    assert status["status"] == "done", status
    agent = client.get(f"/api/agents/{status['agent_id']}").json()
    assert agent["specialty"] == "Solar Callbacks" and agent["status"] == "paused"
    # An editor save re-sends the current label: that must not lock it.
    r = client.patch(f"/api/agents/{agent['id']}", json={"specialty": "Solar Callbacks"}).json()
    assert r["specialty"] == "Solar Callbacks" and r["specialty_custom"] is False
    assert "–" not in agent["name"] and agent["name"] == STRATEGY["agent_name"]

    # A person's label sticks (and is marked custom); clearing it falls back to the inferred one.
    r = client.patch(f"/api/agents/{agent['id']}", json={"specialty": "Buyer Callbacks"}).json()
    assert r["specialty"] == "Buyer Callbacks" and r["specialty_custom"] is True
    r = client.patch(f"/api/agents/{agent['id']}", json={"specialty": ""}).json()
    assert r["specialty_custom"] is False

    # Launch is refused while something blocks calls (no voice service in tests) and the agent stays paused.
    r = client.post(f"/api/agent-builder/agents/{agent['id']}/launch")
    assert r.status_code == 409 and "Voice service" in r.json()["detail"]
    assert client.get(f"/api/agents/{agent['id']}").json()["status"] == "paused"


def test_launch_goes_live_when_ready(client, monkeypatch):
    from app.agent import generator

    _route_chat(monkeypatch)
    _, status = _generate(client)
    monkeypatch.setattr(generator, "readiness", lambda agent, org: {"ready": True, "checks": [
        {"key": "voice", "label": "Voice service", "status": "ok", "detail": ""}]})
    r = client.post(f"/api/agent-builder/agents/{status['agent_id']}/launch")
    assert r.status_code == 200 and r.json()["status"] == "active"


def test_mission_suggestion_uses_ai_and_falls_back(client, monkeypatch):
    async def fake_chat(payload, timeout=45.0):
        return _reply(json.dumps({"mission": "Call homeowners whose listings expired and book a listing appointment."}))

    monkeypatch.setattr(llm, "_chat", fake_chat)
    data = {"business": {"name": "Acme Realty", "industry": "real_estate"},
            "goal": {"specialty": {"key": "expired_listings", "label": "Expired Listings", "use_cases": ["expired_listings"]}}}
    draft = client.post("/api/agent-builder/drafts", json={"data": data, "step": 3}).json()
    r = client.post(f"/api/agent-builder/drafts/{draft['id']}/mission").json()
    assert r == {"mission": "Call homeowners whose listings expired and book a listing appointment.", "source": "ai"}

    async def broken(payload, timeout=45.0):
        raise RuntimeError("down")

    monkeypatch.setattr(llm, "_chat", broken)
    r = client.post(f"/api/agent-builder/drafts/{draft['id']}/mission").json()
    assert r["source"] == "template" and r["mission"]


def test_funeral_homes_get_the_house_opener():
    from app.agent.pipeline import recommended_opener

    spec = {"strategy": {"agent_name": "Grace"}}
    ctx = {"business": {"name": "Hillside Funeral Home", "industry": "funeral_services"}, "direction": "inbound"}
    assert recommended_opener(ctx, spec) == (
        "Hi, thank you for calling Hillside Funeral Home. This is Grace, a virtual assistant here to make sure we "
        "get your call. Who do I have the pleasure of speaking with?")
    assert recommended_opener({**ctx, "direction": "outbound"}, spec) is None  # aftercare calls go out
    assert recommended_opener({**ctx, "business": {"name": "X", "industry": "real_estate"}}, spec) is None
