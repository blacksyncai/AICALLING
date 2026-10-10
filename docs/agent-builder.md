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
| POST | `/generate` | `{draft_id}` | `{agent_id}` — creates a real `Agent` in the org |

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
and outbound use cases plus a `custom` one. Integration statuses must be truthful: only
things that work in this app today are `available` (Cal.com booking when configured,
warm transfer, webhooks/Zapier, CSV import); named CRMs are `coming_soon`.

Draft `data` (all optional while in progress):
```json
{"business": {"name", "industry", "website", "description"},
 "goal": {"direction": "outbound|inbound|both", "use_case": "buyer_follow_up", "answers": {"lead_age": "New leads"}},
 "behavior": {"agent_name", "voice_id", "language": "en", "style": "friendly",
              "qualification_depth": "light|standard|thorough",
              "booking": true, "transfer_number": "", "transfer_when": "",
              "callback": true, "ai_disclosure": true},
 "integrations": {"selected": ["calcom", "webhooks"]}}
```

Generation writes `Agent.system_prompt` (sections joined with headings), `first_message`,
`knowledge_base` (from `knowledge_text`), `extraction_fields` (lead_intent, timeline,
key_objections, next_action + use-case fields), `success_criteria`, `enable_booking`,
`transfer_number`, `voice_id`, `language`, `llm_model` ("gpt-4.1"), `ai_disclosure`, and
`builder = {industry, use_case, direction, style, draft_id, sections: {identity, reason,
flow, qualification, objections, knowledge, booking, transfer, voicemail, callback,
closing, compliance}}`. Requires OPENAI_API_KEY (400 with a plain message otherwise).

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
