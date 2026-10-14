from datetime import datetime, timezone

from app.services.quiet_hours import ok_to_call, zones_for


def test_contacts_are_only_rung_8am_to_9pm_their_time():
    at_noon_utc = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)  # 8 AM New York, 5 AM Los Angeles
    assert ok_to_call("+12125550123", at_noon_utc)          # New York: 8 AM
    assert not ok_to_call("+14155550123", at_noon_utc)      # San Francisco: 5 AM
    late = datetime(2026, 3, 11, 2, 30, tzinfo=timezone.utc)  # 10:30 PM New York, 7:30 PM LA
    assert not ok_to_call("+13055550123", late)
    assert ok_to_call("+16195550123", late)


def test_unknown_or_toll_free_numbers_fall_back_to_the_campaign_hours():
    night = datetime(2026, 3, 11, 8, 0, tzinfo=timezone.utc)
    assert zones_for("+18005550123") == () and ok_to_call("+18005550123", night)
    assert ok_to_call("not a number", night)


def test_slot_choice_uses_the_calendar_timezone_and_the_latest_offer():
    from app.services.calendar import pick_slot

    early = [{"start": "2026-03-12T13:00:00Z", "label": "Thursday, March 12 at 9:00 AM"},
             {"start": "2026-03-12T18:00:00Z", "label": "Thursday, March 12 at 2:00 PM"}]
    later = [{"start": "2026-03-13T15:00:00Z", "label": "Friday, March 13 at 11:00 AM"},
             {"start": "2026-03-13T20:00:00Z", "label": "Friday, March 13 at 4:00 PM"}]
    every = early + later
    # 9 AM New York is 13:00 UTC — the contact means the local hour.
    assert pick_slot(every, "thursday at 9", "America/New_York") == early[0]
    # "The first one" after a second round of options is the first of that round.
    assert pick_slot(every, "first", "America/New_York", later) == later[0]


def test_us_number_typed_with_plus_but_no_1_dials_the_us():
    from app.services.outbound_call import validate_e164

    assert validate_e164("+4157075948") == "+14157075948"   # not Switzerland
    assert validate_e164("+442071838750") == "+442071838750"  # a real UK number stays as typed
