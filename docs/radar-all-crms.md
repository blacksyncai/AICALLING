# Radar across connected CRMs

Radar lists every connected provider whose registry category is `crm`. Adding a new registered CRM no longer requires a Radar allowlist update.

Capabilities are derived from the adapter: existing `can_scan` implementations keep native activity scans; a concrete `list_contacts` implementation with `can_import` enabled automatically supports contact discovery. Neither timestamps nor missing call history are invented. These real contact lists can use the existing selected-contact campaign creation and append flows, with both CRM and BlackSync DNC exclusions. Contact loads use the existing adapter read API and are capped at 500 records, without claiming oldest/recent sorting or unsupported pagination.

Read-unavailable adapters remain visible with their limitation, and no read action is offered. Currently these are Real Geeks, Rechat and BoomTown. A future API adapter gains contact discovery when it implements contact reads. Notifications/spreadsheet integrations are not presented as CRMs.

Discovery responses include capability metadata for UI/API clients; unsupported list, pipeline-install and field-mapping controls are not offered. Existing activity scans, CRM assistant routing, account permissions, entitlements and campaign semantics remain unchanged.

Validation: new-adapter registry integration test, real adapter-contact fallback with deduplication/missing-phone and DNC checks, native activity/campaign/MCP regressions; production Next.js build; browser checks at 390px and 1440px with API fixtures, without live CRM writes or calls.
