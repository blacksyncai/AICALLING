from app.agent.runtime import is_voicemail_greeting, looks_like_personal_greeting


def test_name_and_number_greetings_are_voicemail():
    assert is_voicemail_greeting("Please leave your name, number, and a brief message,")
    assert is_voicemail_greeting("leave me your name and number and I'll call back")
    # Pieces of a personal greeting add up once they're heard together.
    assert looks_like_personal_greeting("Hi. Reached Valerie. Please leave your name and I'll get back to you as soon as possible.")


def test_live_answers_are_not_voicemail():
    for t in ("Hello?", "Yeah this is Valerie, who's calling?", "My name is Bob, what's this about?"):
        assert not is_voicemail_greeting(t)
