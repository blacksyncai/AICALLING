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


def test_voicemail_greeting_is_kept_for_radar():
    from app.agent.runtime import person_answered, voicemail_greeting_turn
    from app.services.crm.verification import classify

    heard = "  Hi, you've reached Robert   Chen. Please leave a message after the tone. "
    transcript = [{"role": "assistant", "text": "Hey, is this Robert?"},
                  {"role": "tool", "tool": "voicemail", "args": {"action": "hung_up"}}]
    turn = voicemail_greeting_turn(transcript, heard)
    assert turn == {"role": "user", "text": "Hi, you've reached Robert Chen. Please leave a message after the tone.",
                    "voicemail_greeting": True}
    transcript.append(turn)
    assert classify(transcript, "Robert Chen", "voicemail")["status"] == "named_voicemail"
    assert not person_answered(transcript)  # still a voicemail, never a conversation
    # Nothing heard, or already on the record: nothing added.
    assert voicemail_greeting_turn(transcript, "") is None
    assert voicemail_greeting_turn(transcript, heard) is None


def test_call_screener_giving_up_is_voicemail():
    from app.agent.runtime import is_screener_hold, voicemail_greeting_match

    for text in ("I'm sorry. This person is not available. If you would like to leave an additional message, "
                 "please reply after the tone.",
                 "I'm sorry. This person is not available. If you would like to leave an additional message,"):
        assert voicemail_greeting_match(text) and not is_screener_hold(text)
    # A live person saying someone isn't around is not a machine.
    assert voicemail_greeting_match("He's not available right now, who's calling?") is None
