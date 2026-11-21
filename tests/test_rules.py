from datetime import date, timedelta
from types import SimpleNamespace as NS

import pytest

from booking import rules
from booking.rules import BookingError

from .conftest import NOW, local


def resource(**kw):
    base = dict(kind="slots", max_days_ahead=14, max_active_bookings=2, max_nights=3, name="Bastu")
    return NS(**{**base, **kw})


def test_overnight_period_is_noon_to_1159():
    p = rules.overnight_period(date(2026, 12, 5), 1)
    assert p.start == local(2026, 12, 5, 12, 0)
    assert p.end == local(2026, 12, 6, 11, 59)


def test_consecutive_nights_do_not_overlap():
    a = rules.overnight_period(date(2026, 12, 5), 1)
    b = rules.overnight_period(date(2026, 12, 6), 1)
    assert not rules.overlaps(a.start, a.end, b.start, b.end)


def test_multi_night_period():
    p = rules.overnight_period(date(2026, 12, 5), 3)
    assert p.end == local(2026, 12, 8, 11, 59)


def test_zero_nights_rejected():
    with pytest.raises(BookingError):
        rules.overnight_period(date(2026, 12, 5), 0)


def test_slots_for_date_uses_weekday():
    templates = [
        NS(weekday=3, start_time=local(2026, 1, 1, 19).time(), end_time=local(2026, 1, 1, 22).time()),
        NS(weekday=4, start_time=local(2026, 1, 1, 7).time(), end_time=local(2026, 1, 1, 10).time()),
    ]
    thursday = date(2026, 12, 3)
    slots = rules.slots_for_date(templates, thursday)
    assert [(s.start.hour, s.end.hour) for s in slots] == [(19, 22)]


def _check(**kw):
    start = kw.pop("start", NOW + timedelta(days=1))
    end = kw.pop("end", start + timedelta(hours=3))
    args = dict(
        resource=kw.pop("resource", resource()),
        start=start,
        end=end,
        now=NOW,
        active_count_for_apartment=0,
        has_overlap=False,
        valid_slots=[rules.Slot(start, end)],
    )
    args.update(kw)
    rules.check_new_booking(**args)


def test_valid_booking_passes():
    _check()


@pytest.mark.parametrize(
    "kwargs,msg",
    [
        ({"start": NOW - timedelta(hours=1)}, "redan har börjat"),
        ({"start": NOW + timedelta(days=15)}, "dagar framåt"),
        ({"valid_slots": []}, "passet finns inte"),
        ({"has_overlap": True}, "redan bokad"),
        ({"active_count_for_apartment": 2}, "max"),
    ],
)
def test_rule_violations(kwargs, msg):
    with pytest.raises(BookingError, match=msg):
        _check(**kwargs)


def test_overnight_must_be_noon_to_1159():
    r = resource(kind="overnight", max_days_ahead=90)
    p = rules.overnight_period(date(2026, 12, 10), 2)
    _check(resource=r, start=p.start, end=p.end)
    with pytest.raises(BookingError, match="12:00"):
        _check(resource=r, start=p.start + timedelta(hours=1), end=p.end)


def test_overnight_max_nights():
    r = resource(kind="overnight", max_days_ahead=90, max_nights=3)
    p = rules.overnight_period(date(2026, 12, 10), 4)
    with pytest.raises(BookingError, match="högst 3 nätter"):
        _check(resource=r, start=p.start, end=p.end)


def test_cancel_deadline():
    rules.check_cancel(booking_start=NOW + timedelta(hours=3), now=NOW, cancel_hours_before=2)
    with pytest.raises(BookingError, match="senast 2 timmar"):
        rules.check_cancel(booking_start=NOW + timedelta(hours=1), now=NOW, cancel_hours_before=2)
    with pytest.raises(BookingError, match="redan börjat"):
        rules.check_cancel(booking_start=NOW - timedelta(minutes=1), now=NOW, cancel_hours_before=2)
