"""Bead catalyst-v2-bgl.7 (parity inventory 034 rows 20, 21 and 34): the business-day arithmetic every follow-up
cadence counts with. Pure functions, no database."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from workflow import business_days

FRIDAY_EVENING = datetime(2026, 10, 30, 22, 15, tzinfo=UTC)  # 2026-10-30 is a Friday
SATURDAY = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
SUNDAY = datetime(2026, 11, 1, 23, 59, 59, tzinfo=UTC)
MONDAY = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)


def test_bgl7_only_monday_to_friday_count_and_the_start_day_itself_never_does():
    assert business_days.business_days_between(FRIDAY_EVENING, FRIDAY_EVENING) == 0
    assert business_days.business_days_between(FRIDAY_EVENING, SATURDAY) == 0
    assert business_days.business_days_between(FRIDAY_EVENING, SUNDAY) == 0
    assert business_days.business_days_between(FRIDAY_EVENING, MONDAY) == 1  # midnight Monday: the first business day
    assert business_days.business_days_between(SATURDAY, MONDAY) == 1
    assert business_days.business_days_between(SUNDAY, MONDAY) == 1
    assert business_days.business_days_between(MONDAY, MONDAY + timedelta(days=4, hours=23)) == 4  # Tuesday to Friday
    assert business_days.business_days_between(MONDAY, MONDAY + timedelta(days=7)) == 5  # the next Monday
    assert business_days.business_days_between(MONDAY, FRIDAY_EVENING) == 0  # end before start: never negative


@pytest.mark.parametrize(("start", "days", "expected"), [
    (FRIDAY_EVENING, 1, MONDAY),  # a Friday-evening send: one business day on Monday, not Saturday
    (FRIDAY_EVENING, 5, datetime(2026, 11, 6, tzinfo=UTC)),  # the next Friday
    (SATURDAY, 5, datetime(2026, 11, 6, tzinfo=UTC)),  # a weekend send counts from Monday as well
    (SUNDAY, 5, datetime(2026, 11, 6, tzinfo=UTC)),
    (MONDAY, 5, datetime(2026, 11, 9, tzinfo=UTC)),  # a Monday send: the following Monday
    (MONDAY, 10, datetime(2026, 11, 16, tzinfo=UTC)),  # the lapse's ten
    (datetime(2026, 11, 26, 12, 0, tzinfo=UTC), 5, datetime(2026, 12, 3, tzinfo=UTC)),  # across a month boundary (Thursday)
    (datetime(2026, 12, 31, 18, 0, tzinfo=UTC), 1, datetime(2027, 1, 1, tzinfo=UTC)),  # a year boundary; no holidays
    (datetime(2028, 2, 25, 8, 0, tzinfo=UTC), 3, datetime(2028, 3, 1, tzinfo=UTC)),  # across a leap day (29 Feb 2028, Tuesday)
])
def test_bgl7_after_is_midnight_utc_of_the_day_the_business_days_have_passed(start, days, expected):
    due = business_days.after(start, days)
    assert due == expected and due.tzinfo is UTC and due.time().isoformat() == "00:00:00"
    # The two functions agree: the due instant is the first at which the count is reached.
    assert business_days.business_days_between(start, due) == days
    assert business_days.business_days_between(start, due - timedelta(seconds=1)) == days - 1


def test_bgl7_zero_days_is_the_start_itself_and_negative_or_naive_input_is_refused():
    assert business_days.after(FRIDAY_EVENING, 0) == FRIDAY_EVENING
    with pytest.raises(ValueError):
        business_days.after(FRIDAY_EVENING, -1)
    with pytest.raises(ValueError):
        business_days.after(datetime(2026, 10, 30, 22, 15), 1)
    with pytest.raises(ValueError):
        business_days.business_days_between(datetime(2026, 10, 30), FRIDAY_EVENING)


def test_bgl7_another_zone_is_read_by_its_utc_date():
    # 23:30 on Friday in UTC-5 is 04:30 Saturday UTC: the UTC calendar decides, so Monday is still the first day.
    local = datetime(2026, 10, 30, 23, 30, tzinfo=timezone(timedelta(hours=-5)))
    assert local.astimezone(UTC).date().isoformat() == "2026-10-31"
    assert business_days.after(local, 1) == MONDAY
    assert business_days.business_days_between(local, MONDAY) == 1
