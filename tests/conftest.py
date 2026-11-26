from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model

from booking.models import Apartment, Member, Resource

TZ = ZoneInfo("Europe/Stockholm")


def local(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


# Fast "nu": en onsdag mitt på dagen.
NOW = local(2026, 12, 2, 12, 0)


@pytest.fixture
def now():
    return NOW


def make_member(apartment_number, email, name="Test", vaka_ref=None):
    apt, _ = Apartment.objects.get_or_create(number=apartment_number)
    user = get_user_model().objects.create_user(username=email, email=email, password="x-Secret-123")
    return Member.objects.create(user=user, apartment=apt, name=name, vaka_user_ref=vaka_ref)


@pytest.fixture
def anna(db):
    return make_member("1001", "anna@example.se", "Anna", "V1")


@pytest.fixture
def bertil(db):
    return make_member("1002", "bertil@example.se", "Bertil", "V2")


@pytest.fixture
def cecilia(db):  # samma lägenhet som Bertil
    return make_member("1002", "cecilia@example.se", "Cecilia", "V3")


@pytest.fixture
def sauna(db):
    return Resource.objects.create(
        name="Bastu", slug="bastu", kind=Resource.Kind.FLEXIBLE, door_ref="DOOR-BASTU",
        open_time=time(7), close_time=time(22),
        min_duration_minutes=60, max_duration_minutes=180, step_minutes=30,
        max_active_bookings=2, max_days_ahead=14, cancel_hours_before=2,
    )


@pytest.fixture
def guestroom(db):
    return Resource.objects.create(
        name="Övernattningsrum", slug="overnattning", kind=Resource.Kind.OVERNIGHT,
        door_ref="DOOR-GAST", max_active_bookings=1, max_days_ahead=90,
        cancel_hours_before=48, max_nights=3, price=200,
    )


def slot(day_offset, hour, length=3):
    start = NOW.replace(hour=hour) + timedelta(days=day_offset)
    return start, start + timedelta(hours=length)
