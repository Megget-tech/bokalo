from datetime import date, time, timedelta
from types import SimpleNamespace as NS

import pytest

from booking import rules
from booking.rules import BookingError

from .conftest import NOW, local

DAY = date(2026, 12, 3)


def sauna(**kw):
    base = dict(
        kind="flexible", name="Bastu", open_time=time(7), close_time=time(22),
        min_duration_minutes=60, max_duration_minutes=180, step_minutes=30,
        max_days_ahead=14, max_active_bookings=2, max_nights=3,
    )
    return NS(**{**base, **kw})


def busy(*pairs):
    return [NS(start=local(2026, 12, 3, *a), end=local(2026, 12, 3, *b)) for a, b in pairs]


# --- Flexibel tid -------------------------------------------------------------


def test_start_times_on_grid_within_opening_hours():
    starts = rules.flexible_start_times(sauna(), DAY, [], earliest=NOW)
    assert starts[0] == local(2026, 12, 3, 7, 0)
    assert starts[1] == local(2026, 12, 3, 7, 30)
    assert starts[-1] == local(2026, 12, 3, 21, 0)  # 21:00 + 1 h = stängning


def test_start_times_skip_busy_and_too_short_gaps():
    # Bokat 10:00–12:00 och 13:30–15:00: 12:30 ger bara 1 h fram till 13:30 => ok,
    # 13:00 ger bara 30 min => inte ok.
    starts = rules.flexible_start_times(sauna(), DAY, busy(((10,), (12,)), ((13, 30), (15,))), earliest=NOW)
    hhmm = [f"{s:%H:%M}" for s in starts]
    assert "09:00" in hhmm and "09:30" not in hhmm
    assert "12:00" in hhmm and "12:30" in hhmm and "13:00" not in hhmm
    assert "15:00" in hhmm


def test_start_times_respect_earliest():
    starts = rules.flexible_start_times(sauna(), DAY, [], earliest=local(2026, 12, 3, 18, 10))
    assert [f"{s:%H:%M}" for s in starts] == ["18:30", "19:00", "19:30", "20:00", "20:30", "21:00"]


def test_durations_stop_at_next_booking_and_closing():
    r = sauna()
    assert rules.flexible_durations(r, local(2026, 12, 3, 8), busy(((10,), (12,)))) == [60, 90, 120]
    assert rules.flexible_durations(r, local(2026, 12, 3, 20), []) == [60, 90, 120]
    assert rules.flexible_durations(r, local(2026, 12, 3, 12), []) == [60, 90, 120, 150, 180]


def test_format_minutes():
    assert rules.format_minutes(60) == "1 h"
    assert rules.format_minutes(90) == "1 h 30 min"
    assert rules.format_minutes(45) == "45 min"


# --- Övernattning ---------------------------------------------------------------


def test_overnight_period_is_noon_to_1159():
    p = rules.overnight_period(date(2026, 12, 5), 1)
    assert p.start == local(2026, 12, 5, 12, 0)
    assert p.end == local(2026, 12, 6, 11, 59)


def test_consecutive_nights_do_not_overlap():
    a = rules.overnight_period(date(2026, 12, 5), 1)
    b = rules.overnight_period(date(2026, 12, 6), 1)
    assert not rules.overlaps(a.start, a.end, b.start, b.end)


def test_possible_nights_stops_at_next_guest():
    r = sauna(kind="overnight", max_nights=4)
    taken = [NS(**rules.overnight_period(date(2026, 12, 8), 1).__dict__)]
    assert rules.possible_nights(r, date(2026, 12, 5), taken) == [1, 2, 3]
    assert rules.possible_nights(r, date(2026, 12, 9), taken) == [1, 2, 3, 4]
    assert rules.possible_nights(r, date(2026, 12, 8), taken) == []


def test_zero_nights_rejected():
    with pytest.raises(BookingError):
        rules.overnight_period(date(2026, 12, 5), 0)


# --- check_new_booking ----------------------------------------------------------


def _check(**kw):
    start = kw.pop("start", local(2026, 12, 3, 19))
    end = kw.pop("end", start + timedelta(hours=2))
    args = dict(resource=kw.pop("resource", sauna()), start=start, end=end, now=NOW,
                active_count_for_apartment=0, has_overlap=False)
    args.update(kw)
    rules.check_new_booking(**args)


def test_valid_booking_passes():
    _check()


@pytest.mark.parametrize(
    "kwargs,msg",
    [
        ({"start": NOW - timedelta(hours=1)}, "redan har börjat"),
        ({"start": local(2026, 12, 20, 19)}, "dagar framåt"),
        ({"has_overlap": True}, "redan bokad"),
        ({"active_count_for_apartment": 2}, "max"),
        ({"start": local(2026, 12, 2, 12, 30), "min_notice_minutes": 75}, "senast 1 h 15 min före start"),
        ({"start": local(2026, 12, 3, 19, 10)}, "steg om 30"),
    ],
)
def test_rule_violations(kwargs, msg):
    with pytest.raises(BookingError, match=msg):
        _check(**kwargs)


def test_min_notice_ok_when_early_enough():
    _check(start=local(2026, 12, 2, 13, 30), min_notice_minutes=75)


def test_overnight_must_be_noon_to_1159():
    r = sauna(kind="overnight", max_days_ahead=90)
    p = rules.overnight_period(date(2026, 12, 10), 2)
    _check(resource=r, start=p.start, end=p.end)
    with pytest.raises(BookingError, match="12:00"):
        _check(resource=r, start=p.start + timedelta(hours=1), end=p.end)


def test_overnight_max_nights():
    r = sauna(kind="overnight", max_days_ahead=90, max_nights=3)
    p = rules.overnight_period(date(2026, 12, 10), 4)
    with pytest.raises(BookingError, match="högst 3 dygn"):
        _check(resource=r, start=p.start, end=p.end)


def test_cancel_deadline():
    rules.check_cancel(booking_start=NOW + timedelta(hours=3), now=NOW, cancel_hours_before=2)
    with pytest.raises(BookingError, match="senast 2 timmar"):
        rules.check_cancel(booking_start=NOW + timedelta(hours=1), now=NOW, cancel_hours_before=2)
    with pytest.raises(BookingError, match="redan börjat"):
        rules.check_cancel(booking_start=NOW - timedelta(minutes=1), now=NOW, cancel_hours_before=2)
