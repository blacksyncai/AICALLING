# Opt-in Cartesia expressions

Agent → Voice → Voice settings → Voice expressions. Disabled by default. Default emotion applies to every generation; leaving it empty retains the existing Tone setting. A line's leading emotion tag can override delivery. Use a neutral tag to explicitly return to neutral delivery within the same reply. Test the selected voice before relying on a particular emotion.

```text
Opening:
<emotion value="curious"/>Hey, this is James, right?

Instruction: Wait for the recipient's answer. Do not speak this instruction.

After confirmation:
<emotion value="neutral"/>Yeah, I'm calling on behalf of Josh Shiflett.
He asked me to reach out about the property on Ashcombe Drive.
<break time="200ms"/>Is that something you're still looking to sell?
```

These are script instructions for the model, not a multi-turn first-message literal. Put only the first question in First message. A pause is not a user turn. No laughter or filler is inserted by the application. `[laughter]` is allowed only when enabled, with a maximum of one per utterance. Pauses accept integer milliseconds or seconds that resolve to integer milliseconds. Product limits are 2 seconds per pause, 3 seconds total per utterance. Unknown tags/emotions, additional attributes, oversized and incomplete controls are dropped. At most eight emotion controls are allowed per utterance.

## Pipeline and compatibility

- Existing runtime JSON includes Agent.voice_tuning, including browser tests (`call_type=web`); no database migration is needed. The API validates default emotions against a fixed allowlist from Cartesia's official generated GenerationConfig enum.
- LiveKit Agents and Cartesia plugin remain pinned to 1.6.4. The active model remains sonic-3.5; the plugin defaults to Cartesia API version 2025-04-16 and serializes emotion through generation_config. No model or SDK upgrade was made.
- build_instructions adds concise delivery guidance only for opted-in direct Cartesia voices on phone/web channels. Other providers and text chat receive no expression guidance.
- LLM output passes through the existing repeat guard and SpeechGuard. SpeechGuard now safely recognizes permitted controls, including split `[laughter]`, without allowing other stage directions through. The bounded parser never holds a whole reply.
- Enabled sessions replace LiveKit's Markdown filter (which can hold `[laughter]` as an unfinished Markdown link) with streaming control normalization. Emoji filtering remains. Pronunciation substitutions preserve complete control tags. The TTS node revalidates controls after transforms.
- An inline emotion closes the previous TTS generation and prefixes a fresh generation. Ordinary text streams immediately. The configured default emotion is applied to each primary Cartesia stream and to the existing same-model LiveKit Inference fallback's Cartesia emotion option. Per-utterance state and active iterators close on cancellation.
- Fixed first messages are variable-rendered and cleaned with the same opt-in setting, then use session.say through the same TTS node as replies. Drafted openings use the same prompt guidance. Existing session turn-taking, identity-turn and interruption handling remain responsible for waiting for a real answer.
- ElevenLabs, Mistral, Fish Audio, Inworld and prefixed hosted clones do not receive Cartesia-specific controls. Choosing one retains saved configuration but ignores it and strips the markup. Explicit hosted Cartesia clones are conservatively excluded from the opt-in UI; the same-model automatic Cartesia fallback is supported by the installed inference SDK's typed CartesiaOptions contract.
- Preview HTTP requests validate/clean controls and accept the default emotion, with existing caching. Previews are short single-generation samples; use the browser call for conversation and generation-boundary behavior.

## Verification and limitations

Contract checks use the actual installed plugin's serialization and sentence tokenizer, mock provider transports and local fake synthesis streams, without dialing leads. They cover opt-out, split/encoded tags, malformed/oversized controls, pause limits, first messages, replies, API persistence, interruptions, default emotion on successive streams and same-model fallback configuration, pronunciation preservation and other-provider preview cleanup.

Local first-text parser benchmark (1,000 iterations, not audio): disabled median 0.0021 ms / p95 0.0033 ms; enabled median 0.0094 ms / p95 0.0111 ms. Extra generation boundaries can add provider latency; this is not a real audio-latency comparison.

The requested current documentation URLs and api.cartesia.ai were blocked by the workspace's enforced network policy. A draft adding those domains was saved but not activated. Compatibility evidence comes from the installed LiveKit 1.6.4 source and Cartesia's official GitHub generated Python SDK and cookbook; the live capability pages could not be independently re-read. No authenticated audio synthesis or listening comparison was possible. Do not claim that all voices express emotions equally or that sound/real audio latency has been verified.

Official references:
- https://docs.cartesia.ai/build-with-cartesia/capability-guides/volume-speed-emotion
- https://docs.cartesia.ai/build-with-cartesia/capability-guides/ssml-tags
- https://github.com/cartesia-ai/cartesia-python/blob/main/src/cartesia/types/generation_config.py
- https://github.com/cartesia-ai/cookbook/tree/main/examples/audiobook

Release checks: 66 backend tests passed; production Next.js build passed; Playwright checks at 390px and 1440px passed for the expression toggle, default-emotion selection, save payload and modal rendering. Local screenshots are in /workspace/radar-review/{390,1440}-expression-controls.png. These browser tests used API fixtures and did not place calls or synthesize provider audio.

## Automatic delivery

Voice settings now offers Automatic delivery and Script controls. Newly enabling Voice expressions selects Automatic delivery. Existing enabled settings without a mode retain Script controls; no existing agents are silently migrated. Users can choose Natural and balanced, Warm and conversational, Calm and reassuring, Clear and confident, or Custom direction, and enter up to 500 characters of tone guidance. Advanced script syntax stays available but collapsed in Automatic delivery. Try in browser opens the existing browser-test tab without placing a call; starting that test uses the editor's existing save-before-test flow.

Automatic delivery adds private, contextual delivery guidance to the existing voice LLM request. It does not rewrite the stored script, add an extra model request, or force a default emotion across the script. The existing global tone/default emotion is ignored only while Automatic delivery is enabled; switching back restores it. The model is asked to leave most speech untagged, use appropriate common emotions at utterance starts, preserve facts, avoid repetitive fillers, and wait after identity questions.

Automatic laughter is off by default. Its opt-in flag is enforced in the first-message cleaner, the LLM speech guard, streaming text transforms, final TTS node and preview cleaner, not just by prompt instructions. Explicit Script controls preserve existing laughter behavior. Other voice providers remain excluded and receive cleaned speech.

Additional validation: automatic-mode API roundtrip and invalid settings, all five style prompts, disabled/non-voice/provider exclusions, legacy tone and mode preservation, no forced generation emotion in automatic mode, laughter opt-out/opt-in through first-message and streamed synthesis paths. Total focused suite: 74 tests passed. Mobile/desktop browser checks verified style/direction saving, advanced defaults, the browser-test shortcut and legacy settings. Local screenshots: /workspace/radar-review/{390,1440}-automatic-delivery.png. No live model/audio quality claim is made; synthesis access remains blocked in this workspace.
