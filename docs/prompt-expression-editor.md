# Prompt expression editor

Compatible direct Cartesia and hosted Sonic 3.5 voices expose delivery controls in First message, System prompt, and script sections. Voice compatibility comes from the voices API. Delivery strength varies by voice.

Select a spoken phrase, then choose Curious, Calm, Warm, Confident, Reassuring, Happy, Neutral, or a short pause. Choosing a control explicitly enables voice expressions. Previously disabled agents use script-only mode; existing automatic mode is preserved. Highlighted ranges restore their preceding emotion afterward. Whole spoken phrases are recommended. Instructions to wait for the recipient still belong in the script; expressions do not add turn boundaries.

The editor displays readable text and labeled highlights while storing existing supported speech tags. Lead variables are never split. Unsupported voices cannot add controls; existing annotations remain editable and runtime provider fallback strips unsupported markup.

Verification: production frontend build; 9 range/editing tests; 40 backend expression/streaming/provider tests; Chromium at 390 and 1440 px verifies selection, save/reload, removal, and both first-message and prompt editing. Provider-generated audio was not auditioned because Cartesia API access is unavailable in this environment.


## Generation configuration correction

Highlighted emotions now become generation configuration for each marked passage, instead of depending on inline emotion tags in the provider transcript. Each emotion uses a separate, cached SDK client within the call, so speculative or interrupted speech cannot mutate the settings for another generation. Browser/phone speech and annotated previews use this path; pauses/laughter remain validated provider controls. Trace events record enabled/mode and the applied emotion without retaining speech text. New request-level tests use the installed LiveKit SDK with a simulated WebSocket and synthetic PCM, not provider-generated audio. Authenticated audio attempts from this environment failed to connect, so audible emotion strength remains unverified.

Hamza Versions 1–3 replace Zain in the third premium family position. Existing saved Zain voice IDs remain playable; only their picker entries are hidden.
