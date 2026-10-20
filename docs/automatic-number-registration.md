# Automatic caller identity registration

## Delivered scope and current limits

SignalWire CNAM has a real HTTP client, transactional number-assignment outbox, background lease/retry worker, provider receipts, status polling, applied-CNAM confirmation and lifecycle cleanup. Customer status is a small line beside each number. Existing customer scripts, voices and call routing are unchanged.

**Hiya and First Orion HTTP integrations are NOT implemented in this change.** Their official documentation endpoints were denied by the execution environment's domain policy, and no approved partner credential bindings were found in the configured server variables. Jobs explicitly record the partner-credentials/API-contract prerequisite; they do not generate business IDs, request IDs, verification statuses or success. `registration_businesses` provides storage for future verified provider business receipts and currently stores manually submitted SignalWire carrier-order references only. No Hiya Create Business, Create Phones, First Orion business/number registration or partner removal API is claimed to work.

Documentation/API domains were added to the environment configuration draft (existing domains preserved): signalwire.com, developer.hiya.com, protect.api.hiyaapi.com, developer.firstorion.com. The environment tool reports `requires_publish: true`; saving the draft does not apply it to this running environment. Official partner auth, request/response schemas, polling and removal endpoints must be verified after access is applied before completing those adapters. Do not substitute a guessed endpoint, customer login, CSV, browser automation or another provider's API.

## Existing architecture and integration points

- FastAPI, async SQLAlchemy, Postgres production / SQLite tests; additive startup migration in `app.database.create_all_tables`.
- `telephony.purchase` and `import_owned` enqueue work in the same transaction as the assigned PhoneNumber. Stripe webhook and admin/self-serve flows already converge here. Carrier purchase happens first; registration HTTP never runs in the purchase request.
- The existing startup background-loop architecture runs the durable outbox. `NUMBER_REGISTRATION_WORKER_ENABLED=false` pauses execution while preserving queued work. `RUN_STARTUP_JOBS=false` also disables it.
- Assignment identity includes number row ID, tenant and assignment timestamp. Released rows reused for another tenant receive separate registration records; old caller identity must be removed before the new assignment can publish its name.
- Release and reassignment persist cleanup. A periodic repair pass catches missing enqueue/cleanup events. Account deletion is blocked while submitted caller identity cleanup remains outstanding so the queue cannot be deleted prematurely.

## Authorization and prerequisites

Existing organization/profile names and website-derived descriptions are **suggestions, not approved registration details or verified businesses**. Read them using `GET /api/phone-numbers/registration/business`. Before any submission, a manager must provide one-time documented consent for current and future assigned numbers through `POST /api/phone-numbers/registration/authorization`:

```json
{
  "legal_name": "Acme Plumbing LLC",
  "caller_name": "Acme Plumbing",
  "business_details": {"website": "https://example.com"},
  "providers": ["signalwire_cnam"],
  "fees_authorized": ["signalwire_cnam"],
  "registration_authorized": true,
  "evidence": "Reference to the customer's signed authorization"
}
```

The API captures authenticated tenant, actor, time, terms version, approved name, provider scopes and fee authorization. Identical consent requests reuse the record; changed consent creates an audit revision. `DELETE .../authorization` revokes consent and wakes cleanup. This is business authorization, not a manual per-number registration step: subsequent eligible purchases submit automatically with no customer-side registration action.

There is no inferred consent, automatic shortening to an unapproved business name, self-asserted Hiya verification or unapproved fee acceptance. Missing consent/name, carrier permissions, fee authorization and partner access are explicit prerequisites. Registration approval is never inferred from a successful payment or purchase.

## SignalWire API and evidence

Official contract verified from `signalwire/docs` at commit `6bb76f54f2e648b7a64f207d35157b20a4ea0bf2`, `rest` OpenAPI source, operations request_caller_id_name / retrieve_caller_id_name / clear_caller_id_name. Official pages supplied for this task:

- https://signalwire.com/docs/apis/rest/caller-id-name/request-caller-id-name
- https://signalwire.com/docs/apis/rest/caller-id-name/retrieve-caller-id-name

Uses existing SIGNALWIRE_SPACE / PROJECT_ID / API_TOKEN (or encrypted token binding), Basic project authentication and Numbers permission:

- POST `/api/relay/rest/phone_numbers/{actual UUID}/cnam`, JSON `{"name":"APPROVED NAME"}`.
- GET same path for review status. Accepted `201` is **pending**, not success. Approved status additionally requires the phone-number GET's applied `cnam` to equal the approved name.
- GET `/api/relay/rest/phone_numbers/{id}` verifies actual E.164 ownership and applied name; a configured SIP caller-ID placeholder is not accepted as a real carrier ID.
- DELETE `/.../{id}/cnam` queues removal; poll applied `cnam` until empty and pending request gone/terminal. An accepted `204` alone is not removal confirmation. An externally changed request/name is flagged for reconciliation rather than cleared.
- Name normalization removes controls, trims/collapses whitespace and uppercases. Names must start with a letter/digit, use only ASCII letters/digits/spaces and `& ' . , -`, and be at most 15 characters after normalization. Longer names are rejected for an approved short name, never truncated.

