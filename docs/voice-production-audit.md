# BlackSync voice audit and limited rollout

Audit date: 2026-10-17. Production baseline: `077691a6660cde8dae7e38dee945148d66019321`, Railway deployment `af047260-d207-4a70-b722-ca42069c98a2` (SUCCESS). This change is prepared for review, not deployed. No agent database rows, customer scripts/objectives, selected voices/models, carrier routing, or infrastructure placement were changed. No calls or external booking/transfer requests were made during validation.

## Three priorities

1. **Measure the real overlapping path.** Existing averages could fall back to adding mean EOU, LLM and TTS durations despite speculation. Stop presenting that sum as a response measurement. Add bounded, content-free, per-call monotonic timelines with speech IDs, generation steps, request attempt IDs, per-call salted turn fingerprints, cancellation, provider consumption, worker output state and tool receipts. Preserve separate SDK stage metrics. A nullable result renders “Not measured” in the dashboard.
2. **Remove verified short-sentence aggregation delay, behind a canary flag.** The installed Cartesia plugin uses BlingFire with a 20-character minimum sentence merge threshold and 10-character lookahead. Lower only the merge threshold to one character with `VOICE_SHORT_SENTENCE_STREAMING=true`; keep lookahead, existing text safety/pronunciation transforms, PCM rate, model, speed and voice. Default is false pending audio evaluation. A complete short sentence followed by later text can now leave the tokenizer before the upstream response finishes. This does not prove earlier caller-audible speech.
3. **Make action results authoritative.** Voice calls can no longer receive mock availability or mock booking receipts from an unconfigured calendar. Distinguish unavailable lookup from no openings. Revalidate a chosen slot before booking, single-flight booking/transfer writes per call, preserve successful receipts if the waiting turn is interrupted, and block automatic retry after uncertain writes. Transfer waits on actual prior playout instead of sleeping 2.5 seconds and records acceptance only after the SIP API responds. Remove forced calendar filler. Make a small built-in prompt clarification about corrections, receipts, two real slots, and uncertainty; retain the customer's script verbatim.

## Verified stack and configuration flow

`web/src/components/agent/VoiceModelSettings.tsx` and `VoiceTuningSettings` → PATCH `/api/agents/{id}` (`app/routers/agents.py`) → Agent columns (`app/models/agent.py`) → `agent_to_runtime()` (`app/agent/runtime.py`) → outbound/inbound/web metadata or private config fetch → `_run_configurable()` (`agent_worker.py`). Calendar secrets are fetched privately and do not travel in room metadata. A per-call duration cap from the dispatcher is retained after config fetch.

The older Paul SDR path remains separate; these changes target dashboard configurable agents. No replacement of provider/model selections was introduced.

Installed locally and pinned for deployment:

| Package | Installed version |
| --- | --- |
| livekit-agents | 1.6.4 |
| livekit-plugins-deepgram/cartesia/silero/turn-detector | 1.6.4 each |
| livekit RTC | 1.1.12 |
| openai | 3.31.0 (transitive, not directly pinned) |

`requirements.txt` pins the LiveKit extras; the running production container cannot be interrogated for its complete wheel inventory through the available API. Thus matching production pins/build ancestry is verified; equality of every transitive wheel is not. No dependency upgrade is proposed here.

The actual sampled LLM is Cerebras `gpt-oss-120b`, not the fallback `gpt-4.1-nano`. Deepgram is `deepgram.STT(model="nova-3")`, not Flux. Cartesia is `sonic-3`; Mistral voice IDs use the separate custom Mistral adapter when its key exists.

## Settings: current → proposed

Values and units below were checked in the installed 1.6.4 constructors/source, not copied from newer vendor examples. Typed dictionaries do not enforce universal numeric ranges; do not mistake annotations for runtime validation.

