# Follow Up Boss deal pipelines and confirmation

## What changed

The assistant and resource form now accept custom stages when creating a Follow Up
Boss deal pipeline. The same action can reuse an existing pipeline by name and add
missing stages. add_stages targets an explicit deal-pipeline ID.

The implementation uses POST /v1/pipelines with an embedded stages array. Existing
pipelines are read from GET /v1/pipelines/{id}; appending stages uses PUT on that
pipeline with the current stages (including their IDs and known metadata) retained.
Person stages at /v1/stages remain separate; they are not used to create deal stages.

A fresh read after a write must confirm the pipeline and all requested stage IDs
before the command is marked succeeded. Missing stage confirmations, permission
errors and interrupted responses leave an uncertain receipt; they do not produce
a completion claim or trigger a blind retry. Duplicate pipeline names and a
conflicting open/closed setting on an existing stage are rejected.

Follow Up Boss represents open/closed with closedStage, rather than separate won
and lost types. The dialog explains that won/lost selections map to closed stages.
The user's three verification/contact-attempt stages are active stages by default.
Pipeline stage names describe structure; this does not create human-activity
triggers or route people/deals automatically.

The read/append preserves the stage IDs and supported metadata it reads immediately
before writing. It is not a distributed transaction against simultaneous edits in
the external CRM. Review the CRM before retrying an uncertain result.

## Confirmation UX

A complete write proposal opens a dialog showing its CRM account and exact details.
Cancel, close, backdrop and Escape do not send a write. Confirm and continue sends
one confirmed command; the existing backend claim/idempotency guard still applies.
The dialog traps keyboard focus and restores focus after closing.

Chat now retains both user and assistant turns. A short "yes, I confirm" reopens a
current, unexpired proposal for that user/account; it does not invoke the LLM or
execute the command. A completed command's actual receipt produces the completion
message in chat and refreshes the resource catalog.

## Evidence and limits

The payload shape was checked against the published @bara-agency/fub-sdk 0.1.1:
PipelineInput.stages is an array of PipelineStage {id?, name?, orderWeight?, color?,
description?, closedStage?}, and pipelines.create/update target /pipelines.
A separate published MCP integration's end-to-end test also distinguishes person
stages from pipelines[].stages[]. No dependency on either package was introduced.

Official docs were blocked by this cloud environment's CONNECT policy. The saved
environment draft adds docs.followupboss.com and api.followupboss.com while
preserving existing domains; review/save/publish the environment to enable direct
checks here. That draft does not change production Railway networking.

Backend tests use HTTP/provider mocks and disposable local SQLite. Browser tests
use actual UI components with labeled sample responses. No private CRM recording,
customer contact, real call, or CRM creation was used as test data. A real test
account write is still needed to validate permissions and this API's behavior on
an actual Follow Up Boss account.
