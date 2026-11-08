# Voice expressions through MCP

Both the customer MCP (/api/mcp) and admin MCP (/api/admin-mcp) use the shared tool definitions.

- get_agent returns voice_tuning, including stored automatic/script mode, delivery style/direction, laughter flag and manual emotion settings. voice_expressions_supported describes compatibility for the selected voice, independently of whether controls are enabled.
- create_agent accepts voice_tuning, validates it through the same AgentUpdate/VoiceTuning model as the app, and returns the saved tuning. New agents still start paused.
- update_agent accepts a partial voice_tuning object and merges its keys with the saved tuning before invoking the app's update function. Unspecified volume, turn-taking, pronunciations, voicemail timing and expression settings remain intact. A provided pronunciations array replaces that list. Empty objects, unknown settings and invalid values fail without updating an agent.
- list_voices returns per-voice compatibility and available modes, delivery style labels, documented emotion values and the automatic laughter default. It performs no synthesis.

Example update_agent arguments:

```json
{
  "agent_id": "<agent UUID>",
  "voice_tuning": {
    "expressions_enabled": true,
    "expression_mode": "automatic",
    "delivery_style": "warm",
    "delivery_direction": "Be curious for identity questions and softer if they are busy.",
    "automatic_laughter": false
  }
}
```

Admin calls retain the existing selected-account/account_id flow and audit logging. No OAuth scopes, tenant access or call-launch permissions changed. No agent is enabled, called or migrated merely by deploying these schema changes. Clients caching an old tool list may need to refresh BlackSync's tools; existing connection credentials remain valid.

Validation: 24 tests passed through the actual local OAuth and regular/admin MCP HTTP endpoints. They cover schema discovery, creation/readback, partial-update preservation, idempotent repeats, disabling without erasing directions, invalid values, provider compatibility and cross-account denial. No live customer data was changed and no calls or provider synthesis were performed.
