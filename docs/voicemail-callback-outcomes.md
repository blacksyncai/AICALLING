# Voicemail and callback outcomes

## Cause and provider boundaries

The configured phone worker uses Deepgram Nova-3 for speech transcription (Cartesia for Filipino).
The final transcription event supplies text and finality to the application's greeting/screening matcher.
This integration does not receive a Deepgram callback-intent or voicemail verdict. Deepgram transcription
can affect the words available, but the incorrect business outcome is assigned downstream.

The worker also uses LiveKit AMD with a separate Deepgram STT and an OpenAI classifier when configured.
Its category, reason, and now its existing is_machine boolean are recorded as answer_detection tool evidence.
These are LiveKit AMD results, not carrier or Deepgram intent labels. The inspected SIP/carrier services
handle dialing, bridging and disconnects; no carrier AMD verdict is used in this classification flow.

Two downstream paths allowed the error: reconciliation only corrected no-answer/voicemail to completed
when someone spoke, and automatic analysis preserved an agent-selected callback even when the transcript
was a greeting. In addition, "name and reason for calling" could be treated as screening before
"leave your name" was recognized as voicemail.

## Changes

- Definite voicemail phrases take precedence over overlapping screening phrases.
- Shared reconciliation excludes greeting/screening speech, consults worker and AMD evidence, and
  allows subsequent live replies to supersede machine detection. Broad "call you back" hints alone
  no longer establish whether a live person answered.
- Callback requires live contact deferral/request evidence or live agreement to an agent's callback offer.
  An agent offer alone, silence, a screener hold, or a hello does not establish a request.
- The live end-call tool, backend outcome report, and automatic analysis apply the same reconciliation.
  Recorded greetings cannot retain callback/qualified labels merely because the agent chose them first.
- Once screening passes, the worker stops applying opening-greeting detection to the live person's response.
- Both live instructions and analysis definitions distinguish recorded callback promises from live requests.

The corrected outcome is saved before contact status, campaign qualification counters, Radar outcome
conditions, CRM outcome mapping, call.completed events, and callback alert filters consume it.
Voicemail retains normal campaign retry eligibility; genuine callbacks retain follow-up routing.
A previous real callback or manually advanced contact stage is still protected by existing contact-stage
rules when a later, separate call reaches voicemail.

## Verification and release

The Call outcome regressions Actions workflow runs the focused regression suite plus existing
outcome, screening, contact-stage, campaign, Radar, and alert tests with the repository's temporary
SQLite fixture. It uses no production credentials and places no calls.

Deploy the same reviewed commit to both backend API and LiveKit worker so prompt, live detection,
and post-call reconciliation agree. No schema migration, database provisioning/reset, or historical
repair job is required. The existing ECS workflow is manual and explicitly documents that its AWS
account belongs to the original Pounce deployment; verify the actual BlackSync release target before
using it. This change does not execute a deployment.

## Limits

Detection remains heuristic and depends on transcription quality and available context. Personal
recordings and very short live answers can be indistinguishable from text alone. Callback phrase
evidence currently recognizes English requests/deferrals and English agreement; multilingual intent
evidence needs separate coverage before extending this guard to other languages. Confirmed bookings,
transfers, do-not-call decisions, and existing screened-call semantics remain protected.
Existing delivered events/alerts cannot be recalled by this fix. No historical calls are modified
as part of implementation or validation.