`number_registrations` stores the returned real request ID and durable submission/removal intent. `registration_receipts` stores HTTP status, response/request ID and provider CNAM JSON; phone-number verification receipts retain only ID, E.164, applied CNAM and capabilities (no credentials, headers or route URLs). Public APIs expose statuses/prerequisites, not raw receipts or secrets.

## Idempotency and failure behavior

Unique `(phone_number_id, assignment_key, provider)` outbox keys suppress duplicate events. Atomic leases serialize duplicate workers; expired leases recover after crashes and token checks fence late finalization. Leases last three minutes, renewed while recording bounded HTTP operations. Production and SQLite use their native ON CONFLICT insert.

The worker checks latest CNAM before submission, persists intent before POST and rechecks ownership/authorization. If a POST response is lost, it reconciles via GET and adopts the actual matching receipt; it does **not** blindly resubmit an ambiguous request. An unresolved receipt stays Verification Required and is polled. Transient network, 429 and 5xx errors back off; provider rejections/failed review remain explicit outcomes. A caller-name change clears the old applied identity before requesting the replacement. In-flight requests cannot be transactionally canceled at an external carrier; a raced cancellation/reassignment immediately queues reconciliation, and old cleanup blocks new publication.

User labels: Registering Caller ID, Pending Provider Approval, Caller ID Registered, Verification Required, Registration Failed. Caller ID Registered describes selected CNAM/provider registrations only; it does not imply spam-label removal or STIR/SHAKEN attestation.

## STIR/SHAKEN

Tracked separately as `signalwire_attestation` action-required jobs. `GET .../admin/carrier-actions` lists the internal business-verification-order work. Admins can record a real, manually submitted order reference/evidence with `PUT .../admin/carrier-orders/{org_id}`. This tracks paperwork only and never submits an undocumented carrier order or claims Level A. Per-call attestation remains `unknown`; CNAM approval does not change it. Reuse the recorded business order across that organization's numbers.

## Validation, real integration test and rollout

Validation completed: 68 focused registration, SignalWire and phone-number tests passed; the 12 existing business-profile tests and the existing account-deletion test also passed separately. Frontend typecheck and production build passed. Automated tests exercise actual HTTP request serialization/authentication against MockTransport, queue transactions, receipt/pending/applied states, retries after lost responses, lease races/recovery, authorization and tenant boundaries, reassignment cleanup, external-name conflicts, migration replay and carrier-order separation. These are contract/logic tests, **not live external approvals**.

Real read-only integration on the owned 737 number: authenticated phone GET returned 200 with actual carrier UUID and `cnam:null`; CNAM request GET returned 404. The new integration-test client ran against the real account in read-only mode, returning `submission_performed:false`. Production credentials can read the required resources. No live POST/DELETE has been authorized/performed and no actual approval is claimed. An authorized test number, exact caller name and possible carrier-fee authorization were requested; they remain prerequisites to the live write test.

Opt-in live test (existing SignalWire credentials configured securely, never on command line):

```sh
python scripts/test_signalwire_cnam_live.py --number-id ACTUAL_UUID --number +14155550123 \
  --caller-name 'APPROVED NAME' --receipts /tmp/cnam-test-receipts.json \
  --submit --authorize-registration --authorize-carrier-fees --polls 3 --interval 60
```

Run the standalone write test with the registration worker paused or an isolated target that has no concurrently authorized outbox job. Without `--submit` the script is read-only. It verifies carrier number ownership, refuses to overwrite a different existing request, writes actual receipts with 0600 permissions and reports activation only after confirmed applied CNAM. Poll intervals are not completion-time promises.

Roll out to the house account's explicitly authorized test number first, inspect actual pending/approved/failed receipt and applied field, then opt in authorized customer businesses. No partner fees/registrations execute while partner adapters are unavailable. Before broad rollout, verify queue recovery on deployment, a release/reassignment, approval and rejection on real carrier resources. External port-out/removal notifications beyond BlackSync's lifecycle are not integrated with partner APIs; missing carrier ownership is flagged for review.

Migration: startup creates the four new tables/indexes additively; `backend/migrations/20261018_caller_identity.sql` is the equivalent idempotent Postgres DDL for review. No existing number data is rewritten. Rollback: set NUMBER_REGISTRATION_WORKER_ENABLED=false, then revert the code; retain audit/outbox tables and revoke or reconcile already submitted identities before deleting records. A code rollback does not undo a real carrier submission.
