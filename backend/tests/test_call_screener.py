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


def test_screener_lines_are_not_a_person_answering():
    from app.agent.runtime import person_answered, reconcile_outcome

    screened = [{"role": "user", "text": "Hi, the person you're calling is using a screening service from Google. "
                                         "Go ahead and say your name and why you're calling."},
                {"role": "assistant", "text": "Hey Mark, it's just..."},
                {"role": "user", "text": "Please stay on the line."}]
    assert not person_answered(screened)
    assert reconcile_outcome("screened", screened) == "screened"
    picked_up = screened + [{"role": "user", "text": "Hello? Who is this?"}]
    assert person_answered(picked_up)
    assert reconcile_outcome("screened", picked_up) == "completed"


def test_screened_is_a_retryable_outcome_billed_like_a_call():
    from app.models.call_log import CALL_OUTCOMES
    from app.routers.campaigns import RETRY_STATUSES

    assert "screened" in CALL_OUTCOMES and "screened" in RETRY_STATUSES


def test_language_barrier_and_hung_up_are_outcomes():
    from app.models.call_log import CALL_OUTCOMES
    from app.agent.runtime import _tools_block

    assert {"language_barrier", "hung_up"} <= set(CALL_OUTCOMES)
    assert "language_barrier, not not_interested" in _tools_block({}, "phone")


def test_screener_that_just_holds_is_recognised():
    from app.agent.runtime import conversation_rules, is_screener_hold, screener_hold_start

    assert screener_hold_start("Thanks, Kathleen. Please stay on the line.") == "please stay on the line"
    assert is_screener_hold("Thanks, Kathleen. Please stay on the line.")
    assert not screener_hold_start("This is Kathleen.") and not is_screener_hold("This is Kathleen.")
    assert "Call screeners" in conversation_rules({})
