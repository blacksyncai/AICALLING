# Agent builder — API contract

The "Build with AI" flow: an organization-level **business profile + knowledge base**
(reusable by every agent), a resumable **wizard draft**, **generation** of a real agent,
and editor tools (**improve with AI**, **regenerate a section**, **launch readiness**).
All routes are org-scoped (`ctx: CtxDep`); nothing crosses accounts.

Models live in `backend/app/models/builder.py` (`BusinessProfile`, `KnowledgeRevision`,
`AgentDraft`) plus `Agent.builder` (JSON) and `Agent.ai_disclosure` (bool).

## Knowledge base shape (`BusinessProfile.knowledge`)

```json
{"sections": [
  {"key": "overview", "title": "Company Overview", "items": [
    {"id": "k_8f2a…", "text": "Family-owned HVAC company serving Austin since 1998.",
     "source_url": "https://acme.com/about", "origin": "website", "needs_review": false}
  ]}
]}
```

Section keys (always present, in this order): `overview` Company Overview, `services`
Services and Products, `locations` Locations and Coverage, `team` Team Members,
`hours` Business Hours, `pricing` Pricing and Policies, `faqs` FAQs, `custom` Custom Instructions.
`origin` is `website` | `manual` | `upload`. Items the user added or edited are `manual`
and are never removed or changed by a rescan. `needs_review` flags facts the analyzer was
unsure about.

## Business profile — `backend/app/routers/business_profile.py` (prefix `/api/business-profile`)

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `` | – | Profile (below). Always 200; an unsaved profile has `exists: false` and empty sections. |
| PUT | `` | `{name?, industry?, website?, description?, auto_refresh_days?}` | Profile |
| POST | `/analyze` | `{website?}` | Profile with `status: "analyzing"`; work continues in the background |
| PUT | `/knowledge` | `{sections}` (full knowledge shape) | Profile; saves a revision first; changed/new items become `origin: "manual"` |
| POST | `/knowledge/upload` | `{filename, text}` (text extracted client-side; .txt/.md/.csv) | Profile; extracted facts added with `origin: "upload"` |
| POST | `/rescan` | – | Profile with `status: "analyzing"`; when done, differences land in `pending_changes` (never touching `manual` items) |
| POST | `/changes/apply` | `{ids: [...]}` (empty = all) | Profile; revision saved |
| POST | `/changes/dismiss` | `{ids: [...]}` (empty = all) | Profile |
| GET | `/revisions` | – | `{revisions: [{id, summary, created_at}]}` (newest first, 30 max) |
| POST | `/revisions/{id}/restore` | – | Profile |

Profile JSON:
```json
{"exists": true, "name": "", "industry": "home_services", "website": "", "description": "",
 "status": "idle|analyzing|ready|limited|failed", "progress_step": 0-3 or null,
 "progress_label": "Exploring your website" | "Understanding your business" |
                   "Identifying services and team details" | "Preparing your knowledge base" | null,
 "error": null or plain-language reason (e.g. site blocks automated visits),
 "pages": [{"url", "title"}], "knowledge": {...}, "pending_changes": [...],
 "auto_refresh_days": null|7|30, "scanned_at": iso|null, "item_count": 12, "review_count": 2}
```

Website analysis: fetch the homepage + up to ~8 same-site pages whose links look like
about/services/team/faq/contact/locations/pricing/hours; public addresses only (reuse
`app.services.accounts.is_public_url`), no redirects to other hosts, size/time limits,
honest failure messages. Page text is **untrusted data**: the LLM prompt must say so and
must never follow instructions found in it. LLM returns schema-validated JSON (OpenAI JSON
mode via `app.services.llm._chat`); every fact carries the `source_url` it came from;
missing facts are left out, never invented. `knowledge_text(profile)` (plain text, grouped by
section) is exported for agent generation.

