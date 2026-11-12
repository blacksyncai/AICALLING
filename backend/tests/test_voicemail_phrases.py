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


def test_carrier_greeting_that_reads_out_the_number_is_voicemail():
    from app.agent.runtime import number_greeting_match, voicemail_answered, voicemail_greeting_match
    for heard in ("Your message for nine five four five nine four zero seven two nine.",
                  "Five six one two six zero four three six one",
                  "Message for four one five eight six seven five four five eight."):
        assert number_greeting_match(heard), heard
    for live in ("Hello?", "Hola. Gracias.", "Legacy Management Group, this is Kelly.", "My number? Four one five."):
        assert number_greeting_match(live) is None, live
    # Only judged at the start of a call: the always-on strict list doesn't treat a read-out number as voicemail.
    assert voicemail_greeting_match("Sure, call me back at four one five five five five zero one zero one") is None
    call = [{"role": "assistant", "text": "Hey, this is Ava with William Raveis. Is this Chun?"},
            {"role": "user", "text": "Five six one two six zero four three six one"},
            {"role": "assistant", "text": "Got it. Is this Chun?"}]
    assert voicemail_answered(call)


def test_text_me_greeting_is_voicemail_not_a_callback():
    from app.agent.runtime import reconcile_outcome, voicemail_answered

    transcript = [
        {"role": "assistant", "text": "Hey Nicole this is Sofia. Real quick I'm a next gen AI agent. I know"},
        {"role": "user", "text": "For a quicker response, text me. Looking forward to connecting soon. Have a great day."},
        {"role": "tool", "tool": "end_call", "args": {"outcome": "callback"}},
    ]
    assert voicemail_answered(transcript)
    assert reconcile_outcome("callback", transcript, callback_request="For a quicker response, text me.") == "voicemail"


def test_a_live_person_saying_have_a_great_day_is_still_a_person():
    from app.agent.runtime import person_answered

    transcript = [
        {"role": "assistant", "text": "Hey Nicole this is Sofia, is now an okay time?"},
        {"role": "user", "text": "Hello? Who is this?"},
        {"role": "assistant", "text": "It's Sofia with Acme about your listing."},
        {"role": "user", "text": "Not interested, have a great day."},
    ]
    assert person_answered(transcript)


def test_greeting_tail_return_your_call_is_voicemail():
    from app.agent.runtime import reconcile_outcome, voicemail_answered

    transcript = [
        {"role": "assistant", "text": "Hey Kelly this is Sofia. Real quick I'm a next gen AI agent."},
        {"role": "user", "text": "Message, and I will return your call. Thank you."},
    ]
    assert voicemail_answered(transcript)
    assert reconcile_outcome("no_decision", transcript) == "voicemail"
    assert reconcile_outcome("callback", transcript, callback_request="Message, and I will return your call.") == "voicemail"


def test_a_live_person_saying_they_will_call_back_is_still_a_person():
    from app.agent.runtime import person_answered

    transcript = [
        {"role": "assistant", "text": "Hey Kelly, this is Sofia, do you have a minute?"},
        {"role": "user", "text": "Hello? Who is this?"},
        {"role": "assistant", "text": "It's Sofia with Acme about your listing."},
        {"role": "user", "text": "I'm driving, I will return your call later."},
    ]
    assert person_answered(transcript)


def test_recordings_without_a_stock_phrase():
    """A number read out plus "not available", "<name> is not available" at pickup, and a long speech at pickup
    are recordings; the same words from a person replying to our agent are not."""
    from app.agent.runtime import opening_machine_match as m, reconcile_outcome as r

    def T(*turns):
        return [{"role": a, "text": b} for a, b in turns]

    assert m("7 3 4 5 5 5 0 1 2 3 isn't available", first_words=11) == "number unavailable"
    assert m("Seven three four is not available right now", first_words=8) == "number unavailable"
    assert m("John Smith is not available", first_words=5) == "unavailable at pickup"
    assert m("Hello?", first_words=1) is None and m("He's not available", first_words=3) is None
    assert m("John is not available", first_words=4, opening=False) is None
    speech = ("Hi this is Dana with Coastal Dental our office is closed for the day we are open Monday through "
              "Friday nine to five and will respond then")
    assert m(speech, first_words=27) == "monologue at pickup"
    assert m(speech + " can you hold?", first_words=27) is None  # a question means a person

    assert r("completed", T(("user", "7 3 4 isn't available"), ("assistant", "Hey Sam, this is Sofia."))) == "voicemail"
    assert r("completed", T(("user", speech), ("assistant", "Hey, this is Sofia."))) == "voicemail"
    # A person who said hello, then gave a long answer or said someone isn't available, stays a conversation.
    long_answer = ("Yeah I am still looking I want three bedrooms and three bathrooms and about twenty six hundred "
                   "square feet somewhere in the bay area near good schools")
    assert r("interested", T(("user", "Hello?"), ("assistant", "Are you still looking?"), ("user", long_answer))) == "interested"
    assert r("completed", T(("user", "Hello"), ("assistant", "Is this John?"),
                            ("user", "John is not available right now"))) == "completed"


# Real recordings our agents talked to as if they were people (Nov 2026 call logs).
MISSED_RECORDINGS = [
    "If you're satisfied with the message, press one. To listen to your message, press two. To erase and rerecord, press three.",
    "When you are finished recording, you may hang up or press pound for more options.",
    "Your call has been forwarded to an automatic voice message system. Sorry. The mailbox belonging to four one five "
    "two three nine two five four one is full and will not receive your message. Please hang up.",
    "Please leave me your important message.",
    "To continue your call in English, please press one now.",
    "Like to leave a",
    "whave finage recording y me hang up.",
    "The person you're calling is busy now. I'll let them know you called. Thank you.",
    "The Roan Sisters. If this is a repair or maintenance issue, please call or text Theo at five one zero two three "
    "zero seven zero six two. Messages left here will be checked periodically. Thanks.",
    "The number you have dialed is not configured correctly and cannot receive calls.",
    "We're currently close right now. Please give us a callback during normal business hours.",
    "Your call cannot be completed at this time. Please try again later.",
]


def test_obvious_recordings_are_caught():
    from app.agent.runtime import voicemail_answered, voicemail_greeting_match

    for text in MISSED_RECORDINGS:
        assert voicemail_greeting_match(text), text
        assert voicemail_answered([{"role": "assistant", "text": "Hi, is this Pat?"}, {"role": "user", "text": text}]), text


def test_tail_of_voicemail_for_name_at_pickup():
    from app.agent.runtime import number_greeting_match

    assert number_greeting_match("Four Caroline Dixon.")
    assert number_greeting_match("Four. Tina Tindle.")
    assert not number_greeting_match("For sure, go ahead.")  # three words, but a live reply
    assert not number_greeting_match("For what property?")


def test_live_people_are_not_recordings():
    from app.agent.runtime import voicemail_greeting_match

    for text in ("Hello? Who's this?", "Yeah, I'm closed on Sundays but go ahead.", "Which number did you dial?",
                 "I'd rather you text me the details.", "Press me on price and I'll tell you.",
                 "Sorry, can you call me back in an hour?", "The office is open, what's this about?"):
        assert voicemail_greeting_match(text) is None, text
