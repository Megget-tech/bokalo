"""Hela flödet: bokning -> betallänk -> betalning -> behörighet -> påminnelse med kod."""

from datetime import date, timedelta

import pytest
from django.core import mail

from access.models import AccessGrant
from access.providers.fake import FakeProvider
from access.reconcile import reconcile
from booking import calendar as cal
from booking import services
from booking.models import Booking, Resource
from booking.rules import BookingError
from payments import services as pay

from .conftest import NOW, slot


@pytest.fixture
def paid_sauna(sauna):
    sauna.price = 30
    sauna.payment_method = Resource.PaymentMethod.ONLINE
    sauna.save()
    return sauna


def run_on_commit(django_capture_on_commit_callbacks, fn):
    with django_capture_on_commit_callbacks(execute=True):
        return fn()


def test_price_per_hour_for_flexible(anna, paid_sauna):
    s, _ = slot(1, 19)
    b = services.create_flexible_booking(member=anna, resource=paid_sauna, start=s, duration_minutes=90, now=NOW)
    assert b.charge.amount == 45


def test_booking_email_contains_payment_link_and_deadline(anna, paid_sauna, django_capture_on_commit_callbacks):
    s, _ = slot(1, 19)
    b = run_on_commit(django_capture_on_commit_callbacks, lambda: services.create_flexible_booking(
        member=anna, resource=paid_sauna, start=s, duration_minutes=120, now=NOW))
    assert b.status == Booking.Status.PENDING_PAYMENT
    msg = mail.outbox[0]
    assert msg.subject == "Betala din bokning: Bastu"
    assert f"/betalning/bokning/{b.pk}/betala/" in msg.body
    assert "60 kr" in msg.body
    assert "kl 18:00" in msg.body  # betala senast 60 min före 19:00
    assert msg.attachments[0][0] == "bokning.ics"


def test_online_booking_requires_notice_before_deadline(anna, paid_sauna):
    # Nu 12:00. Betalning ska ske 60 min före start och man behöver 15 min på sig: tidigast 13:15.
    with pytest.raises(BookingError, match="senast 1 h 15 min före start"):
        services.create_flexible_booking(member=anna, resource=paid_sauna, start=NOW + timedelta(hours=1), duration_minutes=60, now=NOW)
    services.create_flexible_booking(member=anna, resource=paid_sauna, start=NOW + timedelta(minutes=90), duration_minutes=60, now=NOW)


def test_no_access_until_paid(anna, paid_sauna):
    s, _ = slot(1, 19)
    b = services.create_flexible_booking(member=anna, resource=paid_sauna, start=s, duration_minutes=60, now=NOW)
    reconcile(FakeProvider(), now=NOW)
    assert not AccessGrant.objects.exists()
    pay.mark_paid(b.charge.pk, "pi_1", now=NOW)
    reconcile(FakeProvider(), now=NOW)
    assert AccessGrant.objects.get().state == AccessGrant.State.GRANTED


def test_reminder_with_access_code_sent_once_60_min_before(anna, paid_sauna):
    s, _ = slot(1, 19)
    b = services.create_flexible_booking(member=anna, resource=paid_sauna, start=s, duration_minutes=60, now=NOW)
    pay.mark_paid(b.charge.pk, "pi_1", now=NOW)
    reconcile(FakeProvider(), now=NOW)
    code = AccessGrant.objects.get().access_code
    assert len(code) == 6
    mail.outbox.clear()

    assert services.send_due_reminders(now=s - timedelta(minutes=61)) == 0
    assert services.send_due_reminders(now=s - timedelta(minutes=60)) == 1
    assert services.send_due_reminders(now=s - timedelta(minutes=30)) == 0
    msg = mail.outbox[0]
    assert msg.subject == "Snart dags: Bastu"
    assert f"Din kod till dörren: {code}" in msg.body
    assert "18:50" in msg.body  # gäller från 10 min före start


def test_reminder_waits_for_access_grant(anna, sauna):
    s, _ = slot(1, 19)
    services.create_flexible_booking(member=anna, resource=sauna, start=s, duration_minutes=60, now=NOW)
    assert services.send_due_reminders(now=s - timedelta(minutes=30)) == 0  # ingen behörighet än
    reconcile(FakeProvider(), now=NOW)
    assert services.send_due_reminders(now=s - timedelta(minutes=30)) == 1


def test_reminder_without_code_mentions_tag(anna, sauna):
    s, _ = slot(1, 19)
    services.create_flexible_booking(member=anna, resource=sauna, start=s, duration_minutes=60, now=NOW)
    reconcile(FakeProvider(), now=NOW)
    AccessGrant.objects.update(access_code="")
    services.send_due_reminders(now=s - timedelta(minutes=30))
    assert "Din tagg är aktiverad" in mail.outbox[-1].body


