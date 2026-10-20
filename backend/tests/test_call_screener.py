from app.agent.runtime import is_screener_hold, is_voicemail_greeting, screener_match


def test_screeners_are_recognized():
    assert screener_match("Hi, if you record your name and reason for calling, I'll see if this person is available.")
    assert screener_match("Hi, the person you're calling is using a screening service from Google. Go ahead and "
                          "say your name and why you're calling.")
    assert not screener_match("Hello? Who is this?")


def test_screener_is_not_taken_for_voicemail():
    assert not is_voicemail_greeting("Hi, if you record your name and reason for calling, I'll see if this person "
                                     "is available.")


def test_holding_lines_vs_a_person():
    assert is_screener_hold("Thanks, please stay on the line.")
    assert is_screener_hold("One moment while I see if they're available.")
    assert not is_screener_hold("Hello?")
    assert not is_screener_hold("Yeah, this is Thai, who's this?")
    assert not is_screener_hold("Hi, sorry, one moment, who is this?")
