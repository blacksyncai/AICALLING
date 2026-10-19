# Apollo native saved-contact connector

Apollo appears in Integrations and connects using the existing API-key dialog. Enter a customer-owned Apollo key there; never put it in chat. Existing organization-scoped encrypted CrmConnection storage, entitlement checks, import preview, phone deduplication, campaign assignment, disconnect and scheduled auto-sync are reused. No database migration, platform-wide Apollo key, CSV upload or Nango connection is required.

## Real API operations

Host: `https://api.apollo.io/api/v1`. Credential header: `X-Api-Key`.

* GET `/auth/health`: require boolean `is_logged_in: true`.
* POST `/contacts/search`: also tested during connect (`page: 1`, `per_page: 1`) to verify saved-contact permission before persisting credentials.
* Imports use POST `/contacts/search`, fixed `per_page: 100`, 1-based pages, `sort_by_field: contact_created_at`, `sort_ascending: false`, and optional `q_keywords` from the connection's Saved-contact search setting. Requests are read-only despite using POST. A fixed page size avoids shifting the last page's offset. Each import processes at most the requested limit (maximum 2,000), fetching fixed-size pages of up to 100 records and returns records with supplied phone numbers; it never enriches missing phone numbers. Incomplete/malformed responses, repeated IDs, or failed pages abort the preview/import rather than committing a partial success.

Name, email, company, supplied phone numbers, supplied opt-out flags/tags and the Apollo contact ID are mapped. Existing BlackSync import code keeps tenant ownership, durable external IDs, DNC suppression and duplicate handling. Phone-less contacts are skipped. Existing local opt-outs are never cleared. Known Apollo opt-outs are imported; this is not a guarantee of complete upstream DNC coverage or permission to call a contact.

Scheduled sync rechecks a bounded snapshot of the newest saved contacts and deduplicates locally. It is not a complete historical account backfill or a webhook/creation-timestamp trigger. Refine the optional search for large accounts.

## Explicit limits

Saved contacts belong to the customer's Apollo account. This is not search/enrichment of Apollo's global prospect database. API access and saved-contact search permissions depend on the customer's plan/key. No paid enrichment, phone reveal, email/sequence enrollment, outbound writes, pipeline installation, call-note logging or opt-out writeback are enabled. `can_log_calls=false` disables call pushing on connect. The integration detail page now names the actual provider rather than hard-coding Brivity in its read-only notice. “Skip already contacted” is rejected explicitly because reliable activity history is not verified for this connector.

## Evidence and validation

Apollo documentation was requested at `https://docs.apollo.io/reference/authentication` and `/reference/search-for-contacts`, but this cloud environment's egress proxy denied access. The legacy Apollo-owned GitHub docs repository referenced by adapters is no longer available. No claim is made that current official docs were retrieved or that a live account was tested.

Implemented endpoint/header/pagination contracts were cross-checked against these maintained sources available in GitHub:

* Pipedream `components/apollo_io/{apollo_io.app.mjs,common/constants.mjs,actions/search-contacts/search-contacts.mjs}`, commit `cf117dd0ebb60c54e4dbfda30a2ab296607425b4`: native `api.apollo.io/api/v1`, X-Api-Key, saved-contact search, keywords and sort fields.
* Nango `packages/server/lib/hooks/connection/providers/apollo/credentials-verification.ts` and provider config, commit `8da524eae1a41ca3be1625b41d254a25fe34f3ca`: GET auth health and the `is_logged_in` check.

The environment draft additively includes `docs.apollo.io`, `api.apollo.io`, and `app.apollo.io`; saved configuration is not applied network access. Production Railway egress is separate. Live authentication/import remains unverified until a customer connects a permitted Apollo key. No provider request with a real API key or billable enrichment was performed.

Validation: 51 backend tests passed across `test_apollo.py`, `test_crm.py`, `test_re_crms.py`. These use real HTTP serialization with a mocked external server, including the application connect/import/disconnect endpoints; they are not proof of a live Apollo account. Frontend typecheck/build and connect-form smoke checks are part of the release checks.

Rollback: revert this commit. Existing encrypted connection rows can be retained or disconnected normally; existing imported contacts are not automatically deleted. No schema rollback is needed.
