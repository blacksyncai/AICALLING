import asyncio

from app.agent.speech_guard import clean, guarded

LEAKS = [
    ("I have Wednesday Oct 14 at 11 am or Thursday Oct 15 at 11:30 am. Which works better for you?We need to keep "
     "conversation, but we have to wait for their answer.(Note: The assistant should wait for user response.)",
     "I have Wednesday Oct 14 at 11 am or Thursday Oct 15 at 11:30 am. Which works better for you?"),
    ("Great, Thursday Oct 15 at 11:30 am it is. What's the best email for the invite?We need to capture email then "
     "book.Sure, you can send it to tony@fuentesteam.com.{ \"slot\": \"Thursday\" }",
     "Great, Thursday Oct 15 at 11:30 am it is. What's the best email for the invite?"),
    ("Got it. Could you share the best email address for the invite?Sure, just let me know the email.",
     "Got it. Could you share the best email address for the invite?"),
]


def test_leaked_notes_and_imagined_turns_are_never_spoken():
    for raw, spoken in LEAKS:
        assert clean(raw) == spoken


def test_normal_speech_is_untouched():
    for text in ["We help real estate teams add calling capacity. It's about 11 a.m. in the U.S. Does that work?",
                 "I'm built on BlackSync dot A I. Want me to spell that for you?",
                 "Is tonyjunior@yahoo.com right?"]:
        assert clean(text) == text


def test_streamed_in_pieces():
    async def src():
        for piece in ["Which works ", "better for you?", "We", " need to wait.", "(Note: x)"]:
            yield piece

    async def run():
        cut = []
        out = "".join([c async for c in guarded(src(), cut.append)])
        return out, cut

    out, cut = asyncio.run(run())
    assert out == "Which works better for you?" and cut and cut[0].startswith("We need")
