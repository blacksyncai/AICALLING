# Radar CRM assistant

Radar's existing chat now proposes one-time CRM tools as well as reusable post-call
automations. A model never gets arbitrary HTTP or executable-code access. Provider
credentials remain server-side, and actual requests use existing native/Nango
adapters. Auth, organization boundaries, Radar entitlements and owner/admin gates
are preserved.

## Current capability matrix

All 11 CRM adapters support a bounded contact page, exact phone/email lookup,
and find-or-create contact. Queries filter only within the returned page and do
not claim exhaustive search results. A create request may reuse an existing record.

| CRM | Pipeline/stage reads and forward-only moves | Pipeline creation / add stages | Native notes | Other one-time tools |
| --- | --- | --- | --- | --- |
| Close | Yes | Yes / yes | Yes | — |
| HubSpot | Yes | Yes / yes | — | — |
| Pipedrive | Yes | Yes / yes | — | — |
| Follow Up Boss | Person stages | Deal pipelines with embedded stages / yes | Yes | Ponds, person stages, follow-up tasks, DNC, mapped fields |
| GoHighLevel | Yes | — | Yes | DNC |
| Salesforce | — | — | — | DNC |
| Zoho CRM | — | — | Yes | — |
| Attio | — | — | Yes | — |
| BoldTrail / kvCORE | — | — | — | — |
| Lofty | — | — | — | Mapped fields |
| Sierra Interactive | — | — | Yes | Mapped fields |

These capabilities reflect implemented adapters, not guaranteed permissions on a
customer's subscription or token. The UI shows the selected provider's supported
actions. CRM resource reads can return warnings when account permissions prevent
access. Slack and Google Sheets remain separate notification/sheet integrations.

## Flow

1. Ask for a query, a one-time CRM change, or an automation in the existing chat.
2. Missing IDs or ambiguous people require a read first. Read results remain in
   the organization's CRM-action history and are available as bounded chat context.
3. The chat produces immutable, typed proposal cards. No CRM write occurs during
   drafting. Each proposal lists the provider, action, and exact arguments.
4. New write proposals open a confirmation dialog automatically with Cancel and
   Confirm and continue. Read tools have an explicit Run action. Confirmation is
   required by the backend, not just by the button. Typing yes reopens the pending
   proposal's dialog without generating or executing another command.
5. Successful results are cached against that command ID. Repeated execution of
   the same ID returns its receipt without issuing the write again.

Proposals expire after 30 minutes. A connection fingerprint invalidates drafts
when credentials/account/config change. Executing also rechecks active workspace,
manager access, Radar entitlement, org/connection ownership and actual pipeline
IDs/stage membership. The assistant cannot move a record backward through a
protected pipeline or create a deal as a side effect of stage movement.

Atomic draft-to-running claims prevent concurrent execution of one command. A
remote timeout or failed write leaves an `uncertain` receipt; the UI asks the
user to inspect the CRM before proposing another write. No automatic write retry
is added. If the process stops during execution, the running receipt stays visible
for reconciliation. This does not promise distributed exactly-once delivery or
cross-request natural-language deduplication. Different proposals are independent.

Native note tools write notes only: they do not fabricate a completed phone call.
DNC tools also suppress matching imported contacts in the same BlackSync org.
No deletion, unrestricted bulk updates, arbitrary field writes, email/SMS sending,
new dialing, billing administration, or arbitrary endpoints are exposed.

## Examples

- “Find the Close lead with email person@example.com.”
- After inspecting the returned ID: “Add this note to lead_123: Asked us to call next week.”
- “Create a Close pipeline called Test with New (active), Working (active), Won
  (won), and Lost (lost).”
- “Add a stage called Follow-up (active) to pipeline pipe_123.”
- “List 25 contacts.” Results are explicitly a bounded page.

Close, HubSpot and Pipedrive use their existing install_pipeline adapters to
create/reuse pipeline names and add requested stages. The resource manager also
accepts explicit stage names for these CRMs. Existing pipelines, records and
stage mappings are preserved. Follow Up Boss ponds/person stages/deal pipelines
remain distinct resource types.

## Validation and release limits

Tests use disposable SQLite and HTTP/provider mocks; no live CRM account was
written, no customer automation was activated, and production was not deployed.
The external LLM response is mocked in tests. Provider integration tests exercise
the real existing Close pipeline adapter and each enabled native note path.
Contact-tool delegation and the capability matrix cover all eleven CRM providers.

Frontend production build and typecheck pass. Browser tests with the actual UI
and labeled sample responses cover write-preview cancellation, explicit confirmation,
read-query results, history, explicit Close pipeline stages and responsive widths
320, 390, 768, 1440.

The full backend run had 431 passed and two timing-sensitive failures in unchanged
billing/idempotency and speed-to-lead tests. The billing test's second report
crossed a second boundary (the existing handler recomputes duration but does not
rebill); the CRM test's module-import NOW + 1 minute was older than its configured
since timestamp by the time it ran. Both passed in the isolated diagnostic run.
The final CRM-focused run is recorded in the review artifacts. No billing/dialing
code or existing test assertions were changed to make these pass.

Before deployment, validate each enabled write with a permitted test CRM account
and exercise claim contention on PostgreSQL. Existing FUB resource endpoints have
not yet been live-validated (see radar-automations.md). Additional CRM actions can
be added as typed tools with provider-specific payloads and tests; providers do
not automatically gain every action another CRM supports.

Follow Up Boss embedded-stage details and validation limits are documented in
[fub-pipelines.md](fub-pipelines.md). Chat requests now preserve both user and
assistant turns so names/stages supplied in later messages retain context.
