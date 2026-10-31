# Response review, brand kits and account families

## Post-call response review

New outcome reports opt into the versioned response review. The existing analysis request returns both
business response and agreed next action; no extra model request, live voice turn, audio processing,
or end-call-tool change is introduced. The larger result can add post-call processing time; live
conversation latency is unaffected by these changes.

Responses include `no_decision` (Spoke — no decision), `insufficient_conversation`, `busy`,
`information_requested`, and `declined_conversation`. An explicit rejection of the offer remains
`not_interested`. Permission to hear a pitch is not interest in the service; declining a meeting is
not rejecting the offer. A person can decline a meeting and accept information by text/email.
Sentiment remains independent.

`call_logs.response_analysis` stores the evidence quote, question scope, evidence certainty, agreed
next action, its quote, channel, timing and meeting response. Quotes must occur in live-contact turns,
not in agent suggestions, voicemail greetings or screening speech. Short English affirmations need a
matching preceding offer of the relevant action. Busy alone never grants callback permission. The
model still interprets intent and non-English context; these checks verify provenance, not perfect
semantic understanding. Ambiguous or unavailable analysis produces review/no-decision rather than
an invented rejection or callback.

Confirmed bookings, transfers, do-not-call, and machine evidence keep their existing protections.
No-decision, busy, insufficient conversation and declined-conversation are not campaign retry statuses
and do not automatically become lost leads. Installed CRM pipelines log these results without moving
the card. A grounded callback next action continues to match existing callback Radar conditions,
callback alerts and CRM callback tasks even when the business response itself is no-decision.
Information requests move to follow-up, but do not send email/text automatically. The evidence and
agreed next step are included in call details, CRM notes, connector reads and call.completed payloads.

The live report's disposition is provisional. Post-call review can correct that report before Radar
and outgoing call events consume it. Contact stages are corrected only when provenance shows that
this same latest call wrote the stage; unrelated manual edits and stronger results from earlier calls
are preserved. Campaign counters are reconciled idempotently for the same call. If analysis is
unavailable on a new call, hard results remain protected and uncertain replies receive human review.

Historical calls have no review marker and retain their existing outcomes. This release performs no
bulk re-analysis or historical backfill. Explicit per-call Re-analyze opts a legacy call into the new
review. Existing startup repair jobs remain separate and are not invoked by implementation/tests.

## Brand kit and nested accounts

The bottom of each account's admin detail page now holds Account family followed by Brand kit & white
label. The kit includes primary/accent colors, dark sidebar, light workspace background, body text,
bundled typography and button shape. Presets provide starting points; a live scoped preview does not
retheme the admin portal. Colors are restricted to hex values, fonts/shapes to enumerations; arbitrary
CSS and remote font URLs are not accepted. Contrast checks protect readable workspace/sidebar text;
primary button labels choose black or white for their background. This supports the existing light
workspace/dark sidebar design, not a separate dark-mode product theme. Billing, legal copy, voice
scripts and email senders keep their existing configuration.

The new `account_parents` table stores one immutable parent per child, with a maximum of eight levels.
Creation reuses the existing account/owner flow; memberships are always explicit. Parent/child links
never share credits, API keys, contacts, calls, billing or access rights. Parent accounts with children
cannot be deleted through the account deletion action. There is no reparenting or cross-account merge.

Absent a local kit, a child inherits the nearest enabled parent kit, including logo and typography.
A child can override with its own kit, or explicitly stop inheriting and use the platform default.
Each domain remains owned and verified by the child itself; DNS tokens, hosting and sign-in readiness
never inherit. Host routing resolves the child tenant, not the source of the inherited brand.

Hierarchy and kit management remain restricted to unlocked platform super-admins, preserving the
prior admin-only requirement. Parent customers can only switch to child accounts where they have
been explicitly granted membership. Delegated customer-owner administration is not enabled.

## Release and validation

Changes are prepared on `feat/outcomes-brand-kits` because the production branch auto-deploys.
The existing startup migration adds nullable `response_analysis`, `brand_kit`, `inherit_parent`
columns and creates the account-parent table in the current database. No database reset or new
infrastructure is needed. Deploy web/API together; existing workers can continue sending their old
outcome reports, which the API reviews after calls. Existing domain/TLS/Clerk setup requirements in
`admin-white-label.md` continue to apply.

Tests cover reviewed historical-example phrases, scoped refusals, callback consent, unavailable
analysis, actual post-call persistence/contact/counter corrections, repeat analysis, legacy-call
preservation, routing, hierarchy isolation/depth/deletion, inheritance/overrides and safe accessible
theme tokens. Provider/DNS requests are mocked. No real call, message or customer account is created
in production for validation.
