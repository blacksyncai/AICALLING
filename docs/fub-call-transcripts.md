# Follow Up Boss call transcripts

FUB Push calls settings include Full transcript (enabled by default). The existing log-calls switch and outcome, sentiment, minimum-duration and answered-call filters apply. Disabling summary or recording links does not disable transcript text.

New normal CRM call sync and successful Radar CRM routing send the stored call's spoken transcript to the linked FUB person as separate notes. Each note identifies the BlackSync call, content revision and numbered part. Agent/contact turns are included; system/tool events are excluded. Text is HTML escaped. Transcript content is split at 8,000 characters without truncation.

Radar Activity provides Sync transcript for already completed routing entries. This sends notes only: no dialing, rule activation, contact creation or repeated deal routing. It requires manager/Radar authorization, same-workspace call and connection, and an unchanged contact receipt/link. It reports missing transcripts or disabled/filtered settings explicitly.

The durable crm_transcript_deliveries table records per-call/contact/revision/part receipts, serialized using the CRM connection row lock. Confirmed parts are reused. A write intent is committed before POST. Explicit rejection can be retried; uncertain writes stop for review rather than sending a possible duplicate. A changed transcript revision is a new export. The new table is created through the application's existing metadata startup process; existing tables are not altered.

Audio remains an authenticated BlackSync call-page link when Recording link is enabled, not a FUB-hosted audio attachment. Past calls are not bulk exported during deployment. No external CRM test writes are performed by the regression suite.

Validation: test_fub_transcripts.py exercises normal call sync, historical backfill, duplicate prevention, multipart output, internal-message exclusion/escaping, lost responses, explicit rejection/retry, settings, browser-test exclusion and workspace boundaries. Provider HTTP is mocked.