| Setting | SDK default / current effective setting | Proposed | Reason and tradeoff |
| --- | --- | --- | --- |
| Deepgram `endpointing_ms` | Default 25 milliseconds; app omits it | Preserve | No evidence that STT is the dominant delay. Nova final transcripts are not a separate Flux turn controller. |
| Deepgram interim results / VAD events / sample rate | true / true / 16000 Hz defaults | Preserve | Stream transcripts and preserve recognition quality. |
| Silero `min_speech_duration`, `min_silence_duration`, prefix padding, threshold | .05 s, .55 s, .5 s, .5 defaults | Preserve | Recognition backdates speech end; these delays must not simply be added to endpointing. SDK checks turn-detector minimum VAD silence. |
| Session endpointing | SDK fixed .5–3 s; app **dynamic .35–2.5 s** at responsiveness .75 | Preserve | Dashboard range maps .95–.15 s minimum and 4–2 s maximum. No blanket zeroing of timers. |
| Interruption `min_duration` / `min_words` | SDK .5 s / 0; app **.5 s / 2** at .75 | Preserve pending audio tests | Installed SDK can reject one-word turns overlapping active agent speech. Candidate cause of missed “yes/no,” not proven by current traces. Lowering thresholds risks background/backchannel interruptions. |
| False interruption timeout / resume | SDK 2 s / true; app **3 s / true** | Preserve | Requires comparison of false vs genuine interruptions before lowering. Adaptive/VAD resolved mode is not independently confirmed by production logs. |
| Preemptive generation | SDK enabled; app explicitly enabled | Preserve | Already on. SDK default maximum 3 attempts and 10 s caller speech duration, not unlimited. |
| Preemptive TTS | SDK false; app **true** | Preserve and measure cancellation/audio generation | Earlier generation can cost extra even when audio is never played. Do not add a second speculation controller. |
| Cartesia tokenizer | `min_sentence_len=20`, `stream_context_len=10`, both character counts | Canary `1`, `10` | Quicker complete short sentence; possible changes in prosody/flush frequency and generation cost. Only positive values 1 and 20 are proposed/tested; no universal constructor bounds claimed. |
| Cartesia `max_buffer_delay_ms` | Plugin already sends **0** when sentence flushing is active | Preserve | Not a supported constructor argument in this version. No invented additional knob. |
| Cartesia encoding/sample rate/timestamps | pcm_s16le / 24000 Hz / word timestamps true | Preserve | Let LiveKit handle media adaptation; do not force the internal pipeline to PSTN 8 kHz. |
| Connection lifecycle | Cartesia `prewarm()` during SIP ringing; SDK pooled sockets/context-per-generation | Preserve | Existing warmup works; traces show preparation .059–.064 s in four attempts. Cancellation closes generation tasks; the SDK owns audio queue clearing/history truncation. |
| Fixed transfer wait | 2.5 s regardless of spoken handoff | `RunContext.wait_for_playout()`, capped 12 s, then SIP request capped 15 s | Remove arbitrary waiting without cutting off a long handoff. API acceptance is not proof a human answered. |
| Calendar availability/booking timeout | httpx 8/10 s phase timeouts | Bound total requests to 8/10 s; revalidate before write; no uncertain retry | An extra read can increase tool-turn latency; correctness takes priority. Read failures before a write may be retried; uncertain writes cannot. |
| `VOICE_TURN_TRACE` | No previous setting | true; disable to roll back logging | Bounded numeric/status logs only; small unmeasured production overhead. |
| `VOICE_SHORT_SENTENCE_STREAMING` | No previous setting | false by default | Enable only in a test deployment for matched audio comparison. |
| Response dashboard fallback | Sum of means if observed gap absent | null / “Not measured” | Stops misleading latency reporting; historical estimates remain labeled estimates. |

## Saved, ignored, or substituted settings found

- Temperature is persisted and serialized, but only sent to models whose `llm_endpoint` allows it. This is intentional provider compatibility, not a missing database field.
- Mistral voice speed/volume does not follow the Cartesia path. If a Mistral voice is selected but its key is absent, the existing worker silently uses the default Cartesia voice. This existing behavior is documented as a follow-up; no voice migration was made in this patch.
- The dashboard accepts voice speed .5–2.0; installed Cartesia Sonic 3 documentation in the plugin says .6–2.0. No agent speeds were silently clamped. Validate/surface incompatible values in a later targeted settings change.
- The legacy Paul's dictation hook attempts a dataclass `endpointing` replacement. The active plugin constructor parameter is `endpointing_ms`; exceptions are swallowed. It does not reliably change endpointing, and the configurable agents do not use that hook. Do not claim dictation-aware turn-taking exists in the active path.
- `LOW_RESOURCE_MODE=false` is verified in Railway. It previously controlled semantic fallback; latest connected call explicitly logs `turn_detection=semantic`.
- Latest deployment manifest places **one replica in `sfo`**. API, worker, and Next share the container via `start.sh`; local CPU contention is possible, not measured. Non-low-resource worker uses process execution, SDK load threshold .7, and idle process count min(ceil(available CPUs),4); actual container CPU count/capacity is not exported. Old AWS us-east-2 task definitions are not evidence of this Railway deployment's location.
- LiveKit media/SIP point-of-presence and provider inference regions were not exposed in the available traces. No relocation is justified yet.

