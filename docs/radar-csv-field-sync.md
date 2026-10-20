# Radar CSV data → Follow Up Boss

## Existing functionality inspected and reused

The original integration already provides:

- `FollowUpBoss._custom_fields`, `field_catalog` and `person_fields` in `providers.py` to discover custom fields and read contact values.
- `variables.auto_field` / `SYNONYMS` and `visible_fields` for script-variable matching and customer-visible contact fields.
- `settings.var_maps[agent_id]`, managed by the existing `/{key}/variables` endpoints and Script variables integration UI.
- `sync.prefill_fields` and `variables.apply`, which pull **FUB → BlackSync agent scripts**.

Those are inbound read/prefill features. The deployed Radar contact resolver previously sent name, phone, email and source when creating a missing FUB person; it did not export the CSV's extra columns.

The new outbound service reuses that catalog, safe automatic aliases, and concrete saved per-agent mapping choices. It does not replace the inbound mapping system, reverse ownership/stage settings, or reinterpret the inbound “don't fill” choice as permission to discard CSV values. Catalog metadata now retains types and choices and supports strict, fresh, paginated reads for writes; existing read callers retain their compatible behavior.

## Export policy

For a matching FUB Radar action, resolve/link the person first, then export stored CSV/contact values before routing the deal. Newly created and already-existing people use the same path.

- Plain mailing-address columns fill empty FUB address components. Existing conflicting addresses are preserved. Property-address columns remain custom data; a property address is not silently treated as the person's mailing address.
- Concrete script-variable mappings select their corresponding FUB custom field. Matching labels/keys and safe standard aliases work automatically.
- Existing custom-field types are respected: text, finite numbers, ISO dates and valid dropdown choices. Invalid/long/incompatible values are not coerced or silently truncated.
- Missing email/phone lists may be filled after an exact uniqueness check. Existing populated identifier lists, names and original source attribution are preserved.
- A complete JSON snapshot of the customer-visible source values is appended to the FUB contact background, preserving existing background content. Runtime metadata such as CRM caches and BlackSync retry state is excluded. The snapshot represents values currently stored on the BlackSync contact at sync time, rather than a separate historical copy of the original uploaded file.
- Conflicting and unmapped values remain in that full snapshot and are explicitly listed in the execution receipt. Source data exceeding the safe 250,000-character snapshot budget stops with an error rather than truncating it.

Existing populated FUB values are never intentionally replaced by this exporter. As with ordinary FUB read/modify/write APIs, updates from unrelated external clients cannot be made transactionally atomic with BlackSync's database locks.

## Missing custom-field definitions

The existing integration's Push calls section gains one opt-in setting: **Create missing custom fields for CSV data** (`csv_create_fields`, false by default). This is separate from creating missing people. Enabling it allows up to 50 new text-field definitions per sync operation. Existing field types/choices are not changed. Follow Up Boss restricts `POST /v1/customFields` to account-owner API keys.

A schema-creation request is journaled before POST and reconciled against a fresh catalog. Uncertain requests are never blindly repeated. Cooperating Radar jobs serialize schema creation through the connection row. A definitive permission denial disables further creates in that operation; values still reach the source snapshot and the receipt explains the limitation. An unreadable/incomplete catalog blocks field writes instead of treating the account as having no fields.

## Retry and existing completed calls

Person updates are state-setting operations. A lost response is reconciled by reading the fields and complete snapshot back on retry. A deterministic snapshot marker prevents duplicating an unchanged source block.

For calls already routed, **Radar → Activity → Sync CSV data** invokes the scoped `POST /activity/{execution_id}/sync-data` endpoint. It verifies the completed execution, workspace, FUB connection, contact receipt/link and identity. It does not activate rules, dial calls, create another deal, or rerun routing. The existing FUB contact can therefore receive missing CSV data without a new call.

The Activity receipt displays filled fields, created definitions, preserved conflicts, snapshot-only values and warnings. The routing chat prompt describes the feature without falsely claiming a chat request has executed a backfill.

## Verification and limits

HTTP-mocked tests cover standard addresses and custom types, opt-in definition creation, owner-permission denial, existing-value preservation, full snapshots, runtime-metadata exclusion, saved agent mapping reuse and original inbound field reads, schema and person response-loss reconciliation, completed-action backfill, account scoping, missing email fill, and catalog-read failure. Existing CRM, Radar and prefill suites remain part of regression validation. Browser checks exercise the actual integration settings page and Radar Activity at 320/390/768/1440 pixels.

This implementation currently exports to FUB. It adds no new authentication, billing, database schema, or deployment configuration. Automated tests do not create live customer contacts or custom fields.

Official references:
- https://docs.followupboss.com/reference/customfields-get
- https://docs.followupboss.com/reference/customfields-post
- https://docs.followupboss.com/reference/people-id-put
