# SignalWire inbound test setup

Provisioned test number: +17373654598.

- Dedicated digest-authenticated LiveKit inbound trunk `ST_9sEuoPXNqmT3`, named `BlackSync SignalWire inbound`.
- Dedicated individual-room dispatch rule `SDR_Rzd4QpD5RFRW` dispatches worker `closer` with inbound metadata.
- SignalWire hosted calling SWML connects the dialed number to the configured LiveKit SIP host over TLS, retaining caller ID and offering PCMU/PCMA.
- Only this number's incoming handler was changed. Outbound routing and existing inbound trunks/rules were preserved.
- Hosted script and carrier number settings were read back and verified. No PSTN call or caller-audible audio has been tested yet.

## Agent assignment

In the account that owns the number: Campaigns → New campaign → Inbound → select +17373654598 and an existing agent → Create inbound campaign. Creation automatically activates the campaign when routing verification succeeds. Do not select a different account's agent or change its prompt/voice for this test.

Activation requires the dedicated trunk, the exact allowlisted number, digest credentials, and a carrier SWML readback matching destination and credentials. It fails closed if any check fails. Additional SignalWire numbers must be explicitly provisioned before activation; this does not silently enable inbound on every purchased number.

## Validation

Focused tests cover carrier trunk isolation, missing provisioning, readback mismatches, foreign URL rejection, activation ordering, existing inbound campaign routing and existing SignalWire outbound flows. No live account agent assignment was made by the deployment: the existing authenticated dashboard workflow is required.

## Rollback

Pause the inbound campaign to remove the agent assignment. Restore this number's previous carrier incoming handler from the operational rollback snapshot (laml_webhooks/voice; no previous incoming script). Remove only the newly created SignalWire script and dedicated dispatch/trunk after confirming they have no active calls. The local rollback record is `/workspace/scratch/inbound-737-rollback.json`; it contains resource identifiers and previous number routing, not digest credentials. Reverting the code also restores the prior SignalWire activation block. Do not delete or modify the existing Twilio/Bandwidth trunks or dispatch rule.
