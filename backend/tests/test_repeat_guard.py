import asyncio

from livekit.agents import llm

from app.agent.repeat_guard import NUDGE, RepeatGuard, no_repeats, said_lines, with_nudge

INTRO = ("Hey Farah, this is Olivia giving you a call over from Compass Multifamily. I know it's a little out of "
         "the blue, but do you have a quick second to talk about the property?")


async def _gen(text: str):
    for i in range(0, len(text), 7):
        yield text[i:i + 7]


def _run(attempts: dict, said: list[str]) -> tuple[str, list]:
    calls, cut = [], []

    def make(nudged: bool):
        calls.append(nudged)
        return _gen(attempts[nudged])

    async def go():
        return "".join([c async for c in no_repeats(make, said, cut.append)])

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


def test_guard_states():
    g = RepeatGuard([INTRO])
    assert g.feed("Hey Farah, this ") == "wait"
    assert g.feed("is Olivia giving you a ") == "repeat"
    assert RepeatGuard([INTRO]).feed("Sure thing ") == "ok"


def test_nudge_goes_into_instructions_and_contact_keeps_last_turn():
    c = llm.ChatContext()
    c.add_message(role="system", content="You are Olivia.")
    c.add_message(role="assistant", content=INTRO)
    c.add_message(role="user", content="Hello? What property?")
    n = with_nudge(c)
    assert NUDGE in n.items[0].text_content and NUDGE not in (c.items[0].text_content or "")
    assert n.items[-1].role == "user"
    assert said_lines(c) == [INTRO]
