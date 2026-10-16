# Important-call email alerts

Account → Call alerts lets an owner/admin enable automatic email alerts, select outcomes (appointment booked, qualified follow-up, callback, interested, transferred), choose current account members, and optionally limit agents. This supports industry/workflow-specific choices without emailing after every call. Defaults are disabled, with appointment/qualified/callback suggested. Enabling sets a new activation timestamp; no historical bulk sends occur. Browser tests are excluded. A user may stop their automatic alerts in the same tab.

Admin → Accounts → [account] has the same settings plus completed phone-call history. Select up to ten calls and up to twenty account members, preview the call summaries/recipients/links, then explicitly confirm. No email goes out from preview. This neither dials nor changes CRM records. Delivery states and safe retries appear per call.

Emails use `EMAIL_FROM_CALLS`, default `BlackSync Campaigns <campaigns@blacksync.ai>`, through existing Resend credentials and delivery tracking (`kind=call_alert`). This setting does not affect login/password-reset mail. Domain verification in Resend is required; a configured API key alone does not establish sender verification. Tests never send live mail.

Each email contains the outcome, summary, contact, phone, agent, appointment time where present, and BlackSync call link. An optional FUB workspace URL (HTTPS subdomain.followupboss.com only) plus the same-workspace lead's saved numeric FUB contact ID builds `/2/people/view/{id}`. Missing links fall back to BlackSync rather than guessing a CRM ID. Other CRMs currently use the BlackSync review link; tenant-aware direct links can be added separately. The supplied example ID 11204 is test data only, never hard-coded for customers.

`call_alert_settings` and `call_alerts` are additive tables created by existing startup metadata. The worker polls every 30 seconds, allows at least 60 seconds after call events for CRM linking to finish, and persists notification jobs. A unique call/user pair suppresses repeat automatic/manual sends. Delivery rechecks organization status, membership, opt-outs and automatic filters. The email payload is frozen before delivery so retries reuse both the body and Resend idempotency key. Up to five automatic attempts occur, with backoff. Expired unknown writes stop within 20 hours (before the provider's 24-hour deduplication window expires). Admins can retry recent failed/retry messages using the original job/key. Cancelling or changing recipients does not re-send past calls.

This release implements email notifications and admin delivery history; it does not add SMS, browser push, or a global notification bell. No existing workspace is opted in automatically.

## Finding past calls

The admin notification panel starts with contact name/phone search instead of an unfiltered call list. Search is performed on the server before pagination, case-insensitively for names and with literal wildcard handling; both the call dialled number and the linked contact phone are considered. Formatted phone queries have punctuation removed. The optional result filter narrows matches; Browse recent calls retains access to the unfiltered history. Search changes clear call selections to avoid acting on hidden results.

The saved workspace recipient list also supplies manual notification defaults, even with automatic delivery disabled. Defaults update on the page until the operator edits the recipient selection. Recipient name/email search does not change selected recipients. Admin account navigation remounts the selection panel to isolate accounts. Notification settings are collapsed beneath the lookup, and sending still requires preview plus explicit confirmation.
