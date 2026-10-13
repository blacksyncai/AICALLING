"""
House voices — the named Cartesia voices offered as one-click options in the
agent editor, in picker order. New agents default to DEFAULT_VOICE_ID (Lauren).

Voice picker categories (app/routers/settings.py):
- Premium: cloned voices only — entries marked "clone" here, voices owned/cloned
  in the Cartesia account, and any ids in PREMIUM_VOICE_IDS.
- Standard: the other house voices here plus any ids in STANDARD_VOICE_IDS.
The rest of Cartesia's public library isn't listed (a voice id can still be pasted).
Language/accent come from the live Cartesia catalog; nothing here is a guess about them.
"""

VOICE_MODELS = ["sonic-3"]  # the Cartesia TTS model the voice worker uses

FEATURED_VOICES: list[dict] = [
    # Shown in this order in the voice picker. Gender, language and description for entries without
    # them come from the live Cartesia catalog.
    {"id": "e8e5fffb-252c-436d-b842-8879b84445b6", "name": "Jena"},
    {"id": "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4", "name": "Sarah"},
    {"id": "f786b574-daa5-4673-aa0c-cbe3e8534c02", "name": "Kate"},
    {"id": "a5136bf9-224c-4d76-b823-52bd5efcffcc", "name": "Jamison", "gender": "masculine",
     "description": "Easygoing and relaxed. Good for casual outreach and follow-ups."},
    {"id": "6c756032-11c3-4be8-a120-74f9673fb700", "name": "Lauren", "gender": "feminine",
     "description": "Warm, friendly and professional. Great for support and appointment setting."},
    {"id": "5ee9feff-1265-424a-9d7f-8e4d431a12c7", "name": "Paul", "gender": "masculine",
     "description": "The original Paul — thoughtful, steady and confident. Built for sales calls."},
    {"id": "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc", "name": "Ava"},
    {"id": "710feaa3-b550-42f3-b3eb-6f37f2a7cc0a", "name": "Jake"},
    {"id": "95280ca0-610a-41c9-8457-1dcec809da61", "name": "Hamza", "gender": "masculine",
     "description": "Live voice clone.", "clone": True},
    {"id": "97f03c16-fab2-4747-b655-9caefbd68fcf", "name": "Marissa M", "gender": "feminine",
     "description": "Live voice clone.", "clone": True},
]

# New agents start with Lauren (independent of the picker order above).
DEFAULT_VOICE_ID = "6c756032-11c3-4be8-a120-74f9673fb700"
