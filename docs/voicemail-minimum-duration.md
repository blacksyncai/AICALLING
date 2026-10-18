# Voicemail minimum connected duration

Actions → Voicemail exposes “Minimum connected time (seconds)”, default 6.2, range 0–60 in 0.1-second UI steps. Stored in the existing agent voice_tuning JSON as voicemail_min_connected_seconds; no database migration. Existing agents without a value use 6.2. Zero disables the minimum.

The worker measures elapsed time using its monotonic connected/session-start clock, set after SIP answer. Ringing time is excluded. Voicemail detection still interrupts agent speech immediately; the hangup waits silently for the remaining minimum. Calls already exceeding the minimum get no additional delay. Leaving a voicemail still waits for the greeting and finishes message playout. Both detected-voicemail and tool voicemail hangups enforce the floor; the silence watchdog defers to detected voicemail handling. Caller/carrier disconnects cannot be prevented. Normal human calls are unchanged.

This is application timing, not a guarantee about carrier billing intervals, spam reputation, short-duration call classification or regulatory compliance. Scheduled execution and network teardown can make actual duration longer than 6.2 seconds.

Validation: 24 focused voicemail/timing/tuning tests, API persistence/range checks, frontend typecheck and production build. No live carrier-duration measurement performed by these tests. Test an early voicemail greeting and inspect answered-to-ended carrier timestamps before claiming a carrier-side outcome.

Rollback: revert this commit and redeploy; optional JSON field is harmless to old code. Per-agent setting 0 disables the new floor without a code rollback.
