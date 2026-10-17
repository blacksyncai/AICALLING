# SignalWire number purchases

SignalWire is the primary purchasable carrier when its credentials and outbound
LiveKit trunk are configured. Twilio remains an explicitly selectable backup.
There is no automatic carrier failover for purchases.

Both customer Phone numbers and admin account Phone numbers expose a carrier
selector. Customer purchases still require the existing self_serve_numbers
admin setting, account limits, plan allowances, and existing monthly billing.
This change does not enable self-service globally or change retail pricing.

The provider choice is carried into Stripe Checkout and subscription metadata,
including the checkout idempotency key, and used by payment-webhook provisioning.
Old checkout sessions with no carrier metadata retain Twilio behavior.
SignalWire provisioning does not substitute another number after a failed or
uncertain purchase. A provider timeout can require manual reconciliation of owned
inventory and the Stripe subscription; no provider purchase idempotency guarantee
is assumed. Existing database uniqueness prevents duplicate local assignments.

Native REST API: GET /api/relay/rest/phone_numbers/search with areacode,
number_type=local, max_results; POST /api/relay/rest/phone_numbers with JSON number;
DELETE /api/relay/rest/phone_numbers/{id}. API token requires Numbers permission.
Observed search results use e164, national_number_formatted, rate_center, region,
and a capabilities list (only voice-capable results are displayed).

Sources: SignalWire official docs, specs/signalwire-rest/relay-rest/phone-numbers
in signalwire/docs. Live authenticated 415 search returned HTTP 200 with candidates
and no ignored parameters. Search does not reserve a number. Purchase/release are
covered by HTTP mock integration tests; no paid number was bought during testing.

Purchased SignalWire numbers are assigned to their organization and added to the
shared outbound LiveKit trunk with dynamic caller ID routing. Inbound is not
provisioned by this flow and is explicitly labeled in the interface. Twilio's
existing routing remains unchanged. Release dispatch uses the stored carrier,
including releases caused by cancellation of a number-only subscription.

Rollback: revert this commit to hide SignalWire purchase choices. Existing
purchased SignalWire rows must retain carrier-aware release handling; do not
roll back that dispatch while such rows remain active. Disable self-service
through admin telephony settings if purchases must be paused immediately.
