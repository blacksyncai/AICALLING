# Radar custom automations

For the expanded shared CRM tools and current provider capability matrix, see [CRM assistant](crm-assistant.md).

Radar now has Discover and Automations views. Existing scan plays remain available.
Owners/admins with the existing Radar entitlement can draft bounded rules in chat,
edit rules manually, preview transcript evidence, save drafts, and activate them.
Draft generation and preview perform reads only. Only explicit resource creation
or active rule execution changes CRM data. Nothing launches a call.

## Supported scope

- Source: agent, campaign, and Follow Up Boss pond (optional filters).
- Condition: name confirmed, named voicemail, wrong number, unverified; existing
  call outcome; or a public extracted field (equals, contains, exists).
- Actions: add to a BlackSync pond; assign a linked FUB person to a CRM pond;
  add a FUB tag preserving existing tags; or use an existing CRM stage adapter.
- Resource creation: internal BlackSync ponds; FUB ponds, person stages, and
  deal pipelines. A deal pipeline is a separate CRM object, not a person stage.
- Close, HubSpot and Pipedrive also expose their existing native pipeline/stage
  creation adapters through the CRM assistant. Other CRMs reuse supported stage
  adapters. Arbitrary executable integrations are not provided.

## Verification

Verification is phone-specific evidence from callee transcript turns. Conservative
English name checks require an explicit expected-first-name question plus an
unambiguous response, or direct self-identification. Ambiguous replies are unverified.
Named voicemail is separate from live name confirmation. This is evidence of a
stated identity, not proof of legal identity. Call duration, a positive outcome,
and assistant statements alone cannot establish verification. Review the actual
quoted evidence in preview before activation. Multilingual identity extraction is
not implemented. Wrong-number rules can route/tag records; this does not change
the global dialer suppression policy.

## Persistence and execution

Five additive tables are registered with the existing create_all startup:
radar_ponds, radar_pond_members, radar_verifications, radar_automations,
radar_executions (see model for actual table names).
Call analysis enqueues work in a savepoint; enqueue failures cannot discard analysis.
The worker reconciles missing eligible completed calls every 20 seconds. Calls must
have started after activation; historical matching calls require explicit selection.
Editing an active rule produces a new draft version and pauses its automation.

Jobs use an atomic claim, five-minute leases, bounded retries, unique rule/version/
call keys, immutable specs, and per-action progress checkpoints. State-setting
CRM actions check their current destination on retry. This provides retry-safe
reconciliation, not a distributed exactly-once guarantee. DNC, organization access,
active entitlement, rule version, and resource ownership are checked at execution.
Completed/closed CRM stages follow the provider's existing forward-only guards.
RUN_STARTUP_JOBS=0 disables the new worker in tests/local inspection.

## Validation and rollout

Run from repository root:

```sh
python -m pytest -q backend/tests
npm --prefix web ci
npm --prefix web run build
```

Browser validation uses the real component in a separate local review harness with
mocked API responses, never private customer data. Screenshots show sample data.
Checks cover chat/draft, evidence preview, save/activate, selected historical routing,
and responsive widths 320, 390, 768, 1440.

No live FUB write or production deployment was performed. Official FUB documentation
was blocked by this environment's network policy. Resource endpoints were cross-
checked against published Follow Up Boss SDK/MCP tooling and tested with mocked
HTTP responses, not a live FUB account. Before release, validate GET/POST ponds,
stages and pipelines and PUT people assignedPondId/tags with a permitted test FUB
account; actual account permissions and endpoint availability may differ. Test
PostgreSQL multi-worker lease contention before enabling concurrent workers.
The chat path uses the existing configured LLM; external LLM generation was mocked
in tests. No new keys, Stripe products, or billing terms are introduced.

Deploy backend and frontend together after review. Leave all new rules as drafts;
activate one narrowly scoped test rule only after reviewing its evidence and destination.

## Mascot composer

The Radar chat uses `web/src/components/ui/ai-mascot-input.tsx`. The frontend already
has TypeScript, Tailwind 4 (styles in `web/src/app/globals.css`), the `@/*` alias,
and shared components under `web/src/components`. The `ui/` directory keeps reusable
components separate from feature-specific screens; the existing `ui.tsx` exports
remain intact. No shadcn initialization or global CSS reset is needed.

The design adapts the supplied mascot input using the installed `motion/react`
and `lucide-react` packages. It needs no new dependency or external image/font.
Radar passes controlled request text, busy state, and its existing draft callback.
Enter submits; Shift+Enter inserts a line; IME composition does not submit. The
component honors reduced motion, blocks duplicate sends, and preserves failed
requests. There is no simulated dictation or fake processing delay.

The microphone uses the browser's SpeechRecognition service when available;
a browser may send audio to its speech provider. Unsupported browsers disable the
control; permission denial shows an error and preserves the prompt. Speech input
is optional and never auto-submits. Unmounting/stopping aborts recognition.
Model/reasoning selection, attachments, and web search are omitted because the
Radar draft endpoint does not accept those options. The existing server-side LLM
configuration remains unchanged. Browser tests exercise speech callbacks with a
mock; real microphone capture depends on browser support and user permission.
