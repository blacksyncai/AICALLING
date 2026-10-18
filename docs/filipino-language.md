# Filipino (Tagalog)

Editor and builder offer Filipino (Tagalog), code `tl`, with the Philippines flag. Existing agent selections are unchanged. Runtime language instructions preserve the saved business script and ask for Filipino speech. Voice previews use a Filipino sample.

Provider routing: `tl` uses Cartesia ink-whisper transcription (streaming and `tl` explicitly listed by installed livekit-plugins-cartesia 1.6.4), leaving other languages on Deepgram nova-3. TTS retains the selected voice. Cartesia receives `tl`; ElevenLabs Flash v2.5 receives its Filipino code `fil` in both worker and preview requests. No voice is silently substituted.

Validation: catalog/save preservation, installed STT and ElevenLabs constructors, language mapping and runtime instructions tested; frontend typecheck and production build. Live audio pronunciation and latency are not validated by these tests. Direct provider metadata requests were blocked by this environment's network policy; no claim of a successful live Filipino call is made.

Rollback: revert this commit and redeploy. No data migration or carrier changes. Agents saved with `tl` should be changed to their previous language before rollback.
