# Matt: existing ElevenLabs voice

The premium picker entry **Matt** stores `elevenlabs:iRh44YCGcZyLpQjPFMsh`. The provider prefix routes previews and live configurable-agent sessions to ElevenLabs; it never reaches Cartesia. Existing selected voices, agent scripts/objectives, default voice, LLM choices, telephony and customer credit rates are unchanged. This adds an existing voice, not a create-new-clone/upload interface.

`ELEVENLABS_API_KEY` is a server-only Railway variable. The key is never returned to the picker or put in room metadata. LiveKit receives it explicitly because its plugin's automatic environment name is `ELEVEN_API_KEY`, which differs from our application setting.

The installed/pinned plugin is `livekit-plugins-elevenlabs==1.6.4`, via the existing LiveKit extras requirement. Matt uses the supported `eleven_flash_v2_5` model, streaming `auto_mode=True`, mono `pcm_24000`, stability .5 and similarity boost .75. Saved speaking speed is passed through, with the installed plugin's documented .8–1.2 range validated rather than silently clamped. The editor slider uses that range for ElevenLabs voices. Existing pronunciation transforms and voice tracing still apply. Cartesia-only volume control is not sent as an unsupported ElevenLabs parameter.

Preview uses ElevenLabs' PCM endpoint and wraps its response in a valid 24 kHz WAV, with the existing bounded preview cache. Provider errors return a generic actionable message without provider bodies or keys. A missing key fails explicitly instead of switching voices/providers.

Validation: 64 focused tests passed across the new provider integration, existing voice catalog, and voice audit. They cover installed constructor compatibility, exact ID/model routing, valid PCM/WAV conversion, catalog categorization, cache behavior, errors without secret leakage, no provider fallback, invalid paths, persisted selection/speed validation and preserved scripts. The web production build validates the editor change.

Live account permission/voice availability and real synthesized audio have not been verified from this execution environment: `api.elevenlabs.io` returns proxy CONNECT 403. Its domain was added to the existing unpublished development-environment draft. That development restriction does not establish a production connectivity failure. Use Matt's preview after rollout to verify the actual key/voice permissions before assigning to a campaign. No calls were placed or agents reassigned during implementation.

Rollback: choose the previous voice on any agents explicitly switched to Matt. Deploy parent `06b5bd928a84b4a2a9baf13f4f184e40368ead9e` if reverting the integration; existing original voices need no data migration. Do not remove the provider while active agents still select its namespaced ID.
