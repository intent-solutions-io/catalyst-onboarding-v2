"""Business-day arithmetic for the follow-up cadence (parity inventory 034 rows 20, 21 and 34; bead bgl.7).

Monday to Friday by the UTC calendar date, no holiday calendar: the first-generation service counted this way, and the
cadence must match it so the swap is invisible. Subject-generic and leaf: it imports no domain app, so correspondence
(the clarification reminder and the lapse) and agreements (the signing reminder) both use it.

- `business_days_between(start, end)`: whole business days after `start`'s date up to and including `end`'s date, so a
  Friday-evening send and a Saturday send both reach one business day on Monday.
- `after(start, days)`: the first instant at which `days` business days have passed since `start`: midnight UTC at the
  start of that day. A follow-up due then is checked against quiet hours by its own handler.
- `db_now()`: the database clock (the transaction's `now()`), so a due time is never computed from an application clock.
"""

from datetime import UTC, date, datetime, time, timedelta

from django.db import connection

SATURDAY = 5  # weekday() of Saturday; Monday is 0


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("business-day arithmetic needs an aware datetime")
    return value.astimezone(UTC)


def is_business_day(day: date) -> bool:
    return day.weekday() < SATURDAY


def business_days_between(start: datetime, end: datetime) -> int:
    """Whole Monday-to-Friday days after `start`'s UTC date up to and including `end`'s UTC date; 0 when `end` is not
    after `start`'s date."""
    day, last = _utc(start).date(), _utc(end).date()
    count = 0
    while day < last:
        day += timedelta(days=1)
        count += is_business_day(day)
    return count


def after(start: datetime, days: int) -> datetime:
    """Midnight UTC of the day on which `days` business days have passed since `start`; `start` itself for 0."""
    if days < 0:
        raise ValueError("business days cannot be negative")
    if days == 0:
        return _utc(start)
    day, passed = _utc(start).date(), 0
    while passed < days:
        day += timedelta(days=1)
        passed += is_business_day(day)
    return datetime.combine(day, time.min, tzinfo=UTC)


def db_now() -> datetime:
    with connection.cursor() as cursor:
        cursor.execute("SELECT now()")
        return cursor.fetchone()[0]
