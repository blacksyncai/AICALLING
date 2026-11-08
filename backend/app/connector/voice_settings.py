"""Discoverable MCP voice settings; validation still uses the agent API's VoiceTuning model."""
from app.agent.expressions import DELIVERY_STYLES, EMOTIONS

VOICE_TUNING_SCHEMA = {
    "type": "object", "additionalProperties": False, "minProperties": 1,
    "description": "Voice expression and tuning settings. Updates merge only the keys provided; other settings stay. "
                   "For automatic delivery set expressions_enabled=true and expression_mode=automatic, then choose "
                   "delivery_style or describe delivery_direction in plain English. Laughter defaults off in automatic mode. "
                   "Script controls use expression_mode=script. Read current settings with get_agent; list_voices lists options.",
    "properties": {
        "expressions_enabled": {"type": "boolean"},
        "expression_mode": {"type": "string", "enum": ["automatic", "script"]},
        "delivery_style": {"type": "string", "enum": list(DELIVERY_STYLES)},
        "delivery_direction": {"type": "string", "maxLength": 500,
                               "description": "Tone guidance, never spoken, e.g. Be curious about the property and softer if they are busy."},
        "automatic_laughter": {"type": "boolean", "description": "Allow occasional laughter in automatic mode; off by default."},
        "default_emotion": {"type": "string", "enum": ["", *EMOTIONS],
                            "description": "Script-mode default emotion; empty uses the existing tone. Ignored in automatic mode."},
        "tone": {"type": "string", "enum": ["", "warm", "upbeat", "calm", "friendly", "empathetic"]},
        "volume": {"type": "number", "minimum": .5, "maximum": 2},
        "responsiveness": {"type": "number", "minimum": 0, "maximum": 1},
        "interruption": {"type": "number", "minimum": 0, "maximum": 1},
        "voicemail_min_connected_seconds": {"type": "number", "minimum": 0, "maximum": 60},
        "pronunciations": {"type": "array", "maxItems": 50, "description": "Replaces the agent's pronunciation list when provided.",
                           "items": {"type": "object", "additionalProperties": False, "required": ["word", "say"],
                                     "properties": {"word": {"type": "string", "maxLength": 60},
                                                    "say": {"type": "string", "maxLength": 120}}}},
    },
}
