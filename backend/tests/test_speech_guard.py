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


def test_stage_directions_in_brackets_are_not_spoken():
    assert clean("Okay, thanks so much. Have a great day! [Call ended]") == "Okay, thanks so much. Have a great day!"
    assert clean("[Call ended]") == ""


def test_internal_names_are_not_spoken_but_emails_with_underscores_are():
    assert clean("Got it, thanks for your time. end_call") == "Got it, thanks for your time."
    assert clean("Is that john_smith@gmail.com?") == "Is that john_smith@gmail.com?"


def test_complete_short_sentence_reaches_tts_before_upstream_finishes():
    from app.agent.voice_tuning import pronounce, BUILT_IN_PRONUNCIATIONS
    async def run():
        unblock=asyncio.Event()
        async def source():
            yield 'Yes, absolutely. '
            await unblock.wait()
            yield 'What works for you?'
        stream=pronounce(BUILT_IN_PRONUNCIATIONS)(guarded(source()))
        try:
            first=await asyncio.wait_for(anext(stream),timeout=0.2)
            assert first=='Yes, absolutely.'
            unblock.set()
            assert ''.join([part async for part in stream])==' What works for you?'
        finally:
            await stream.aclose()
    asyncio.run(run())


def test_sentence_release_keeps_cross_chunk_leak_protection():
    samples=[raw for raw,_ in LEAKS]+[
        'Fine. The assistant should wait.', 'Thanks! end_call', 'Okay. functions.book_appointment',
        'Yes. assistant: internal notes', 'Good. [Call ended]', 'Done. {"internal":"value"}',
        'We help the U.S. teams. Ready?', 'Is sam_smith@example.com correct?',
    ]
    async def run(text,size):
        async def source():
            for i in range(0,len(text),size):yield text[i:i+size]
        return ''.join([x async for x in guarded(source())]).strip()
    for text in samples:
        expected=clean(text)
        for size in range(1,len(text)+1):
            assert asyncio.run(run(text,size))==expected,(text,size)


def test_sentence_release_does_not_split_a_domain_or_decimal_at_a_chunk_edge():
    from app.agent.speech_guard import SpeechGuard
    for first,rest in [('Visit blacksync.','ai now. '),('The rate is 1.','25 per minute. ')]:
        g=SpeechGuard()
        assert g.feed(first)==''
        assert (g.feed(rest)+g.flush()).strip()==(first+rest).strip()