## Speculation and interruption audit

Installed `agent_activity.py` starts LLM/TTS before speech scheduling when enabled, then validates transcript, context equivalence, tool set and tool choice after `on_user_turn_completed`. `_CallAgent.on_user_turn_completed` checks voicemail and does not mutate history/tools. This patch adds timing only. There is no measured hook invalidation frequency yet; no restructuring is justified.

The installed SDK authorizes speech before `perform_tool_executions`; tools are not launched from the speculative hook. `CommittedActions` adds a stale/interrupted-turn check and single-flight shielding at execution. Turn fingerprints correlate precommit request vs confirmed transcript without logging text. Speech IDs/generation steps distinguish old output and retries; SDK still owns generation cancellation and queued-audio clearing. The tiny version-gated read-only adapter accesses `_SpeechHandleContextVar` because `session.current_speech` can point to an older playing speech during speculation. It returns no correlation on another SDK version; it never changes SDK state.

Flux `STTv2` exists in the installed plugin: `EagerEndOfTurn` maps to PREFLIGHT_TRANSCRIPT, `TurnResumed` to INTERIM_TRANSCRIPT (abort eager), `EndOfTurn` to FINAL_TRANSCRIPT and END_OF_SPEECH. BlackSync uses Nova, so none are active. No Flux controller was added alongside semantic/VAD detection.

Hard remaining boundary: single-flight is **in-memory per call**. It is not a cross-worker persistent idempotency ledger. Process death after a provider accepted a write still requires reconciliation. Provider booking response is authoritative and availability recheck does not reserve a slot; provider conflict remains possible. Failed/uncertain writes are never described as confirmed. Do not auto-retry unknown outcomes. Cross-provider action persistence is a future change, not claimed completed.

## Measurements and validation

### Production baseline, not before/after proof

Latest deployment logs: 295 rows retrieved; eight relevant lines. Four resource preparations .059–.064 s; one connected session startup .017 s; two TTS-node first-audio durations .139 and .108 s. **Zero ordinary-response gap/e2e samples**. No live p50/p95 or invalidation rate can be inferred. The TTS measurements do not include STT, endpointing, all model work or PSTN playback.

### Offline measured comparison

`backend/scripts/benchmark_voice_streaming.py` uses the **actual installed BlingFire tokenizer**, identical first sentences and later content, a controlled 150 ms upstream pause, six cases × three repeats. Warmed tokenizer first-release p50/p95: **150.51/153.66 ms before, .07/.21 ms after, n=18 each** in the recorded run. Twenty simultaneous local tokenizer streams: **.66/1.56 ms p50/p95, n=20**. These are local text release times, not synthesized audio, full-call load capacity, or an estimate of real-world milliseconds saved.

Final validation: **127 tests passed** across the voice, action, prompt/builder, platform, calendar and recording suites. Next.js production build including lint/type checking passed. Six warnings include SDK/dependency deprecations and SQLite background-thread teardown warnings in existing platform tests; no failed assertions remain.

An offline differential run of the baseline and modified calendar code confirmed the same missing-credential input returned **three mock openings plus a mock booking receipt before**, and explicit rejection after.

Deterministic tests exercise stale availability, empty credentials, provider failure, concurrent duplicate/different slot requests, cancelled write waiters with later success, transfer acceptance vs failure, interruption before transfer, exact installed tool schemas, constructor preservation, immediate sentence release, address/decimal/email preservation, privacy/cancellation of tracing, and non-additive metrics. Existing PCM encode/decode recording tests cover audio transport/recording regressions, not conversational turn timing.

`backend/tests/fixtures/voice_scenarios.json` supplies **40 authored scenarios: 24 development and 16 held-out**, derived from reported failure classes and newly identified risks. They are not claimed to be 40 historical recordings or 40 executed model conversations. Cases cover short answers, pauses, corrections, noise, overlaps, backchannels, repeated questions, stale/failed tools, duplicate actions, opt-out and ending. The held-out set was defined before final validation and has not been used to tune a model/prompt against end-to-end results.

