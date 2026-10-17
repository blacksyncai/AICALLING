# Additional providers: scope and readiness

Oracle, Real Geeks and BoomTown are listed under Integrations. Vulcan7 and REDX are listed in Lead Finder → My lead sources.

## Available

All five entries open the existing CSV contact importer, with an default `source:<provider>` tag added to any user-entered tags. Phone deduplication, organization scoping, custom fields and the import receipt use the existing `/api/contacts/import` route. No property lookup, campaign activation, external vendor request or account connection is performed by importing.

The parser additionally recognizes Phone1, Phone 1, Primary Phone, Owner First Name and Owner Last Name headers. These are tested supported headers, not a claim that every vendor export uses this schema. Other fields, including secondary phone columns, remain custom fields. Existing importer restrictions and phone validation still apply.

## Not enabled

Direct login, OAuth/API credential verification, scheduled account sync, provider-backed property search, and post-call writeback for these five providers are not implemented. The UI explicitly says account sync is unavailable and does not solicit credentials or report a connected state.

The user confirmed Oracle Sales/Fusion CRM. No NetSuite or HCM adapter is substituted. The user has neither API access nor developer documentation for Vulcan7/REDX.

The documentation requests below were rejected by this environment's HTTP proxy (403). Access domains were saved to the environment draft; saving is not publication or proof of vendor API access:

- developers.realgeeks.com
- developers.boomtownroi.com
- www.vulcan7.com
- www.redx.com
- docs.oracle.com

Existing configured domains were retained. Read-only inspection of Nango's provider definitions found Oracle HCM/Identity, but no matching adapters for these requested CRM/data products; these Oracle products were not substituted for Oracle Sales or NetSuite.

## Before enabling direct connections

For Oracle Sales/Fusion and the remaining providers, obtain official API/authentication specifications and appropriate account access for each provider, implement read-only verification before credential persistence, then add scoped import/pagination, DNC mapping and confirmed call-write receipts with contract tests. Treat any live property lookup pricing separately from contact imports. Never use regular account passwords with a guessed endpoint.

## Validation

Four backend tests cover export headers, quoted address data, missing numbers, source tags, duplicate import handling and no campaign assignment. Frontend build/type checks and mocked browser checks are recorded in the task artifacts. No real vendor accounts were linked and no real vendor data was imported.
