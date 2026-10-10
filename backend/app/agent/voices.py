"""
House voices — the named Cartesia voices offered as one-click options in the
agent editor. The first one is the default for new agents.
"""

FEATURED_VOICES: list[dict] = [
    {"id": "6c756032-11c3-4be8-a120-74f9673fb700", "name": "Lauren", "gender": "feminine",
     "description": "Warm, friendly and professional. Great for support and appointment setting."},
    {"id": "a5136bf9-224c-4d76-b823-52bd5efcffcc", "name": "Jamison", "gender": "masculine",
     "description": "Easygoing and relaxed. Good for casual outreach and follow-ups."},
    {"id": "5ee9feff-1265-424a-9d7f-8e4d431a12c7", "name": "Paul", "gender": "masculine",
     "description": "The original Paul — thoughtful, steady and confident. Built for sales calls."},
    {"id": "95280ca0-610a-41c9-8457-1dcec809da61", "name": "Hamza", "gender": "masculine",
     "description": "Live voice clone."},
]

DEFAULT_VOICE_ID = FEATURED_VOICES[0]["id"]
