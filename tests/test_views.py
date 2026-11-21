import re
from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from booking.models import Booking
from booking.rules import slots_for_date


@pytest.fixture
def client_anna(client, anna):
    client.force_login(anna.user)
    return client


def next_free_slot(resource):
    day = timezone.localdate() + timedelta(days=1)
    return slots_for_date(resource.slot_templates.all(), day)[0]


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


def test_book_and_cancel_slot(client_anna, sauna):
    s = next_free_slot(sauna)
    page = client_anna.get(reverse("booking:resource", args=["bastu"]))
    assert page.status_code == 200 and "Boka" in page.content.decode()

    r = client_anna.post(reverse("booking:book", args=["bastu"]), {"start": s.start.isoformat()})
    assert r.status_code == 302
    b = Booking.objects.get()
    assert (b.start, b.end) == (s.start, s.end)

    home = client_anna.get(reverse("booking:home")).content.decode()
    assert "Bastu" in home

    client_anna.post(reverse("booking:cancel", args=[b.pk]))
    b.refresh_from_db()
    assert b.status == Booking.Status.CANCELLED


def test_book_overnight(client_anna, guestroom):
    arrival = timezone.localdate() + timedelta(days=5)
    client_anna.post(reverse("booking:book", args=["overnattning"]), {"arrival": arrival.isoformat(), "nights": "2"})
    b = Booking.objects.get()
    assert b.nights == 2


def test_cannot_cancel_other_apartments_booking(client, bertil, anna, sauna):
    from booking import services
    s = next_free_slot(sauna)
    b = services.create_booking(member=bertil, resource=sauna, start=s.start, end=s.end)
    client.force_login(anna.user)
    assert client.post(reverse("booking:cancel", args=[b.pk])).status_code == 404


def test_other_apartment_name_not_shown(client_anna, bertil, sauna):
    from booking import services
    s = next_free_slot(sauna)
    services.create_booking(member=bertil, resource=sauna, start=s.start, end=s.end)
    html = client_anna.get(reverse("booking:resource", args=["bastu"])).content.decode()
    assert "Upptaget" in html and "Bertil" not in html


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
