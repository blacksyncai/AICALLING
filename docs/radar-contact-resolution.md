# Radar: find or create a Follow Up Boss contact before routing

For an activated, matching Radar rule, FUB destinations no longer require a CSV contact to have been imported from FUB first. Radar resolves the person before applying any CRM destination action. BlackSync-only ponds do not perform CRM lookup or creation. Other providers retain their existing link requirement.

## Resolution policy

1. Check the workspace, active rule/version, call type, DNC/suppression and evidence condition using the existing worker.
2. Validate the rule's destination against the current connected account before contact creation.
3. Lock and refresh the BlackSync contact row. Reuse a linked FUB person after checking it is available, not suppressed, and matches the contact when identity fields are returned.
4. For an unlinked contact, look up its normalized phone and, when present, email. Require exact identity evidence. Multiple matching records, mismatching lookup responses, and phone/email resolving to different people stop for manual review. No new contact or deal is created in these cases.
5. If a person matches, save its ID in the existing CRM references without changing its name, source or other attributes. Existing matches can be linked when contact creation is off.
6. If none matches, honor the existing Integrations → Follow Up Boss **Create people who aren't in Follow Up Boss** setting (`create_contacts`, off by default). Disabled means a failed action with an actionable message and no contact/deal creation. The worker never enables this setting itself.
7. When allowed, create a person quietly through `POST /v1/people?deduplicate=true` with the CSV contact's name/phone/email and source `BlackSync AI`. Read back the person and confirm identity before saving the link. Existing contact source attribution is never overwritten. This is not native FUB Lead Flow ingestion and does not use `/events`.
8. Continue the existing deal, person-stage, pond or tag action and record its result.

This explicit Radar workflow does not depend on normal call-log syncing being enabled or completing first. The global `create_contacts` setting still also governs ordinary CRM call syncing; it is not limited to verified-call rules.

## Durability and retries

A `pending_contact` receipt is committed before a contact-creation POST. The contact row is locked and both the link and the remote match are rechecked after the commit, serializing cooperating Radar jobs. FUB-side deduplication also protects against concurrent normal call syncing.

A lost response stops automatic retries. An explicit retry first searches read-only: a confirmed matching person can be linked and routing resumed without another POST. If no matching person is visible, Radar keeps the action failed for review and never blindly creates a second person. Pending requests are bound to the connection fingerprint and contact identity; changing either requires review.

Successful linking and creation receipts are committed before routing the deal. If a later deal action fails, its contact link survives. Existing deal write-ahead and read-back checks remain in place.

The legacy exact error `This contact isn't linked to the selected CRM. Import/link it before routing.` was raised before any deal request, but earlier workers stored a pending-deal marker first. Only that exact known pre-write failure clears its old marker on retry. Other uncertain deal markers remain blocked; the update does not reset historical executions or trigger an automatic backfill.

## User flow

For a new matched call, an active rule resolves and routes automatically. For the existing failed test call, enable creation if the person is missing, then choose Retry on that execution in Radar → Activity. Existing-contact matches do not require enabling creation.

Read-only previews disclose the current creation setting and do not search, create or link contacts. Activity displays the confirmed FUB contact ID and whether it was already linked, found and linked, or created/deduplicated, followed by the deal receipt. Structured deal results render safely alongside older text receipts.

## Validation

HTTP-mocked tests cover existing matches with creation off, missing contact creation with ordinary call logging off, settings changes and retry, duplicate/conflicting matches, source attribution preservation, DNC/Trash suppression, response-loss reconciliation, uncertain requests with no visible match, the legacy failed-action retry, read-only preview, and CSV import through contact creation/linking and deal routing. Browser checks cover structured contact/deal receipts at phone/tablet/desktop widths.

No live FUB contacts, deals or integration settings are changed by these tests. Production validation with a selected test contact remains separate from automated verification. There are no schema, billing, authentication, calling-runtime, or ordinary CRM sync changes.
