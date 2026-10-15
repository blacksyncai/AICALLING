# Radar custom automations

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
- Other CRMs reuse the existing supported stage adapters. New generic CRM
  resource-creation APIs and arbitrary executable integrations are not provided.

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
