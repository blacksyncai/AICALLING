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


def test_times_are_offered_the_way_people_say_them():
    import datetime as dt
    from app.services.calendar import spoken_offer
    now = dt.datetime(2026, 10, 21, 12, 0, tzinfo=dt.timezone.utc)
    slots = [{"start": "2026-10-22T14:00:00Z"}, {"start": "2026-10-22T15:00:00Z"}, {"start": "2026-10-22T17:00:00Z"},
             {"start": "2026-10-23T18:15:00Z"}]
    assert spoken_offer(slots, "America/New_York", now) == "tomorrow at 10, 11 or 1, or Friday at two fifteen"


def test_pick_slot_understands_tomorrow():
    import datetime as dt
    from app.services.calendar import pick_slot
    tomorrow = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).date().isoformat()
    later = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)).date().isoformat()
    slots = [{"start": f"{tomorrow}T10:00:00+00:00", "label": "a"}, {"start": f"{later}T10:00:00+00:00", "label": "b"}]
    assert pick_slot(slots, "tomorrow at 10", "UTC")["label"] == "a"


def test_josh_rogers_greeting_is_voicemail():
    from app.agent.runtime import personal_greeting_match, voicemail_greeting_match
    heard = ("Feel free to leave a voice mail or send a text as I can read those faster. It's a great life. "
             "Look forward to connecting.")
    assert voicemail_greeting_match(heard)
    assert personal_greeting_match("Hey it's Josh, I'll get back to you, send a text if it's quick.")


def test_live_people_are_not_voicemail():
    from app.agent.runtime import personal_greeting_match, voicemail_greeting_match
    for said in ("Hello?", "Yeah this is Josh, who's calling?", "Can you just send me a text instead?",
                 "I got your voicemail yesterday, what's this about?"):
        assert not voicemail_greeting_match(said) and not personal_greeting_match(said), said