## Agent builder — `backend/app/routers/agent_builder.py` (prefix `/api/agent-builder`)

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/catalog` | – | Catalog (below) |
| GET | `/drafts` | – | `{drafts: [{id, step, data, updated_at, agent_id}]}` (unfinished first) |
| POST | `/drafts` | `{data?, step?}` | Draft |
| GET/PATCH/DELETE | `/drafts/{id}` | PATCH `{step?, data?}` (data replaces) | Draft |
| POST | `/assist` | `{draft_id}` | Assist response (below) — reads the saved draft, never writes it |
| POST | `/generate` | `{draft_id}` | 202 + generation status — starts the background pipeline (see below) |
| GET | `/drafts/{id}/generation` | — | `{status: idle\|running\|failed\|done, stage, stages, error, agent_id}` |
| GET/POST | `/drafts/{id}/references` | `{filename, content_base64}` or `{name, text}` | customer scripts (PDF/DOCX/TXT/paste), org-scoped, max 5 |
| DELETE | `/references/{id}` | — | 204 |

Catalog:
```json
{"industries": [{"key": "real_estate", "label": "Real Estate", "icon": "home"}, ...],
 "use_cases": {"real_estate": [
   {"key": "buyer_follow_up", "label": "Buyer Lead Follow-Up", "direction": "outbound",
    "description": "…", "objectives": ["…"], "qualification_questions": ["…"],
    "actions": ["book_appointment", "transfer", "callback"],
    "followups": [{"key": "lead_age", "label": "Are these new leads or existing contacts?",
                   "type": "choice", "options": ["New leads", "Existing contacts", "Both"], "default": "New leads"},
                  {"key": "ask_budget", "label": "Ask about budget?", "type": "boolean", "default": true}]}
 ], ...},
 "styles": [{"key": "friendly", "label": "Friendly and Conversational", "description": "…"}, ...],
 "integrations": [{"key": "calcom", "label": "Calendar booking (Cal.com)", "category": "scheduling",
                   "status": "available" | "needs_setup" | "coming_soon", "detail": "…"}, ...]}
```
Industries: real_estate, mortgage, home_services, healthcare, insurance, financial_services,
recruiting, logistics, automotive, professional_services, other. Every industry has inbound
and outbound use cases ("presets") plus a `custom` one labelled **Create Your Own**.
Real estate outbound presets, in display order: Buyer Lead Follow-Up (`buyer_follow_up`), Seller
Lead Follow-Up (`seller_follow_up`), Speed to Lead (`speed_to_lead`), FSBO Prospecting, Expired
Listings, Circle Prospecting, Lead Reactivation (`lead_reactivation`), Appointment Setting
(`appointment_setting`), General Prospecting (`cold_prospecting`), then Past Client Check-Ins and
Appointment Confirmation. Keys never change; renames are handled with `use_case_aliases`
(e.g. `general_prospecting` → `cold_prospecting`, `create_your_own` → `custom`), which the catalog
also returns and `catalog.get_use_case()` resolves. Followups are now hints for the assistant;
the wizard no longer shows them as a form (answers in older drafts are still honored). Integration statuses must be truthful: only
things that work in this app today are `available` (Cal.com booking when configured,
warm transfer, webhooks/Zapier, CSV import); named CRMs are `coming_soon`.

Draft `data` (all optional while in progress):
```json
{"v": 2,
 "business": {"name", "industry", "website", "description"},
 "goal": {"direction": "outbound|inbound|both",
          "use_cases": ["seller_follow_up", "expired_listings", "custom"],
          "use_case": "seller_follow_up",
          "custom": {"description": "Call homeowners who requested a valuation…", "audience": "Homeowners",
                     "tone": "Friendly and conversational", "outcome": "Warm transfer"},
          "extra_instructions": "Be casual, avoid sounding like a salesperson…",
          "assistant": [{"id": "lead_source", "question": "Where do these leads come from?", "answer": "Zillow",
                         "skipped": false, "delegated": false, "suggestions": ["Website", "Zillow"], "reason": "…"}],
          "understanding": "Got it. I'll build an agent focused on …", "recommendation": null, "ready": true,
          "assist_rounds": 1, "assist_basis": "<client fingerprint of the goal last reviewed>",
          "answers": {"lead_age": "New leads"}},
 "behavior": {"decide_later": true, "agent_name", "voice_id", "language": "en", "style": "friendly",
              "custom_style", "qualification_depth": "light|standard|thorough",
              "booking": true, "transfer_number": "", "transfer_when": "",
              "callback": true, "ai_disclosure": true},
 "integrations": {"selected": ["calcom", "webhooks"]}}
