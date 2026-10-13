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
    {"id": "mistral:01a133e4-93c6-7540-98b5-a917a4da562e", "name": "Hamza 2.0", "gender": "masculine",
     "description": "Live voice clone.", "clone": True, "provider": "mistral", "language": "en"},
    {"id": "95280ca0-610a-41c9-8457-1dcec809da61", "name": "Hamza", "gender": "masculine",
     "description": "Live voice clone.", "clone": True},
    {"id": "mistral:01a1340c-90cb-7714-8ee0-02732154b0dd", "name": "Marissa M 2.0", "gender": "feminine",
     "description": "Live voice clone.", "clone": True, "provider": "mistral", "language": "en"},
    {"id": "97f03c16-fab2-4747-b655-9caefbd68fcf", "name": "Marissa M", "gender": "feminine",
     "description": "Live voice clone.", "clone": True},
    # Mistral preset voices — one entry per mood (Mistral exposes each mood as its own voice).
    {"id": "mistral:c69964a6-ab8b-4f8a-9465-ec0925096ec8", "name": "Paul · Neutral", "gender": "masculine", "accent": "American",
     "description": "Relaxed and balanced.", "provider": "mistral", "language": "en"},
    {"id": "mistral:98559b22-62b5-4a64-a7cd-fc78ca41faa8", "name": "Paul · Confident", "gender": "masculine", "accent": "American",
     "description": "Bold, punchy and confident.", "provider": "mistral", "language": "en"},
    {"id": "mistral:1024d823-a11e-43ee-bf3d-d440dccc0577", "name": "Paul · Happy", "gender": "masculine", "accent": "American",
     "description": "Sunny and easygoing.", "provider": "mistral", "language": "en"},
    {"id": "mistral:01d985cd-5e0c-4457-bfd8-80ba31a5bc03", "name": "Paul · Cheerful", "gender": "masculine", "accent": "American",
     "description": "Upbeat and breezy.", "provider": "mistral", "language": "en"},
    {"id": "mistral:5940190b-f58a-4c3e-8264-a40d63fd6883", "name": "Paul · Excited", "gender": "masculine", "accent": "American",
     "description": "Bouncy and spirited.", "provider": "mistral", "language": "en"},
    {"id": "mistral:e3596645-b1af-469e-b857-f18ddedc7652", "name": "Oliver · Neutral", "gender": "masculine", "accent": "British",
     "description": "Slight British accent. Calm and even.", "provider": "mistral", "language": "en"},
    {"id": "mistral:8169ab87-bc99-4669-a5ec-6855860ace24", "name": "Oliver · Confident", "gender": "masculine", "accent": "British",
     "description": "Slight British accent. Firm and decisive.", "provider": "mistral", "language": "en"},
    {"id": "mistral:5ad5d44e-6b4e-4a57-a8a8-4cae088034ed", "name": "Oliver · Cheerful", "gender": "masculine", "accent": "British",
     "description": "Slight British accent. Bright and lively.", "provider": "mistral", "language": "en"},
    {"id": "mistral:e8e5b1de-493c-4061-8414-e2170f9f4b6f", "name": "Oliver · Excited", "gender": "masculine", "accent": "British",
     "description": "Slight British accent. Energetic and crisp.", "provider": "mistral", "language": "en"},
    {"id": "mistral:390c8a2b-60a6-4882-8437-c49a8bd33b63", "name": "Oliver · Curious", "gender": "masculine", "accent": "British",
     "description": "Slight British accent. Thoughtful and engaged.", "provider": "mistral", "language": "en"},
]

# New agents start with Lauren (independent of the picker order above).
DEFAULT_VOICE_ID = "6c756032-11c3-4be8-a120-74f9673fb700"
