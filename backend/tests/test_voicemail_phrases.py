from app.agent.runtime import is_voicemail_greeting, looks_like_personal_greeting


def test_name_and_number_greetings_are_voicemail():
    assert is_voicemail_greeting("Please leave your name, number, and a brief message,")
    assert is_voicemail_greeting("leave me your name and number and I'll call back")
    # Pieces of a personal greeting add up once they're heard together.
    assert looks_like_personal_greeting("Hi. Reached Valerie. Please leave your name and I'll get back to you as soon as possible.")


def test_live_answers_are_not_voicemail():
    for t in ("Hello?", "Yeah this is Valerie, who's calling?", "My name is Bob, what's this about?"):
        assert not is_voicemail_greeting(t)


def test_live_people_are_not_voicemail():
    from app.agent.runtime import is_voicemail_greeting, looks_like_personal_greeting

    assert not is_voicemail_greeting("Yeah I got your voicemail earlier, what's up")
    assert is_voicemail_greeting("The voice mailbox is full")
    # A busy live person — one weak phrase, or asking a question — isn't a recording.
    assert not looks_like_personal_greeting("Hey I can't talk right now I'm driving, sorry about that")
    assert not looks_like_personal_greeting("I can't talk right now, can you just text me instead?")
    assert looks_like_personal_greeting("Hey, you've reached Sam, I'll get back to you as soon as I can")
    assert looks_like_personal_greeting("Hey it's Sam, can't talk right now, text me and I'll call you back")


def test_premature_hangup_is_held():
    from app.agent.runtime import should_hold_hangup

    assert should_hold_hangup("interested", "Yeah that actually sounds interesting, tell me more")
    assert should_hold_hangup("completed", "Okay so how much does it cost?")
    assert not should_hold_hangup("interested", "Okay thanks, bye")
    assert not should_hold_hangup("not_interested", "Yeah I'm interested")  # final outcomes always go through
    assert not should_hold_hangup("completed", "")
    assert not should_hold_hangup("qualified", "Alright, sounds good, talk soon")
