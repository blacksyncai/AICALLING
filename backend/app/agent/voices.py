"""
House voices — the named Cartesia voices offered as one-click options in the
agent editor, in picker order. New agents default to DEFAULT_VOICE_ID (Marissa M).

Voice picker categories (app/routers/settings.py):
- Premium: entries marked "clone" or category "premium" here, voices owned/cloned
  in the Cartesia account, and any ids in PREMIUM_VOICE_IDS.
- Standard: the remaining house voices here plus any ids in STANDARD_VOICE_IDS.
The rest of Cartesia's public library isn't listed (a voice id can still be pasted).
Language/accent come from the live Cartesia catalog; nothing here is a guess about them.
"""

VOICE_MODELS = ["sonic-3"]  # the Cartesia TTS model the voice worker uses

FEATURED_VOICES: list[dict] = [
    # Premium families in picker order; keep each family's versions together.
    {"id": "97f03c16-fab2-4747-b655-9caefbd68fcf", "name": "Marissa M · Version 1", "family": "Marissa M", "tone": "Version 1",
     "gender": "feminine", "description": "Live voice clone.", "clone": True},
    {"id": "fishaudio:v_SriZAPqzgffq", "name": "Marissa M · Version 2", "family": "Marissa M", "tone": "Version 2",
     "gender": "feminine", "description": "Live voice clone.", "clone": True, "provider": "fishaudio", "language": "en"},
    {"id": "fishaudio:v_goYxyDbAUbfP", "name": "Zain · Version 1", "family": "Zain", "tone": "Version 1",
     "gender": "masculine", "description": "Live voice clone.", "clone": True, "provider": "fishaudio", "language": "en"},
    {"id": "95280ca0-610a-41c9-8457-1dcec809da61", "name": "Zain · Version 2", "family": "Zain", "tone": "Version 2",
     "gender": "masculine", "description": "Live voice clone.", "clone": True},
    {"id": "26def8d4-b397-4d79-b5f1-d554d16ba4fe", "name": "Mia", "gender": "feminine", "category": "premium"},
    {"id": "91e4713f-2150-4be6-8564-2d121bbd8c10", "name": "Lauren", "gender": "feminine",
     "description": "Live voice clone.", "clone": True, "language": "en"},
    {"id": "058f0988-5723-49e0-b322-e50034637fe6", "name": "Sofia", "gender": "feminine",
     "description": "Live voice clone.", "clone": True, "language": "en"},
    {"id": "elevenlabs:WkIfOTQgqfIPfV7X7nND", "name": "Sally", "provider": "elevenlabs",
     "clone": True, "description": "Live voice clone.", "language": "en"},
    {"id": "lkcartesia:v_ZMqDxhK7B6i6", "name": "Macco · Version 1", "family": "Macco", "tone": "Version 1",
     "description": "Deep voice clone.", "clone": True, "provider": "cartesia", "language": "en"},
    {"id": "inworld:v_ZMqDxhK7B6i6", "name": "Macco · Version 2", "family": "Macco", "tone": "Version 2",
     "description": "Live voice clone.", "clone": True, "provider": "inworld", "language": "en"},
    {"id": "elevenlabs:iRh44YCGcZyLpQjPFMsh", "name": "Matt", "provider": "elevenlabs",
     "clone": True, "description": "Live voice clone.", "language": "en"},
    {"id": "elevenlabs:Ywuz3KyW2N5pqKNpwcCL", "name": "Mishal", "provider": "elevenlabs",
     "gender": "masculine", "description": "Arabic voice with a Saudi accent.", "language": "ar", "accent": "Saudi"},
    {"id": "mistral:01a1346d-b155-75a6-a670-b9924b477fbf", "name": "Leena · Version 1", "family": "Leena", "tone": "Version 1",
     "gender": "feminine", "description": "Live voice clone.", "clone": True, "provider": "mistral", "language": "en"},
    {"id": "mistral:01a13477-ce35-7031-84e8-71a1f7a51cbd", "name": "Leena · Version 2", "family": "Leena", "tone": "Version 2",
     "gender": "feminine", "description": "Live voice clone.", "clone": True, "provider": "mistral", "language": "en"},
    {"id": "a7b6afa8-fa7f-4b0d-ba37-6cb8d8014919", "name": "Don"},
    {"id": "e8e5fffb-252c-436d-b842-8879b84445b6", "name": "Jena"},
    {"id": "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4", "name": "Sarah"},
    {"id": "f786b574-daa5-4673-aa0c-cbe3e8534c02", "name": "Kate"},
    {"id": "mistral:c69964a6-ab8b-4f8a-9465-ec0925096ec8", "name": "Paul 2.0 · Neutral", "family": "Paul 2.0", "tone": "Neutral", "gender": "masculine", "accent": "American",
     "description": "Relaxed and balanced.", "provider": "mistral", "language": "en"},
    {"id": "mistral:98559b22-62b5-4a64-a7cd-fc78ca41faa8", "name": "Paul 2.0 · Confident", "family": "Paul 2.0", "tone": "Confident", "gender": "masculine", "accent": "American",
     "description": "Bold, punchy and confident.", "provider": "mistral", "language": "en"},
    {"id": "mistral:1024d823-a11e-43ee-bf3d-d440dccc0577", "name": "Paul 2.0 · Happy", "family": "Paul 2.0", "tone": "Happy", "gender": "masculine", "accent": "American",
     "description": "Sunny and easygoing.", "provider": "mistral", "language": "en"},
    {"id": "mistral:01d985cd-5e0c-4457-bfd8-80ba31a5bc03", "name": "Paul 2.0 · Cheerful", "family": "Paul 2.0", "tone": "Cheerful", "gender": "masculine", "accent": "American",
     "description": "Upbeat and breezy.", "provider": "mistral", "language": "en"},
    {"id": "mistral:5940190b-f58a-4c3e-8264-a40d63fd6883", "name": "Paul 2.0 · Excited", "family": "Paul 2.0", "tone": "Excited", "gender": "masculine", "accent": "American",
     "description": "Bouncy and spirited.", "provider": "mistral", "language": "en"},
    {"id": "a5136bf9-224c-4d76-b823-52bd5efcffcc", "name": "Jamison", "gender": "masculine",
     "description": "Easygoing and relaxed. Good for casual outreach and follow-ups."},
    {"id": "6c756032-11c3-4be8-a120-74f9673fb700", "name": "Lauren", "gender": "feminine",
     "description": "Warm, friendly and professional. Great for support and appointment setting."},
    {"id": "5ee9feff-1265-424a-9d7f-8e4d431a12c7", "name": "Paul", "gender": "masculine",
     "description": "The original Paul — thoughtful, steady and confident. Built for sales calls."},
    {"id": "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc", "name": "Ava"},
    {"id": "710feaa3-b550-42f3-b3eb-6f37f2a7cc0a", "name": "Jake"},
    {"id": "mistral:e3596645-b1af-469e-b857-f18ddedc7652", "name": "Oliver · Neutral", "family": "Oliver", "tone": "Neutral", "gender": "masculine", "accent": "British",
     "description": "Slight British accent. Calm and even.", "provider": "mistral", "language": "en"},
    {"id": "mistral:8169ab87-bc99-4669-a5ec-6855860ace24", "name": "Oliver · Confident", "family": "Oliver", "tone": "Confident", "gender": "masculine", "accent": "British",
     "description": "Slight British accent. Firm and decisive.", "provider": "mistral", "language": "en"},
    {"id": "mistral:5ad5d44e-6b4e-4a57-a8a8-4cae088034ed", "name": "Oliver · Cheerful", "family": "Oliver", "tone": "Cheerful", "gender": "masculine", "accent": "British",
     "description": "Slight British accent. Bright and lively.", "provider": "mistral", "language": "en"},
    {"id": "mistral:e8e5b1de-493c-4061-8414-e2170f9f4b6f", "name": "Oliver · Excited", "family": "Oliver", "tone": "Excited", "gender": "masculine", "accent": "British",
     "description": "Slight British accent. Energetic and crisp.", "provider": "mistral", "language": "en"},
    {"id": "mistral:390c8a2b-60a6-4882-8437-c49a8bd33b63", "name": "Oliver · Curious", "family": "Oliver", "tone": "Curious", "gender": "masculine", "accent": "British",
     "description": "Slight British accent. Thoughtful and engaged.", "provider": "mistral", "language": "en"},
]

