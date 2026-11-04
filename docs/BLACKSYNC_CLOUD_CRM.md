# BlackSync Cloud CRM connection

This branch adds BlackSync Cloud to the existing native CRM provider catalog and uses the production app’s native connection screen under **Integrations → BlackSync Cloud**.

## Connect

1. In the CRM, open **Connect & automate → API** and create a key. Its role must read the mapped contacts, and read/create notes and note targets. Allow contact creation only if you intend to use that feature.
2. In the calling app's **Integrations → BlackSync Cloud**, enter the public HTTPS CRM workspace URL and the key. The key uses the existing encrypted `CrmConnection.secret_enc` storage; it is never returned to the browser.
3. Leave automatic contact creation off to sync existing contacts only, or explicitly turn it on. Existing imported CRM contact mappings are reused. Otherwise the adapter matches an exact international phone number and refuses ambiguous matches.
4. New completed phone calls are picked up by the existing one-minute CRM poller. Browser voice tests and text playground sessions are excluded.

The CRM receiver is `POST /rest/pulse/calls`. Deploy the BlackSync Cloud CRM branch containing that endpoint before enabling the connection.

## What is synced

- A stable `source: blacksync-si` and the saved call UUID as `externalId`.
- Inbound/outbound direction, the remote party's phone number, talk duration, and connection outcome.
- Sales outcome (including meeting booked, callback, qualified, etc.), agent, summary, extracted details, meeting information and authenticated source-call link in the summary.
- Customer and agent transcript turns when transcript sync is enabled. Tool arguments are excluded.

Private recording objects remain private. This version links to the authenticated source-call page rather than exporting an expiring signed recording URL. It does not copy recordings or promise playable embedded audio in the CRM.

## Delivery and recovery

`crm_call_deliveries` is a durable receipt table created by the existing startup schema initialization. No new infrastructure or environment variables are required. The API worker recovers eligible completed calls from `call_logs`, so a lost in-memory task does not lose the call. It considers calls ending on or after the connection's creation; it does not automatically export historical calls from before connection.

Receipts are unique per connection and call. The poller serializes work per connection with a PostgreSQL row lock. The receiving CRM deduplicates repeated events by source/external ID, covering crashes after a remote write but before a local commit.

Transient failures remain pending with exponential backoff (up to one hour). Most HTTP 4xx errors are blocked until corrected; 408/429 remain retryable. The panel shows processed, pending and blocked counts, with a retry action. A processed receipt includes intentional skips from existing call filters or from leaving contact creation off; the existing activity log explains those outcomes.

The current CRM provider does not advertise pipeline-stage mutation, automatic tagging, DNC-field mutation, or Radar scanning. Those require explicit record/field mappings; call outcomes are preserved in the summary rather than guessed into workspace-specific fields.

## Validation and deployment

23 focused backend tests passed, including real SQLite schema/receipt queries, adapter HTTP tests, retry state, tenant selection, inbound caller selection, ambiguous-number rejection and regression tests for the existing real-estate CRM adapters. Changed Python files compile, and changed TSX parses. The complete frontend build and live account-to-CRM delivery have not been exercised here.

The existing ECS workflow is manual and points at the original upstream AWS account. Do not run it for BlackSync. Use your existing BlackSync hosting deployment for this branch. GitHub publication by itself does not verify that blacksync.si has deployed this version.
