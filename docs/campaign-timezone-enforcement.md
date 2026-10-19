# Campaign timezone enforcement

The campaign's saved IANA `timezone` and local HH:MM calling window are authoritative. The server converts its UTC clock into that zone using Python ZoneInfo, including daylight saving changes. Browser/device timezone is neither submitted as an implicit override nor consulted by the backend. Existing campaign-specific selections are not rewritten. Legacy NULL timezone retains the documented America/New_York default; account reporting timezone is a separate setting.

Audit: the normal campaign queue already checked the saved window at its loop and after waiting for capacity. However, the campaign `call selected` route/background path lacked those checks, and the common outbound service could place campaign-linked calls from other API/CRM entry points without enforcing the campaign window.

Changes:

* Selected-contact requests outside the saved campaign window return HTTP 409 before scheduling any background calls. Background selection checks again before each contact.
* The shared outbound dispatcher checks any explicit or lead-inferred campaign before CRM/context/credit preparation and refreshes the saved zone/window/days again before committing dispatch, covering schedule changes or window closure during preparation.
* Schedule closure is a distinct error. The queue rolls back the attempt and waits instead of treating it as a failed dial or pausing the campaign for a setup error. Selected-contact batches stop without persisting a failed attempt.
* Invalid saved timezone names fail closed; they are never silently interpreted as Eastern time. API validation continues rejecting invalid selections.
* Start/resume and selected-contact controls are disabled while calling rules are edited or saving, with a visible save reminder. The start confirmation no longer falsely promises immediate dialing outside the window.
* UI help explicitly says the server follows the saved timezone, not the device/browser. No schedule fields are changed automatically.

A call initiated within the window can ring or continue past its end; this does not terminate existing conversations. Once an external provider request has been sent it cannot be retroactively canceled by a subsequent settings edit. Recipient quiet hours are an independent restriction and may delay a call further. Ad-hoc agent tests with no campaign remain immediate.

Validation: 35 focused backend tests passed across campaign rules, outbound calling and orphan reconciliation, including 9 AM Pacific boundaries in standard/daylight time and immediately after both DST transitions, invalid saved zones, fresh-zone reloading, blocking the selected-contact API, and blocking shared dispatch before account/credit/provider work. Browser checks with Tokyo and New York device timezones confirm that selecting 09:00 Pacific sends the same unconverted saved timezone/time and that starting is disabled until save completes. Frontend production build includes TypeScript checking. No actual phone calls were placed for validation.

Rollback: revert this change; no schema migration or schedule backfill is involved. Reverting restores the selected/manual campaign schedule bypass and is therefore not recommended while campaigns depend on strict windows.