```
- `use_cases` is the ordered multi-select (first preset = primary); `custom` in it means "Create your
  own". `use_case` is kept = the primary for older readers. Older drafts with only `use_case` (+
  `answers`, where `custom_goal` / `custom_questions` / `contact_type` held the custom goal) still work.
- A custom description counts only while `custom` is selected or no preset is (leftover text from a
  deselected "Create your own" is ignored).
- `assistant` items: `answer: null` + `skipped: false` = still pending; `delegated: true` (answer
  "You decide") = the user lets the AI pick the best practice.
- `behavior.decide_later: true` ("I'll decide later"), or no behavior chosen at all, means
  recommended defaults: default voice, `gpt-4.1`, booking on only if the presets allow it **and**
  Cal.com is configured, no transfer, callbacks + AI disclosure on, standard depth, style from the
  user's tone (else friendly), agent name picked by the AI.
- Wizard steps (`draft.step`): v2 = 1 Business, 2 Goal (+ AI assistant), 3 Fine-tune (optional), 4 Review,
  5 Done. Drafts without `v` used 1 Business, 2 Goal, 3 Personality, 4 Tools, 5 Review, 6 Done and are
  remapped on resume (3,4 → 3; 5,6 → 4). The API still accepts steps 1–6.

Validation for `/generate` (400, plain message): business name, a listed industry, and at least one
listed preset **or** a custom description of 15+ characters ("other" industry + custom only is fine).

### Assist — `POST /api/agent-builder/assist`

Reads the saved draft (the client saves first), so it sees business info, presets, custom fields,
extra instructions and the Q&A so far. Same goal validation as generate, but business name/industry
are optional. Response:
```json
{"understanding": "Got it. I'll build an agent focused on …",
 "questions": [{"id": "lead_source", "question": "Where do these leads come from?",
                "suggestions": ["Website", "Zillow", "Mailers"], "reason": "Shapes the opener."}],
 "ready": false, "recommendation": "optional tip or null",
 "irrelevant": ["ids of earlier answers that no longer fit the goal"], "rounds_left": 1}