# Voices in the Cartesia account that the picker should NOT list (owned voices are listed automatically).
HIDDEN_VOICE_IDS = {
    "b77472c7-ed40-40ae-b022-2a264719d520",  # "Giovanna" (was briefly listed as Lina by mistake)
    "e26d5a55-fe5a-4f79-a8e9-ef5580e134cc",  # "lina" (Cartesia) — Leena uses the Mistral clones instead
    "3a5cc58b-260a-4da6-9840-4966242e109e",  # "Leena" (Cartesia) — Leena uses the Mistral clones instead
}

# New agents start with Marissa M (Version 1, the Cartesia house clone).
DEFAULT_VOICE_ID = "97f03c16-fab2-4747-b655-9caefbd68fcf"

# Voices taken out of the picker, and what agents still using them move to (applied at startup).
RETIRED_VOICES = {
    "mistral:01a133e4-93c6-7540-98b5-a917a4da562e": "fishaudio:v_goYxyDbAUbfP",  # Zain (Mistral) → Zain · Version 1
    "mistral:01a1340c-90cb-7714-8ee0-02732154b0dd": "fishaudio:v_SriZAPqzgffq",  # Marissa M (Mistral) → Version 2 (Fish)
    "378695da-44e9-4fc7-a9cb-efcb0d2037cc": "lkcartesia:v_ZMqDxhK7B6i6",  # Macco (old Cartesia clone) → Version 1
    "elevenlabs:diHzndF9D0TjlgUfMwn0": "inworld:v_ZMqDxhK7B6i6",  # Macco (ElevenLabs) → Version 2
}


async def move_retired_voices() -> int:
    """Agents on a retired voice move to its replacement. Idempotent; returns how many agents moved."""
    from sqlalchemy import update

    from app.database import AsyncSessionLocal
    from app.models.agent import Agent

    moved = 0
    async with AsyncSessionLocal() as db:
        for old, new in RETIRED_VOICES.items():
            moved += (await db.execute(update(Agent).where(Agent.voice_id == old).values(voice_id=new))).rowcount or 0
        await db.commit()
    return moved
