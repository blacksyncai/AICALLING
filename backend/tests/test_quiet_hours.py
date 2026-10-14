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