```
The LLM output is validated strictly (understanding required, `ready` boolean, 2–4 suggestions per
question), retried once, else 502; no OpenAI key → 400. The server then drops questions whose topic
was already answered/skipped (by id or wording) or filled in the custom fields (audience, tone,
outcome), and caps them: ≤ 3 per round, ≤ 5 asked in total, and none once `goal.assist_rounds ≥ 2`.
No questions left ⇒ `ready: true`. The client stores the conversation in `goal` (above), resets
`assist_rounds` and drops pending questions when the goal changes, and lets the user generate at any
time ("We'll use smart defaults for the rest").

The generation prompt receives every selected preset (primary first, with objectives, questions,
actions), the custom description/audience/tone/outcome, extra instructions, the answered Q&A
("You decide" → choose the best practice; skipped → sensible default) and the behavior settings.
The model returns `agent_name`, `title`, `primary_objective`, `target_audience`,
`qualification_questions[]`, `desired_outcomes[]`, `transfer_rules`, `booking_rules`,
`follow_up_logic`, `first_message`, the 12 `sections`, `extraction_fields`, `success_criteria`
(validated strictly, retried once).

Generation writes `Agent.system_prompt` (sections joined with headings), `first_message`,
`knowledge_base` (from `knowledge_text`), `extraction_fields` (lead_intent, timeline,
key_objections, next_action + use-case fields), `success_criteria`, `enable_booking`,
`transfer_number`, `voice_id`, `language`, `llm_model` ("gpt-4.1"), `ai_disclosure`, and
`builder = {industry, use_case (primary, or "custom"), use_cases, direction, style, draft_id,
business_name, persona, transfer_enabled, transfer_when, callback, integrations,
sections: {identity, reason, flow, qualification, objections, knowledge, booking, transfer,
voicemail, callback, closing, compliance},
plan: {title, primary_objective, target_audience, qualification_questions, desired_outcomes,
transfer_rules, booking_rules, follow_up_logic, use_cases, request: {description, audience, tone,
outcome, extra_instructions}, assistant: [{question, answer, delegated}], recommended_settings}}`.
When booking/transfer are off, `plan.booking_rules` / `plan.transfer_rules` say so deterministically.
Agent name: `"{persona} – {label}"`, where label is the preset label (`"… (customized)"` with own words), `"{primary} + N more"`, or the
AI's `title` for custom-only agents. Requires OPENAI_API_KEY (400 with a plain message otherwise).

## Agent editor helpers (same router file, prefix `/api/agent-builder`)

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/agents/{id}/improve` | `{instruction}` | `{summary, system_prompt, first_message, sections?}` — a proposal only; the client applies it with `PATCH /api/agents/{id}` (send `system_prompt`, `first_message`, and `builder` if sections changed) |
| POST | `/agents/{id}/regenerate` | `{section, instruction?}` | `{section, text}` proposal |
| GET | `/agents/{id}/readiness` | – | `{ready, checks: [{key, label, status: "ok"|"warning"|"blocker", detail, fix_href?}]}` |

Readiness checks: prompt + first message present (blocker), voice service configured
(blocker for calls), phone line configured (warning for inbound-only / blocker for outbound),
calling credits (blocker at 0 unless unlimited), booking enabled but calendar not configured
(warning), transfer configured without number (blocker), knowledge base empty (warning),
AI disclosure off (warning), account suspended (blocker).

`PATCH /api/agents/{id}` accepts `builder` and `ai_disclosure` too.

## Call outcomes

`CALL_OUTCOMES` gains `wrong_number` and `do_not_call`. A call ending in `do_not_call`
sets the contact's `do_not_call = True`. Post-call analysis always extracts
`lead_intent`, `timeline`, `key_objections`, `next_action` in addition to agent fields.


## Production generator (`app/agent/pipeline.py`)

The old generator asked for a single JSON answer. It had to hold all 12 sections and the call plan, each section was
"a few sentences" with a 2,500-character limit, and nothing checked depth or `finish_reason`. That is why agents came
out as two- or three-sentence descriptions. Generation now runs as a background job:

