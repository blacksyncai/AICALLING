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

VOICE_MODELS = ["sonic-3.5"]  # the Cartesia TTS model the voice worker uses (more natural, faster first audio)

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
    {"id": "inworld:v_PmKa7bajvjhe", "name": "Kate · Version 1", "family": "Kate", "tone": "Version 1",
     "gender": "feminine", "description": "Live voice clone.", "clone": True, "provider": "inworld", "language": "en"},
    {"id": "fishaudio:v_PmKa7bajvjhe", "name": "Kate · Version 2", "family": "Kate", "tone": "Version 2",
     "gender": "feminine", "description": "Live voice clone.", "clone": True, "provider": "fishaudio", "language": "en"},
    {"id": "lkcartesia:v_PmKa7bajvjhe", "name": "Kate · Version 3", "family": "Kate", "tone": "Version 3",
     "gender": "feminine", "description": "Live voice clone.", "clone": True, "provider": "cartesia", "language": "en"},
    {"id": "26def8d4-b397-4d79-b5f1-d554d16ba4fe", "name": "Mia", "gender": "feminine", "category": "premium"},
    {"id": "lkcartesia:v_ZMqDxhK7B6i6", "name": "Macco · Version 1", "family": "Macco", "tone": "Version 1",
     "description": "Deep voice clone.", "clone": True, "provider": "cartesia", "language": "en"},
    {"id": "inworld:v_ZMqDxhK7B6i6", "name": "Macco · Version 2", "family": "Macco", "tone": "Version 2",
     "description": "Live voice clone.", "clone": True, "provider": "inworld", "language": "en"},
    {"id": "91e4713f-2150-4be6-8564-2d121bbd8c10", "name": "Lauren · Version 1", "family": "Lauren", "tone": "Version 1", "gender": "feminine",
     "description": "Live voice clone.", "clone": True, "language": "en"},
    {"id": "inworld:v_9thNgvPeCfcX", "name": "Lauren · Version 2", "family": "Lauren", "tone": "Version 2",
     "gender": "feminine", "description": "Live voice clone.", "clone": True, "provider": "inworld", "language": "en"},
    {"id": "fishaudio:v_9thNgvPeCfcX", "name": "Lauren · Version 3", "family": "Lauren", "tone": "Version 3",
     "gender": "feminine", "description": "Live voice clone.", "clone": True, "provider": "fishaudio", "language": "en"},
    {"id": "058f0988-5723-49e0-b322-e50034637fe6", "name": "Sofia", "gender": "feminine",
     "description": "Live voice clone.", "clone": True, "language": "en"},
    {"id": "elevenlabs:WkIfOTQgqfIPfV7X7nND", "name": "Sally", "provider": "elevenlabs",
     "clone": True, "description": "Live voice clone.", "language": "en"},
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
    # Language voices (Cartesia Sonic 3.5), listed under Standard voices.
    {"id": "002622d8-19d0-4567-a16a-f99c7397c062", "name": "Huda", "gender": "feminine", "language": "ar", "description": "Arabic. Natural and clear for conversations."},
    {"id": "fc923f89-1de5-4ddf-b93c-6da2ba63428a", "name": "Nour", "gender": "feminine", "language": "ar", "description": "Arabic. Warm and friendly."},
    {"id": "b4b8e2af-6139-466e-a93a-30c20d2e1fc5", "name": "Fernanda", "gender": "feminine", "language": "es", "description": "Spanish (Mexico). Warm and approachable."},
    {"id": "2fc4f1ec-bfd0-46f1-8e6d-d4279eaaf838", "name": "Mateo", "gender": "masculine", "language": "es", "description": "Spanish (Mexico). Friendly and confident."},
    {"id": "3b7d569e-01fc-45ef-b74b-29460956c691", "name": "Josette", "gender": "feminine", "language": "fr", "description": "French. Calm and polished."},
    {"id": "d9f4af15-c402-4f50-bbda-d8823d028d6a", "name": "Henri", "gender": "masculine", "language": "fr", "description": "French. Clear and professional."},
    {"id": "ac197a78-cec7-4c50-93e5-93bdc1910b11", "name": "Jennifer", "gender": "feminine", "language": "de", "description": "German. Bright and clear."},
    {"id": "f6f315e4-4fb3-4440-92ea-2edb01f9bf1b", "name": "Hermann", "gender": "masculine", "language": "de", "description": "German. Steady and trustworthy."},
    {"id": "8d826d43-20ad-4c56-8d37-1048eccca1bf", "name": "Larissa", "gender": "feminine", "language": "pt", "description": "Portuguese (Brazil). Warm and lively."},
    {"id": "616c64d7-f541-436b-9b8d-e79cfbe19ef9", "name": "Felipe", "gender": "masculine", "language": "pt", "description": "Portuguese (Brazil). Relaxed and friendly."},
    {"id": "d718e944-b313-4998-b011-d1cc078d4ef3", "name": "Liv", "gender": "feminine", "language": "it", "description": "Italian. Friendly and expressive."},
    {"id": "79693aee-1207-4771-a01e-20c393c89e6f", "name": "Marco", "gender": "masculine", "language": "it", "description": "Italian. Confident and clear."},
    {"id": "7a5d4663-88ae-47b7-808e-8f9b9ee4127b", "name": "Hua", "gender": "feminine", "language": "zh", "description": "Chinese (Mandarin). Gentle and clear."},
    {"id": "16212f18-4955-4be9-a6cd-2196ce2c11d1", "name": "Hao", "gender": "masculine", "language": "zh", "description": "Chinese (Mandarin). Calm and professional."},
    {"id": "861213b7-f057-45c8-9527-0f4c144f1a03", "name": "Haruka", "gender": "feminine", "language": "ja", "description": "Japanese. Polite and warm."},
    {"id": "1d210168-d764-462c-8ab6-288a6d5a9579", "name": "Hiroshi", "gender": "masculine", "language": "ja", "description": "Japanese. Calm and composed."},
    {"id": "15628352-2ede-4f1b-89e6-ceda0c983fbc", "name": "Jiwoo", "gender": "feminine", "language": "ko", "description": "Korean. Bright and friendly."},
    {"id": "e1717dc3-b87b-4720-aa7f-b6db290e0609", "name": "Taehyun", "gender": "masculine", "language": "ko", "description": "Korean. Clear and confident."},
    {"id": "a81fccdc-5595-4dfc-ae76-4de6a515b8a2", "name": "Meera", "gender": "feminine", "language": "hi", "description": "Hindi. Warm and conversational."},
    {"id": "910fb75e-1d20-4840-ac63-ac6b26a71bdc", "name": "Dev", "gender": "masculine", "language": "hi", "description": "Hindi. Friendly and clear."},
    {"id": "fa7bfcdc-603c-4bf1-a600-a371400d2f8c", "name": "Leyla", "gender": "feminine", "language": "tr", "description": "Turkish. Warm and clear."},
    {"id": "91e91d74-8eb4-43cd-97d3-7466c21db00d", "name": "Aykut", "gender": "masculine", "language": "tr", "description": "Turkish. Confident and steady."},
    {"id": "9261664a-c3d0-4200-9038-5466bcf3a09c", "name": "Luz", "gender": "feminine", "language": "tl", "description": "Filipino (Tagalog). Friendly and upbeat."},
    {"id": "91e72442-c0fc-46a9-b949-4ac132b6f0eb", "name": "Alden", "gender": "masculine", "language": "tl", "description": "Filipino (Tagalog). Calm and approachable."},
    {"id": "9ed9f7e7-3ef6-4773-9dd3-ffcb479ca1f0", "name": "Olga", "gender": "feminine", "language": "ru", "description": "Russian. Clear and composed."},
    {"id": "60e94cf5-8069-459f-a91e-3ff852a51107", "name": "Isa", "gender": "feminine", "language": "nl", "description": "Dutch. Friendly and natural."},
    {"id": "ea7b5eee-39d9-40b0-b241-1910cbca9c62", "name": "Kasia", "gender": "feminine", "language": "pl", "description": "Polish. Warm and clear."},
    {"id": "43e52207-96fc-4e01-aaf8-cae317e43fdb", "name": "Kacper", "gender": "masculine", "language": "pl", "description": "Polish. Steady and friendly."},
    {"id": "935a9060-373c-49e4-b078-f4ea6326987a", "name": "Linh", "gender": "feminine", "language": "vi", "description": "Vietnamese. Gentle and friendly."},
    {"id": "0e58d60a-2f1a-4252-81bd-3db6af45fb41", "name": "Minh", "gender": "masculine", "language": "vi", "description": "Vietnamese. Clear and calm."},
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
    "lkcartesia:v_9thNgvPeCfcX": "inworld:v_9thNgvPeCfcX",  # Lauren · Version 2 → Inworld TTS 2
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
