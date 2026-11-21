from datetime import date, timedelta

import pytest

from booking import services
from booking.models import Booking
from booking.rules import BookingError

from .conftest import NOW, slot


def test_book_slot(anna, sauna):
    start, end = slot(1, 19)
    b = services.create_booking(member=anna, resource=sauna, start=start, end=end, now=NOW)
    assert b.status == Booking.Status.ACTIVE
    assert b.apartment == anna.apartment


def test_double_booking_rejected(anna, bertil, sauna):
    start, end = slot(1, 19)
    services.create_booking(member=anna, resource=sauna, start=start, end=end, now=NOW)
    with pytest.raises(BookingError, match="redan bokad"):
        services.create_booking(member=bertil, resource=sauna, start=start, end=end, now=NOW)


def test_cancelled_slot_can_be_rebooked(anna, bertil, sauna):
    start, end = slot(1, 19)
    b = services.create_booking(member=anna, resource=sauna, start=start, end=end, now=NOW)
    services.cancel_booking(b, by_member=anna, now=NOW)
    services.create_booking(member=bertil, resource=sauna, start=start, end=end, now=NOW)


def test_non_template_slot_rejected(anna, sauna):
    start, end = slot(1, 15)
    with pytest.raises(BookingError, match="passet finns inte"):
        services.create_booking(member=anna, resource=sauna, start=start, end=end, now=NOW)


def test_max_active_counts_per_apartment(bertil, cecilia, sauna):
    for day in (1, 2):
        s, e = slot(day, 19)
        services.create_booking(member=bertil, resource=sauna, start=s, end=e, now=NOW)
    s, e = slot(3, 19)
    with pytest.raises(BookingError, match="max"):
        services.create_booking(member=cecilia, resource=sauna, start=s, end=e, now=NOW)


def test_past_bookings_do_not_count_towards_max(bertil, sauna):
    for day in (1, 2):
        s, e = slot(day, 19)
        services.create_booking(member=bertil, resource=sauna, start=s, end=e, now=NOW)
    later = NOW + timedelta(days=3)
    s, e = slot(4, 19)
    services.create_booking(member=bertil, resource=sauna, start=s, end=e, now=later)


def test_overnight_back_to_back(anna, bertil, guestroom):
    services.create_overnight_booking(member=anna, resource=guestroom, arrival=date(2026, 12, 10), nights=2, now=NOW)
    # Nästa ankomst samma dag som Anna checkar ut (11:59) går bra.
    services.create_overnight_booking(member=bertil, resource=guestroom, arrival=date(2026, 12, 12), nights=1, now=NOW)
    with pytest.raises(BookingError, match="redan bokad"):
        services.create_overnight_booking(member=bertil, resource=guestroom, arrival=date(2026, 12, 11), nights=1, now=NOW)


def test_member_cannot_cancel_other_apartment(anna, bertil, sauna):
    s, e = slot(1, 19)
    b = services.create_booking(member=anna, resource=sauna, start=s, end=e, now=NOW)
    with pytest.raises(BookingError, match="din lägenhets"):
        services.cancel_booking(b, by_member=bertil, now=NOW)


def test_same_apartment_can_cancel(bertil, cecilia, sauna):
    s, e = slot(1, 19)
    b = services.create_booking(member=bertil, resource=sauna, start=s, end=e, now=NOW)
    services.cancel_booking(b, by_member=cecilia, now=NOW)
    b.refresh_from_db()
    assert b.status == Booking.Status.CANCELLED


def test_board_can_cancel_after_deadline(anna, sauna):
    s, e = slot(1, 19)
    b = services.create_booking(member=anna, resource=sauna, start=s, end=e, now=NOW)
    services.cancel_booking(b, now=s - timedelta(minutes=30))
    b.refresh_from_db()
    assert b.status == Booking.Status.CANCELLED


def test_inactive_member_cannot_book(anna, sauna):
    anna.active = False
    anna.save()
    s, e = slot(1, 19)
    with pytest.raises(BookingError, match="inte aktivt"):
        services.create_booking(member=anna, resource=sauna, start=s, end=e, now=NOW)


def test_release_expired_holds(anna, sauna):
    s, e = slot(1, 19)
    b = Booking.objects.create(
        resource=sauna, member=anna, apartment=anna.apartment, start=s, end=e,
        status=Booking.Status.PENDING_PAYMENT, hold_expires_at=NOW + timedelta(minutes=15),
    )
    assert services.release_expired_holds(now=NOW) == 0
    assert services.release_expired_holds(now=NOW + timedelta(minutes=16)) == 1
    b.refresh_from_db()
    assert b.status == Booking.Status.CANCELLED
