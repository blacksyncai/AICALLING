# Optional campaign caller-number rotation

Enable under Campaign → Calling rules, beside automatic retries. Select 2–20 active numbers owned by the campaign's account and use the arrows to choose A/B/C order. First attempts select A, B, C, A, B, C. Rotation is off by default, including for all existing campaigns; off preserves agent caller number → account default selection. Explicit phone-test caller selection retains its existing override.

Retry policy:

* Same number: use the `from_phone` on that contact's latest outbound call in this campaign. This does not advance the first-attempt cursor. If that number is removed from the active pool, redial fails explicitly until the pool or policy is changed.
* Different selected number: advance through the pool and skip the number on that contact's latest campaign attempt. It may reuse an earlier attempt's number; it guarantees a difference from the immediately previous attempt, not a never-before-used number.

The nullable model columns are added by the existing idempotent startup migration. Equivalent PostgreSQL DDL is in `backend/migrations/20261019_campaign_number_rotation.sql`. NULL enabled means off, NULL policy means same, NULL cursor means zero. Clients cannot set the cursor. Pool edits reset the next selection to A.

Selection is inside the real outbound dispatch path. A tenant-scoped campaign row lock and atomic UPDATE ... RETURNING allocate the cursor. Cursor and call-log writes commit in the same existing transaction, so failed preparation/rollback does not consume a turn. Post-commit carrier failures do consume that attempted selection. Postgres row locking serializes allocations for the same campaign; provider delivery/ringing order may differ from assignment order. A same-number retry is chosen from persisted call history and survives restarts. The selected caller number is saved in the existing call log and passed to existing carrier/trunk routing.

Inactive, released, duplicate, missing or unowned pool numbers are rejected. A pool that becomes invalid does not silently fall back to an unrelated default number. Existing queue setup-error handling may pause the campaign when the pool needs correction. Disabling rotation remains possible with an old inactive pool. Inbound campaigns cannot enable rotation. Campaign timezones, retries, DNC handling, scripts, voices and provider logic are otherwise unchanged.

This distributes call attempts across a pool. It does not guarantee removal of spam labels, verified caller identity, higher attestation or permission to call. Existing carrier registration/reputation workflows remain separate. Return calls to each selected number still depend on that number's inbound routing.

Validation: tests exercise real SQLite transactions, cross-session A/B/C ordering, rollback, same/different retries, invalid/released/unowned number rejection, server-owned cursor reset and unchanged default-off behavior. The existing campaign timezone and outbound tests also run. Live concurrent PostgreSQL allocation and carrier calls are not exercised by these local tests. Browser fixtures verify mobile/desktop ordering, minimum pool size, retry-policy submission and save payloads.

Rollback: turn rotation off on affected campaigns, then revert the code if needed. Retain the additive nullable columns and existing call history. No purchased numbers, carrier resources or scripts are changed by enabling this feature.
