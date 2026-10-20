# Voice startup and turn detection repair

Production observations from deployment 0259d5ca-58fc-40b4-b906-f4f7d5902fda, October 16, 2026:

- Six sampled configurable calls logged turn_detection=vad and turn_detector_unavailable (RuntimeError), despite LOW_RESOURCE_MODE=false.
- Matching logs report missing languages.json for livekit-plugins-turn-detector.
- Semantic turn detection was imported inside a job, after CLI download-files and inference-runner startup. The installed LiveKit 1.6.4 SDK registers both model-download plugins and inference runners on import, and reads languages.json locally during model construction.
- Six opening waits ranged from 1.22 to 3.04 seconds. That metric covers greeting-listening/opening preparation only, not complete pickup-to-audio time.
- Only two session-state response samples were present in the queried log window (0.711 and 2.030 seconds). These are too few to establish typical latency and exclude carrier playback delay. The sampled agent used gpt-oss-120b; no model change is part of this repair.

Changes:

1. Import the turn-detector plugin before worker/CLI startup so download-files includes it and inference runners are registered before processes start. Respect the existing low-resource runtime opt-out.
2. Model-download failures now fail the Docker build instead of silently deploying without required assets. The currently running production image remains unaffected until a successful deployment.
3. Load Silero VAD in LiveKit's process prewarm hook; reuse it through process userdata, with a lazy fallback for contexts lacking prewarm.
4. Construct configurable providers and instructions before waiting for the SIP answer. Start supported voice socket prewarming during ringing, with shutdown cleanup even on unanswered calls. Session audio/listening, billable call clocks, transcript times and normal greeting delivery remain after the answer gate. Bandwidth's existing answer-first dispatch cannot benefit from preparing during ringing; native SIP carriers can.
5. Log setup duration, post-answer session-start duration and numeric SDK ChatMessage stage metrics (transcription, end-of-turn, LLM first token, TTS first audio, SDK e2e). These overlap and must not simply be added as a total. Socket prewarm_started means attempted, not proof of a completed handshake. No transcript or credential is included in the added timing logs.

Validation: 30 focused backend regression tests passed, including fresh-process plugin/runner registration, shared VAD reuse, prewarmed voice cleanup and graceful warmup failure, streaming guards and timing sanitization. Python compile and worker CLI help passed. No frontend files changed. The real Hugging Face model download, semantic model inference, provider WebSocket handshake and live call comparison have not been verified in this execution environment. Production build/download and a controlled call are required before claiming runtime restoration or a measured speed improvement.

Unchanged: LLM selection, customer scripts, greeting wait, turn-taking thresholds, AMD behavior and carrier configuration. Restoring semantic turn detection may wait appropriately on unfinished sentences; it is not a guarantee of shorter pauses on every turn.
