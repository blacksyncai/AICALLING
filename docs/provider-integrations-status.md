# CRM connectors and lead-source readiness

## Native CRM connections

Oracle Sales/Fusion (`oracle_sales`) and Real Geeks (`realgeeks`) are registered in the normal CRM connector catalog. The misleading Oracle/Real Geeks/BoomTown CSV cards have been removed from Integrations. No customer account is automatically connected.

Oracle uses a Fusion API username/password and a validated HTTPS Oracle Cloud instance hostname. Read-only contact access is verified before the encrypted password is persisted. The adapter supports paginated contact import, existing-record matching, confirmed contact creation, call-note creation and do-not-call updates. Imported contacts retain their Oracle PartyNumber so later calls log to that record. Phone-only automatic creation is refused when the contact cannot be matched, reducing duplicate risk.

Real Geeks uses registered Incoming Leads API credentials, a Site UUID, and an existing lead UUID for a read-only connection test. This is not the customer's normal website login. It supports call notes on linked contacts and creation/readback of new leads using a stable per-site phone-based UUID. A successful connection test never creates a test lead. The Incoming Leads API does not list all contacts, so bulk import and speed-to-lead are not advertised. Those require a separate Outgoing Leads webhook implementation, not CSV or guessed API endpoints.

Passwords remain encrypted in the existing secret store. Authentication failures never mark a new connection connected, and failed reconnection does not replace the prior saved credential. Password whitespace is preserved for these providers.

## BoomTown blocker

BoomTown is represented as unavailable with “API verification pending”, not as a CSV integration or a live connector. Its official documentation host returned HTTP 503 at the root, /docs, /api and /swagger/index.html. No authentication flow or endpoint contract was invented. The backend explicitly refuses activation until that contract is verified. Provider API documentation/access is the remaining prerequisite.

## Lead sources

Vulcan7 and REDX remain CSV contact import options in Lead Finder → My lead sources, with source tags and duplicate handling. The user confirmed they have no API access/documentation for these providers. These are not labeled connected accounts and do not run paid property lookups or place calls.

## API references inspected

- https://docs.oracle.com/en/cloud/saas/sales/faaps/api-contacts.html
- https://docs.oracle.com/en/cloud/saas/sales/faaps/op-contacts-get.html
- https://docs.oracle.com/en/cloud/saas/sales/faaps/op-contacts-post.html
- https://docs.oracle.com/en/cloud/saas/sales/faaps/op-contacts-partynumber-child-note-post.html
- https://docs.oracle.com/en/cloud/saas/sales/faaps/Quick_Start.html
- https://developers.realgeeks.com/incoming-leads-api/
- https://developers.realgeeks.com/leads/
- https://developers.realgeeks.com/activities/
- https://developers.realgeeks.com/outgoing-leads-api/ (separate future webhook contract)

Oracle and Real Geeks documentation became reachable during this correction. HTTP contract tests use mocks based on these documents; no customer credentials were available to verify a live customer connection or perform external writes. Do not describe those tests as live customer sync validation.

Rollback: revert the correction commit; avoid reverting the earlier CSV additions wholesale because that would also remove the requested Vulcan7/REDX import path and prior MCP link changes.

## Brivity

Native API-token connection, verified read-only against `/api/v2/roster` before encrypted storage. Supports importing up to 100 explicitly selected Brivity person IDs via `/api/people/{id}`. The imported external ID is preserved for each record. This is not CSV and does not discover the full account.

Published documentation: https://nvntd.github.io/brivity-core/doc/api/index.html (generated July 2019). Verified authentication format `Authorization: Token token=<token>` and array response shapes. The API host returns HTTP 401 without a token for roster and person reads. Mock contract tests cover positive and negative response shapes; no customer token or live authenticated account was available for this task.

The published API has no contact list/search, note-write or opt-out-update contract. Those operations are disabled in UI, settings API and sync worker. Lead creation and event subscriptions are documented, but are not enabled in this release; no duplicate-prone creation or unverified webhook payload handling is introduced. The roster only verifies access; it is never imported as customer leads.

To use: Integrations → Brivity → Connect; paste the API token and optionally comma-separated person IDs, then use Import. Change selected IDs through Update credentials. Existing agent scripts, objectives and voices remain unchanged.

Rollback: revert this connector commit; existing tokens remain encrypted and can be disconnected normally.
