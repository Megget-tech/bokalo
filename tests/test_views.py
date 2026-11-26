import re
from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from booking.models import Booking
from booking.rules import local_tz


@pytest.fixture
def client_anna(client, anna):
    client.force_login(anna.user)
    return client


def tomorrow_at(hour=19):
    from datetime import datetime, time
    day = timezone.localdate() + timedelta(days=1)
    return datetime.combine(day, time(hour), local_tz())


def post_flexible(client, start, minutes=120):
    return client.post(
        reverse("booking:book", args=["bastu"]),
        {"date": start.date().isoformat(), "start": f"{start:%H:%M}", "duration": str(minutes)},
    )


def test_login_required(client, db):
    r = client.get(reverse("booking:home"))
    assert r.status_code == 302 and "/konto/login/" in r["Location"]


def test_user_without_member_gets_403(client, django_user_model):
    u = django_user_model.objects.create_user(username="x@example.se", email="x@example.se")
    client.force_login(u)
    assert client.get(reverse("booking:home")).status_code == 403


def test_signup_closed(client, db):
    r = client.post(reverse("account_signup"), {"email": "new@example.se", "password1": "Abc-12345678"})
    assert r.status_code in (200, 302)
    from django.contrib.auth import get_user_model
    assert not get_user_model().objects.filter(email="new@example.se").exists()


def test_month_calendar_then_times_then_durations(client_anna, sauna):
    start = tomorrow_at(19)
    url = reverse("booking:resource", args=["bastu"])
    page = client_anna.get(url).content.decode()
    assert 'class="cal-grid"' in page and "Välj starttid" not in page  # bara kalendern först

    page = client_anna.get(url, {"datum": start.date().isoformat()}).content.decode()
    assert "Välj starttid" in page and ">19:00<" in page and "Välj hur länge" not in page

    page = client_anna.get(url, {"datum": start.date().isoformat(), "start": "19:00"}).content.decode()
    assert "Välj hur länge" in page
    assert ">1 h<" in page and ">3 h<" in page and "till 22:00" in page


def test_book_and_cancel_flexible(client_anna, sauna):
    start = tomorrow_at(19)
    r = post_flexible(client_anna, start, 90)
    assert r.status_code == 302
    b = Booking.objects.get()
    assert (b.start, b.duration_minutes) == (start, 90)

    home = client_anna.get(reverse("booking:home")).content.decode()
    assert "Bastu" in home

    client_anna.post(reverse("booking:cancel", args=[b.pk]))
    b.refresh_from_db()
    assert b.status == Booking.Status.CANCELLED


def test_book_overnight(client_anna, guestroom):
    arrival = timezone.localdate() + timedelta(days=5)
    client_anna.post(reverse("booking:book", args=["overnattning"]), {"date": arrival.isoformat(), "nights": "2"})
    b = Booking.objects.get()
    assert b.nights == 2


def test_cannot_cancel_other_apartments_booking(client, bertil, anna, sauna):
    from booking import services
    s = tomorrow_at(19)
    b = services.create_flexible_booking(member=bertil, resource=sauna, start=s, duration_minutes=60)
    client.force_login(anna.user)
    assert client.post(reverse("booking:cancel", args=[b.pk])).status_code == 404


def test_other_apartment_booking_hides_times_and_name(client_anna, bertil, sauna):
    from booking import services
    s = tomorrow_at(19)
    services.create_flexible_booking(member=bertil, resource=sauna, start=s, duration_minutes=180)
    html = client_anna.get(reverse("booking:resource", args=["bastu"]), {"datum": s.date().isoformat()}).content.decode()
    assert ">18:00<" in html and ">19:00<" not in html and ">21:00<" not in html
    assert "Bertil" not in html
    assert 'cal-day partial' in html


def test_login_by_email_code(client, anna):
    r = client.post(reverse("account_request_login_code"), {"email": "anna@example.se"})
    assert r.status_code == 302
    assert len(mail.outbox) == 1
    code = re.search(r"^\s*([A-Z0-9][A-Z0-9-]{4,}[A-Z0-9])\s*$", mail.outbox[0].body, re.M).group(1)
    r = client.post(reverse("account_confirm_login_code"), {"code": code})
    assert r.status_code == 302
    assert client.get(reverse("booking:home")).status_code == 200


def test_staff_without_member_gets_link_to_create_member(client, django_user_model):
    u = django_user_model.objects.create_user(username="admin", email="a@example.se", is_staff=True)
    client.force_login(u)
    html = client.get(reverse("booking:home")).content.decode()
    assert f"/admin/booking/member/add/?user={u.pk}" in html