Current environment cannot reach `api.deepgram.com`, `api.cartesia.ai`, or `api.cerebras.ai` (proxy CONNECT 403). Additive network access was saved as an environment draft, preserving existing domains; it is not active or published. Provider keys are present in production; they were not copied into source or test artifacts. Local paid-provider/audio/model evaluations, stochastic repetitions, expected full-call concurrency and caller-side listening remain **unrun**. No billing/cost estimate is asserted; new trace fields expose generated audio duration, characters, tokens, cancellation and pooled connection reuse for later reconciliation.

### Measurement contract

Each `voice_trace` has `clock_id`, process-relative `offset_ms`, stage, optional speech ID/generation step/attempt. Stages include user state, transcript availability, turn commitment, LLM request/first chunk, usable guarded text, first TTS input, first generated PCM frame, generated PCM duration, worker speaking/listening state, semantic predictor timing, tools and terminal outcomes. Provider metrics include cancellations/consumption. Logs do not contain caller transcripts, audio, emails, tool arguments or secrets.

`user_state` timestamps are callback receipts, **not the exact acoustic last speech sample**. SDK message metrics supply backdated EOU/transcription/e2e durations. `agent_speaking` is a worker output event, **not proof the caller heard sound**. `tts_input_first` precedes the plugin's internal sentence aggregation; `tts_audio_first` proves generated PCM only. No independently timestamped RTP publication or handset-audibility probe is installed. Meaningful onset vs filler requires listening annotation; manual `say` (startup/filler) is separate from ordinary `generate_reply`. Do not treat the first token, filler, first generated audio, publication and actual audibility as interchangeable.

`backend/scripts/voice_trace_report.py` reads JSONL, Railway message rows or the actual console-rendered logs and writes JSON distributions and an expandable HTML timeline per speech, using only same-clock offsets and the SDK's direct e2e duration. It never sums overlapping stages or joins clocks across processes. Uncorrelated events remain uncorrelated. Interruption/recovery grouping is conservative; SDK `interrupted` does not itself prove a genuine interruption. The report marks unmeasured caller audibility, meaningful onset, and invalidation reasons. No synthetic timelines are presented as production data.

## Limited rollout and rollback

1. Review the code and focused validation artifacts. Deploy first to a test service, not all accounts. Keep `VOICE_SHORT_SENTENCE_STREAMING=false`; leave all current customer settings unchanged. Enable trace logging for controlled sessions.
2. Complete environment review/save and publish of the saved provider-domain additions if running paid provider tests here. No token replacement is needed for that network change. Record actual worker/media/inference regions and SDK inventory at test startup.
3. Run the 24 development cases at current settings. Use fixed agent configuration hashes and the same caller audio. Repeat stochastic cases at least three times. Use sandbox calendar/SIP doubles for action writes; separately authorize any selected real call/booking test. Record caller-side audio with a synchronization marker to measure audibility. Annotate meaningful first response, cutoffs, missed turns, false interruptions, correctness, action receipts, task completion and billed generation.
4. Repeat with sentence canary enabled, keeping all other settings fixed. Then evaluate the 16 held-out cases without prompt changes. Compare concurrency 1 and the account's actual expected simultaneous-call load (not the local tokenizer's 20-stream result). Report n/p50/p95 separately for startup, ordinary, tool and recovery turns; report cancellation/generated audio and provider cost separately.
5. Advance only if ordinary caller-audible p50 <900 ms and p95 <1500 ms are approached without worse correctness, cutoffs, task completion or speech quality. These are provisional goals, not measurements achieved here. Stop on duplicate side effects, false success or materially worse interruptions.
6. Roll back streaming instantly with `VOICE_SHORT_SENTENCE_STREAMING=false` and restart workers normally. Disable trace with `VOICE_TURN_TRACE=false`. Keep the action safety fix; reverting it would restore simulated phone bookings. For full rollback deploy baseline `077691a...` during a drain window, with that risk explicitly acknowledged. No schema or agent data migration is needed. Never restart active call workers abruptly merely to change flags.

## Remaining work, outside the first three changes

Authoritative compact state beyond tool receipts still relies on the committed SDK conversation/history and custom script. A correction rule is not a structured-state extractor. Do not claim full state tracking or intelligence improvements without model evaluation. Add structured state only after observed correction/repetition failures justify its schema and tests. Also defer model changes, Flux migration, VAD/silence/interruption tuning, relocation, capacity changes, persistent action ledger, and provider switching until matched measurements identify the next bottleneck.