def test_free_booking_gets_confirmation(anna, sauna, django_capture_on_commit_callbacks):
    s, _ = slot(1, 19)
    run_on_commit(django_capture_on_commit_callbacks, lambda: services.create_flexible_booking(
        member=anna, resource=sauna, start=s, duration_minutes=60, now=NOW))
    assert mail.outbox[0].subject == "Bokningsbekräftelse: Bastu"


def test_checkout_session_expires_at_deadline(anna, paid_sauna):
    s, _ = slot(0, 19)  # samma dag: gränsen 18:00 ligger inom Stripes 24 h
    b = services.create_flexible_booking(member=anna, resource=paid_sauna, start=s, duration_minutes=60, now=NOW)
    pay.get_checkout_url(b.charge, success_url="s", cancel_url="c", now=NOW)
    b.charge.refresh_from_db()
    assert b.charge.checkout_expires_at == b.hold_expires_at


def test_checkout_session_capped_at_24h(anna, paid_sauna):
    s, _ = slot(3, 19)
    b = services.create_flexible_booking(member=anna, resource=paid_sauna, start=s, duration_minutes=60, now=NOW)
    pay.get_checkout_url(b.charge, success_url="s", cancel_url="c", now=NOW)
    b.charge.refresh_from_db()
    assert b.charge.checkout_expires_at == NOW + timedelta(hours=23, minutes=55)


def test_checkout_session_at_least_30_min(anna, paid_sauna):
    start = NOW + timedelta(minutes=90)
    b = services.create_flexible_booking(member=anna, resource=paid_sauna, start=start, duration_minutes=60, now=NOW)
    pay.get_checkout_url(b.charge, success_url="s", cancel_url="c", now=NOW)
    b.charge.refresh_from_db()
    assert b.charge.checkout_expires_at == NOW + timedelta(minutes=30)


# --- Kalendern --------------------------------------------------------------------


def test_calendar_day_states(anna, bertil, sauna):
    d1 = (NOW + timedelta(days=1)).date()
    d2 = (NOW + timedelta(days=2)).date()
    d3 = (NOW + timedelta(days=3)).date()
    s, _ = slot(1, 19)
    services.create_flexible_booking(member=bertil, resource=sauna, start=s, duration_minutes=60, now=NOW)
    s2, _ = slot(2, 10)
    services.create_flexible_booking(member=anna, resource=sauna, start=s2, duration_minutes=60, now=NOW)
    weeks = cal.month_days(sauna, anna.apartment_id, d1.year, d1.month, now=NOW)
    days = {d.date: d for w in weeks for d in w}
    assert days[d1].state == cal.PARTIAL and days[d1].bookable
    assert days[d2].state == cal.MINE and days[d2].bookable
    assert days[d3].state == cal.FREE
    assert days[(NOW - timedelta(days=1)).date()].state == cal.CLOSED
    assert days[(NOW + timedelta(days=20)).date()].state == cal.CLOSED  # bortom 14 dagar


def test_calendar_full_day(anna, sauna):
    sauna.max_active_bookings = 10
    sauna.save()
    d = (NOW + timedelta(days=1)).date()
    for h in (7, 10, 13, 16, 19):
        st, _ = slot(1, h)
        services.create_flexible_booking(member=anna, resource=sauna, start=st, duration_minutes=180, now=NOW)
    weeks = cal.month_days(sauna, 999, d.year, d.month, now=NOW)
    day = {x.date: x for w in weeks for x in w}[d]
    assert day.state == cal.FULL and not day.bookable


def test_overnight_calendar(anna, bertil, guestroom):
    services.create_overnight_booking(member=bertil, resource=guestroom, arrival=date(2026, 12, 10), nights=2, now=NOW)
    weeks = cal.month_days(guestroom, anna.apartment_id, 2026, 12, now=NOW)
    days = {d.date: d for w in weeks for d in w}
    assert days[date(2026, 12, 10)].state == cal.FULL
    assert days[date(2026, 12, 11)].state == cal.FULL
    assert days[date(2026, 12, 12)].state == cal.FREE  # ankomst samma dag som avresa går bra


def test_emails_are_not_html_escaped(anna, sauna, django_capture_on_commit_callbacks):
    sauna.name = "Bastu & relax"
    sauna.save()
    s, _ = slot(1, 19)
    run_on_commit(django_capture_on_commit_callbacks, lambda: services.create_flexible_booking(
        member=anna, resource=sauna, start=s, duration_minutes=60, now=NOW))
    assert "Bastu & relax" in mail.outbox[0].body and "&amp;" not in mail.outbox[0].body
