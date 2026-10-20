# Direct call transfer reliability

BlackSync's built-in transfer_call tool calls LiveKit TransferSIPParticipant.
This is a SIP REFER/direct handoff, not a consultative warm transfer. No external
LLM tool/plugin is required. The originating carrier must accept the handoff and
be able to dial the destination. Browser test calls have no SIP leg and cannot
exercise this path. Warm introductions and returning to the AI after an unanswered
consultative call would require a separate bridge design.

Verified code defects:
- An outer 15-second asyncio timeout interrupted the SDK's longer transfer RPC.
  Installed livekit-api 1.2.1 explicitly outlasts the ring window (30+2 seconds
  by default), so the application deadline could fire while the destination rang.
- Any non-throwing API response was marked transferred, ignoring the response's
  failed/ongoing/successful status.
- Participant lookup required a sip_ identity prefix; inbound SIP identities need
  not use it.
- Transfer settings were neither normalized nor validated on save.
- end_call could claim transferred without a completed transfer receipt, and
  activity reporting counted explicit failed transfer tool entries.

Changes:
- Explicit 45-second ringing_timeout, 55-second SDK timeout, 60-second outer
  deadline. These are seconds; the protobuf ring field is a Duration. This is
  configuration, not a guarantee that every carrier rings for exactly 45 seconds.
- Select a unique SIP caller using participant kind/attributes, with a legacy
  prefix fallback; refuse ambiguous multi-leg selection.
- Mark success only for STS_TRANSFER_SUCCESSFUL. Failed and ongoing/empty/legacy
  responses never claim completion. Existing committed-action single-flight
  shielding preserves receipts after interruption and avoids application retries.
- E.164 normalization on save and runtime validation for legacy/builder settings.
- Safe operational logs include call ID, result/reason, exception type, and SIP
  status when available. They omit raw provider errors/credentials/destinations.
- Guard unperformed transferred hangups and explicit failed activity receipts.
  Legacy activity entries without result metadata retain historical behavior.
- UI now describes direct phone-only transfer, not a warm introduction.

Installed versions verified: agents 1.6.4, api 1.2.1, protocol 1.1.27. API/protocol
are now explicitly pinned so production uses the response fields and method
parameters verified locally. uv pip check confirms installed compatibility.
Sources: installed sip_service.py, _dial_timeout.py, RunContext.wait_for_playout,
protobuf descriptors, and livekit/sip source transfer handling. Caller-side
carrier acceptance cannot be proven from constructor tests.

Validation includes real protobuf responses for success/failure/ongoing, destination
normalization, ambiguous participant rejection, no retries after unknown/failed
results, interruptions before handoff, receipts after a canceled waiter, rejected
invalid saved settings without overwriting prior values, no false transferred
hangup, and activity reporting. Web production build passes.

Recent retained production log samples did not identify the user's failed transfer.
A specific agent/call time and controlled real phone-call test are still needed.
No test call was placed and no transfer was initiated against a live caller.

Test procedure:
1. Agent -> Actions -> Transfer to human: set the receiving phone number and save.
2. Place a real phone test call to a test recipient; browser tests are unsupported.
3. Ask for a human, answer the receiving phone, and verify two-way audio.
4. Separately test no-answer/busy and inspect call_transfer_result or
   call_transfer_unconfirmed by call_log_id before broad campaign use.
5. If the carrier rejects REFER, use the logged SIP/error code to investigate its
   transfer policy. Do not automatically retry or add an unverified second leg.

Rollback: revert the transfer-fix commit as a unit. Keep current agents' saved
E.164 destinations (valid under both versions). Dependency pins may remain; no
schema or infrastructure changes are required. Returning to the old code restores
its 15-second cutoff and weak outcome accounting, so prefer pausing transfers by
clearing the affected agent's transfer number while investigating carrier issues.