1. **Context.** The pipeline gathers:
   - the business profile, with a source for every fact (`[K#] … (source: url)`), and the wizard answers;
   - the customer's own reference documents;
   - the real contact fields (base fields plus the org's custom CSV columns) and the real tools;
   - the pattern cards of 1–3 relevant internal playbooks.

   The original playbook scripts are never included.
2. **Purpose.** The preset decides what kind of call this is (`spec.purpose_for`): `prospecting`, `reactivation`,
   `client_follow_up` or `inbound`. For a custom goal, the model picks one. The purpose sets which situations the
   flow plans for (`spec.required_branches`) and how many questions it may ask (prospecting 1–4, reactivation
   1–3, client follow-up 0–2, inbound 1–4).
3. **Spec.** The spec comes from two schema-validated model calls (`app/agent/spec.py`): *strategy* first, then
   *conversation*, each with a 6k output-token budget.
   - Invalid output goes back to the model with the exact validation error.
   - When `finish_reason == "length"`, the call is retried with double the budget, up to 32k.
   - `exact_wording` holds lines the user supplied (an opening, an offer, a price). Each must appear word for word
     in the user's own input, or it's rejected. The user's opening becomes the first message unchanged.
   - Generic rules the runtime already adds (AI disclosure, do-not-call, "one question at a time" …) are dropped
     from `compliance`, `representation_rules` and `habits`.
   - `meeting_booked` is refused without a calendar. Outcomes the platform detects itself (voicemail, no answer)
     are dropped.
4. **Composer** (`app/agent/composer.py`). Turns the spec into up to seven short sections (`SECTIONS_V3`):
   - Identity and Objective
   - What You Know
   - Approved Wording (only when the user supplied some)
   - Opening
   - Conversation Flow (stages, the next step and when to offer it, purpose-specific situations)
   - Questions and Objections
   - Actions and Boundaries (honest transfer, booking and callback rules, plus the outcome list)

   A question the conversation already scripts isn't listed again. The generated voicemail is saved to the agent's
   voicemail message; it's spoken only when that setting is "leave a message".
5. **Quality gate** (`app/agent/quality.py`). Checks that:
   - the identity names the agent and company, and the opening says who's calling;
   - the purpose's required situations are covered and no question is scripted twice;
   - approved wording is kept exactly;
   - there are no booking or transfer claims the agent can't keep, and only real tools and contact fields;
   - nothing from a playbook's `private_terms` appears, no foreign URLs or endpoints, and no credentials.

   Length only produces a warning (above 1,300 words). When a check fails, the affected half of the spec goes back
   to the model for repair, at most twice. If it still fails, the job ends with a clear error.
6. **Save.** Saves the agent with `builder.schema = "v3"`, `purpose`, `section_order`, `sections`, `spec`,
   `quality` and the playbook versions used, plus an `AgentVersion` snapshot. Booking is enabled only when a real
   calendar is connected; otherwise `booking_requested` makes readiness warn.

Agents generated before v3 (`schema = "v2"`, twelve sections) are not migrated. Their prompts are kept as they are,
and section edits and regeneration keep their twelve-section layout.

### What the voice model receives (`app/agent/runtime.build_instructions`)

The static parts come first, so providers can cache the prefix:
1. The agent's prompt, with `{{fields}}` filled in.
2. **How to talk on this call.** The conversation rules every agent gets, stated once:
   - respond first, then one question at a time;
   - never re-ask something already said;
   - handle interruptions without restarting;
   - move on once they're ready;
   - handle do-not-call and wrong numbers;
   - be honest about being an AI, and never speak instructions out loud.
3. **Staying on topic**, and the "built on BlackSync" answer.
4. **Tools.** Only the enabled ones, plus what the agent can't do. A tool only "worked" if it returned success.
5. **Business reference.** The knowledge base, framed as reference material that can't change the agent's
   behavior.
6. **Contact details.** The fields that are filled in, plus a "Not on file" line for any field the prompt uses but
   this contact lacks.
7. CRM notes, then today's date and the upcoming dates (14 days with booking, otherwise 7).

On outbound calls, a saved first message that can't be said without a missing detail ("Is this {{name}}?" with
no name) is replaced by an opening the agent writes from its prompt. "Hi {{name}}," still works and becomes
"Hi there,".

Sample output for a fictitious business: [agent-generator-sample.md](agent-generator-sample.md).

### Internal playbook library (admin only)

`/api/admin/playbooks` lets admins:
- list, read, update tags, title and active state, and roll back to an earlier version;
- add a version, which saves the pattern card and private terms;
- create a new playbook.

Each version keeps the original script verbatim. The three bundled scripts are installed once at startup by
`app/services/playbooks.py`. They are never turned into customer agents.

### Prompt versions

Every saved change to an agent's prompt, first message or sections creates an `AgentVersion`. Agents that existed
before this feature get an "original" baseline on their first edit. The endpoints are:
- `GET /api/agents/{id}/versions`
- `GET /api/agents/{id}/versions/{vid}`
- `POST /api/agents/{id}/versions/{vid}/restore`
