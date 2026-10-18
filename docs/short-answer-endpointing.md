# Short-answer endpointing

Observed production: one turn hit 2.501 seconds of endpointing delay while its TTS node first audio took 0.144 seconds. Six replies in another call had SDK e2e latency 0.592–1.042 seconds. These are worker/SDK measurements, not caller-audible timings or a controlled provider comparison.

Change: extend the existing semantic detector adapter to recognize exact English yes/no responses to explicitly closed questions, and greeting acknowledgments to greetings. VAD, dynamic minimum delay, preemptive generation, interruption handling and action commitment remain owned by LiveKit. Numbers, dictated details, alternatives, open questions and incomplete answers delegate to the semantic model. No global silence timer reduction. Saved prompts, voices, models and agent objectives are unchanged.

Installed LiveKit Agents 1.6.4: predict_end_of_turn returns a probability, compared with the delegate's unlikely_threshold. A complete answer returns 1.0, using the normal dynamic minimum delay instead of the semantic maximum. Timing remains adaptive and includes STT/model/media delays; there is no guaranteed 0.59–1.4 second total latency. The installed-SDK offline test verifies the previous semantic maximum is at least 2.4 seconds, eligible answers are below 1 second, and unfinished answers still wait at least 2.4 seconds. This is an endpoint gate test, not a live before/after audio result.

Validation: 66 focused tests in test_opening_turns.py and test_turn_latency.py. Production validation pending: compare complete yes/no, unfinished “yes, but…”, dictated details and interruptions on the same agent. call_config now records the effective TTS provider without credentials. Use voice_trace monotonic offsets for comparison.

Rollback: revert the short-answer endpointing commit and redeploy. No database or carrier changes. Existing VOICE_FAST_IDENTITY_TURNS=false disables this adapter as a temporary operational rollback (including its prior identity shortcut).
