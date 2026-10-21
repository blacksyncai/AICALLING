import asyncio

from livekit.agents import llm

from app.agent.repeat_guard import NUDGE, RepeatGuard, no_repeats, said_lines, with_nudge

INTRO = ("Hey Farah, this is Olivia giving you a call over from Compass Multifamily. I know it's a little out of "
         "the blue, but do you have a quick second to talk about the property?")


async def _gen(text: str):
    for i in range(0, len(text), 7):
        yield text[i:i + 7]


def _run(attempts: dict, said: list[str], heard: str = "") -> tuple[str, list]:
    calls, cut = [], []

    def make(nudged: bool):
        calls.append(nudged)
        return _gen(attempts[nudged])

    async def go():
        return "".join([c async for c in no_repeats(make, said, cut.append, heard)])

    return asyncio.run(go()), calls, cut


def test_reread_intro_is_dropped_and_retried():
    out, calls, cut = _run({False: '"' + INTRO + '"', True: "The one on Oak Street, the fourplex. Got a sec?"}, [INTRO])
    assert out == "The one on Oak Street, the fourplex. Got a sec?"
    assert calls == [False, True] and cut


def test_new_reply_passes_untouched():
    out, calls, cut = _run({False: "Hey Farah, sorry, the fourplex on Oak Street.", True: "x"}, [INTRO])
    assert out == "Hey Farah, sorry, the fourplex on Oak Street." and calls == [False] and not cut


def test_short_lines_may_repeat():
    out, calls, _ = _run({False: "Hey, is this Sam?", True: "x"}, ["Hey, is this Sam?"])
    assert out == "Hey, is this Sam?" and calls == [False]


def test_guard_judges_sentences():
    g = RepeatGuard([INTRO])
    assert g.repeats("Hey Farah, this is Olivia giving you a call over from Compass Multifamily.")
    assert not g.repeats("Sure thing.")
    assert g.clearly_new("The fourplex on Oak Street that you own ")
    assert not g.clearly_new("Do you have a quick ")


# The call that started this: the agent re-asked its pitch three times in new words.
CALL = ["Hey Thai, this is Zane, calling on behalf of Gabriel Manzanares with Compass Multifamily. Do you have a "
        "quick second to talk about the property over on 27th Street?",
        "I'm reaching out from our Compass Multifamily office. Do you have a quick second to talk about the "
        "property on 27th Street?"]


def test_reworded_repeats_are_dropped_and_new_words_kept():
    out, calls, cut = _run({False: "I'm calling from our Compass Multifamily office. Do you have a quick second to "
                                   "talk about the property on 27th Street?",
                            True: "Compass Multifamily, here in San Francisco. It's about your building on 27th."},
                           CALL)
    assert out == "Compass Multifamily, here in San Francisco. It's about your building on 27th."
    assert calls == [False, True] and cut


def test_only_the_repeated_sentence_is_cut():
    out, calls, _ = _run({False: "Sorry about that, the line was choppy for a second. Do you have a quick second to "
                                 "talk about the property on 27th Street?", True: "x"}, CALL)
    assert out == "Sorry about that, the line was choppy for a second. " and calls == [False]


def test_nudge_goes_into_instructions_and_contact_keeps_last_turn():
    c = llm.ChatContext()
    c.add_message(role="system", content="You are Olivia.")
    c.add_message(role="assistant", content=INTRO)
    c.add_message(role="user", content="Hello? What property?")
    n = with_nudge(c)
    assert NUDGE in n.items[0].text_content and NUDGE not in (c.items[0].text_content or "")
    assert n.items[-1].role == "user"
    assert said_lines(c) == [INTRO]


TIMES = "I have Wednesday, October 21 at 10:00 AM or at 2:15 PM. Which works better for you?"


def test_asked_to_repeat_the_times_says_them_again():
    for ask in ("Say the times again.", "What times again?", "Sorry, I didn't catch that", "What times do you have?"):
        out, calls, cut = _run({False: TIMES, True: "x"}, [TIMES], ask)
        assert out == TIMES and calls == [False] and not cut, ask
