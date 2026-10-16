# Radar conversations and native CRM routing

This update extends the existing Radar framework. It does not replace calling, authentication, billing, CRM connections or existing rules.

## Conversations

Server-side conversations are private to a manager, workspace, CRM connection and connection fingerprint. Reconnecting a different account does not reuse the old account's conversation context. Conversations and current generated drafts are restored on reload; the selector reopens older threads and New chat starts a separate thread. The server uses its own recent history for continuation, ignoring client-supplied history once a conversation ID exists. The assistant also receives the current saved rules for that CRM so it can propose a reviewable update by ID. Generating an update does not save or activate it.

The current retention limit is 200 messages per thread; the assistant receives the latest 12 turns as working context. The selector lists 50 recent conversations. Saved rules and immutable CRM action receipts remain separately durable. Unsaved input and failed requests are not represented as completed conversations. Previous browser-memory-only conversations cannot be recovered retroactively.

The new `radar_conversations` table is registered through the existing models import and `create_all_tables` startup mechanism. It has foreign keys to organizations, connections and users. No existing production table is rewritten.

## Source → evidence → destination

Choose the BlackSync agent, campaign and/or BlackSync source pond first. Follow Up Boss can additionally filter by the linked person's current pond and/or lead-source label. These predicates are cumulative. CRM source/pond membership is read at evaluation time, not reconstructed at the time of an old call. A lead source records origin; Lead Flow controls incoming-lead assignment and is not a prerequisite for evaluating BlackSync calls.

FUB's existing contact import adapter already labels newly created contacts `BlackSync AI`. New `list_sources` and `set_contact_source` assistant tools read source labels or assign a label to a single contact after explicit confirmation. Assignment refuses to overwrite an existing different source. This is not a standalone source-object creation endpoint or native Lead Flow rule creation.

Evidence conditions remain independent of sales outcomes. Name confirmation requires callee evidence responding to an agent name check. Natural replies such as “Yes, it is. Who's speaking?” are now accepted. Named voicemail is weaker and stays a separate rule. Wrong-number evidence overrides confirmation. DNC/suppressed contacts and browser/text tests remain excluded.

## Follow Up Boss deal boards

The UI calls FUB pipelines **Deal boards (Deals / Deal Tracking)**. Person stages, ponds, native Smart Lists, lead sources and Lead Flow have distinct descriptions. `crm_deal_stage` is separate from `crm_stage`.

A reviewed and activated deal-routing rule:

1. Requires a linked FUB contact and an existing open deal stage on the selected board.
2. Reads that contact's deals on that board, including archived deals.
3. Creates a linked deal if none exists, or moves a single active deal forward. Existing later stages are preserved; closed/archived/ambiguous deals stop for review.
4. Reads the changed deal back before recording success.

Before a deal action the execution commits a pending marker, then locks the contact row while reconciling. This serializes deal reconciliation across jobs in PostgreSQL. If a request fails or the worker stops after that marker, it does not automatically repeat the potentially non-idempotent write. The execution stops for manual CRM review instead of risking a duplicate. No automatic historical backfill occurs: users preview past calls and explicitly select them; new calls use activated rules.

`GET /commands/{id}/verify` checks a completed FUB board receipt against the current CRM without recreating anything. “I don't see it” checks the latest completed board receipt for the current user/account rather than producing a new create command.

## Provider coverage and remaining limits

Conversations, saved-rule context and verification improvements apply to all connected CRMs. Shared adapters remain authoritative for available tools and routing targets. This update adds native deal routing and lead-source controls for FUB; it does not claim equivalent native resources exist in every other CRM. Native FUB Smart List and Lead Flow configuration remain in Follow Up Boss; unsupported actions are described honestly and are not simulated.

Tests use mocked CRM HTTP responses. No live customer contact, deal, Lead Flow, production database or Stripe object is modified during validation. A live test with an explicitly selected test contact remains necessary before enabling a customer's routing rule.
