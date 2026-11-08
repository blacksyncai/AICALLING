# Radar across connected CRMs

Radar lists every connected provider whose registry category is `crm`. Adding a new registered CRM no longer requires a Radar allowlist update.

Capabilities are derived from the adapter: existing `can_scan` implementations keep native activity scans; a concrete `list_contacts` implementation with `can_import` enabled automatically supports contact discovery. Neither timestamps nor missing call history are invented. These real contact lists can use the existing selected-contact campaign creation and append flows, with both CRM and BlackSync DNC exclusions. Contact loads use the existing adapter read API and are capped at 500 records, without claiming oldest/recent sorting or unsupported pagination.

Read-unavailable adapters remain visible with their limitation, and no read action is offered. Currently these are Real Geeks, Rechat and BoomTown. A future API adapter gains contact discovery when it implements contact reads. Notifications/spreadsheet integrations are not presented as CRMs.

Discovery responses include capability metadata for UI/API clients; unsupported list, pipeline-install and field-mapping controls are not offered. Existing activity scans, CRM assistant routing, account permissions, entitlements and campaign semantics remain unchanged.

Validation: new-adapter registry integration test, real adapter-contact fallback with deduplication/missing-phone and DNC checks, native activity/campaign/MCP regressions; production Next.js build; browser checks at 390px and 1440px with API fixtures, without live CRM writes or calls.

## Activity grouping and lists

Scans share evidence-based groups, including Contacted and Needs activity data. Readable contact adapters use tenant- and phone-matched BlackSync call logs in addition to CRM contact signals. A voicemail or failed call is an attempt, not a conversation. Missing history never proves a contact was untouched. Scan groups show previously handled contacts by default, retaining their badges and the hide-handled control.

List catalogs reuse each adapter's supported import filters or native segment API. Generated filter tokens are validated against the current catalog; arbitrary client filters and stale tokens cannot broaden a selection. Adapter limits still apply.

BlackSync Cloud reads people, companies, opportunities, notes and noteTargets through authenticated REST endpoints. Note titles follow Cloud's actual call/email/text ingestion format. Native saved views and custom pipeline stage fields come from metadata. Company activity applies at lead/account level, matching Cloud's model. Old opportunity updatedAt values provide conservative evidence that the stage has not changed. Incomplete history produces a warning and cannot establish never-contacted/cold classifications.

Scans page through people in batches of up to 500 (50 for quick); linked collections cap at 5,000. Lists evaluate up to 5,000 people and reject incomplete reads rather than silently opening a partial list. Metadata requires the Cloud key's data-model read permission. Unsupported saved-view operators fail explicitly. Private Pulse smart views in pulseSetting are unavailable through existing API-key endpoints and are not advertised. No Cloud write permissions were broadened.

Validation uses HTTP-client transport fixtures checked against BlackSync-pulse-'s application-registration-ownership-guard source, plus shared adapter, tenant isolation, pagination, DNC, campaign append and MCP regressions. These are contract tests, not a live customer-workspace scan.
