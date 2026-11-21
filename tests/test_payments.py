import hashlib
import hmac
import json
import time
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest import mock

import pytest
from django.core import mail
from django.urls import reverse

from booking import services
from booking.models import Booking, Resource
from payments import services as pay
from payments.models import Charge
from payments.providers.base import PaymentError
from payments.providers.fake import FakePaymentProvider

from .conftest import NOW


@pytest.fixture(autouse=True)
def _reset_refunds():
    FakePaymentProvider.refunds = []


@pytest.fixture
def invoice_room(guestroom):
    guestroom.payment_method = Resource.PaymentMethod.INVOICE
    guestroom.save()
    return guestroom


@pytest.fixture
def online_room(guestroom):
    guestroom.payment_method = Resource.PaymentMethod.ONLINE
    guestroom.save()
    return guestroom


def book(member, room, arrival=date(2026, 12, 10), nights=2, now=NOW):
    return services.create_overnight_booking(member=member, resource=room, arrival=arrival, nights=nights, now=now)


# --- Avgiftsavi -----------------------------------------------------------------


def test_invoice_booking_is_active_with_open_charge(anna, invoice_room, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        b = book(anna, invoice_room)
    assert b.status == Booking.Status.ACTIVE
    c = b.charge
    assert (c.amount, c.method, c.status) == (Decimal("400"), Charge.Method.INVOICE, Charge.Status.OPEN)
    assert "2 nätter" in c.description
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert "avgiftsavin" in msg.body
    assert msg.attachments[0][0] == "bokning.ics"
    assert "BEGIN:VEVENT" in msg.attachments[0][1]


def test_free_resource_has_no_charge(anna, guestroom):
    b = book(anna, guestroom)
    assert not Charge.objects.filter(booking=b).exists()


def test_cancel_invoice_booking_voids_charge(anna, invoice_room):
    b = book(anna, invoice_room)
    services.cancel_booking(b, by_member=anna, now=NOW)
    assert Charge.objects.get().status == Charge.Status.VOID
    assert "struken" in mail.outbox[-1].body


def test_export_csv_marks_exported(anna, bertil, invoice_room):
    book(anna, invoice_room)
    book(bertil, invoice_room, arrival=date(2026, 12, 20), nights=1)
    content = pay.export_invoice_csv(Charge.objects.all())
    lines = content.strip().splitlines()
    assert lines[0].startswith("Lägenhet;Namn")
    assert any(l.startswith("1001;Anna;") and "400,00" in l for l in lines)
    assert any(l.startswith("1002;Bertil;") and "200,00" in l for l in lines)
    assert Charge.objects.filter(exported_at__isnull=True).count() == 0


# --- Onlinebetalning -------------------------------------------------------------


def test_online_booking_is_held_until_paid(anna, online_room):
    b = book(anna, online_room)
    assert b.status == Booking.Status.PENDING_PAYMENT
    assert b.hold_expires_at == NOW + timedelta(minutes=30)
    assert b.charge.method == Charge.Method.ONLINE


def test_pending_booking_blocks_the_slot(anna, bertil, online_room):
    book(anna, online_room)
    with pytest.raises(Exception, match="redan bokad"):
        book(bertil, online_room)


def test_mark_paid_activates_and_is_idempotent(anna, online_room, django_capture_on_commit_callbacks):
    b = book(anna, online_room)
    with django_capture_on_commit_callbacks(execute=True):
        pay.mark_paid(b.charge.pk, "pi_1", now=NOW)
        pay.mark_paid(b.charge.pk, "pi_1", now=NOW)
    b.refresh_from_db()
    assert b.status == Booking.Status.ACTIVE and b.hold_expires_at is None
    c = Charge.objects.get()
    assert c.status == Charge.Status.PAID and c.provider_ref == "pi_1"
    assert len(mail.outbox) == 1 and "betald" in mail.outbox[0].body


def test_expired_hold_releases_booking_and_voids_charge(anna, online_room):
    b = book(anna, online_room)
    assert services.release_expired_holds(now=NOW + timedelta(minutes=31)) == 1
    b.refresh_from_db()
    assert b.status == Booking.Status.CANCELLED
    assert Charge.objects.get().status == Charge.Status.VOID
    assert mail.outbox == []  # ingen avbokningsmejl för en obetald reservation


def test_late_payment_reactivates_if_still_free(anna, online_room):
    b = book(anna, online_room)
    services.release_expired_holds(now=NOW + timedelta(minutes=31))
    assert Charge.objects.get().status == Charge.Status.VOID
    pay.mark_paid(b.charge.pk, "pi_late", now=NOW + timedelta(minutes=32))
    b.refresh_from_db()
    assert b.status == Booking.Status.ACTIVE
    assert FakePaymentProvider.refunds == []


def test_late_payment_refunded_if_slot_taken(anna, bertil, online_room):
    b = book(anna, online_room)
    later = NOW + timedelta(minutes=31)
    services.release_expired_holds(now=later)
    online_room.payment_method = Resource.PaymentMethod.NONE
    online_room.save()
    book(bertil, online_room, now=later)  # någon annan tog tiden
    pay.mark_paid(b.charge.pk, "pi_late", now=later)
    b.refresh_from_db()
    assert b.status == Booking.Status.CANCELLED
    assert Charge.objects.get(booking=b).status == Charge.Status.REFUNDED
    assert FakePaymentProvider.refunds == [b.charge.pk]


def test_cancel_paid_online_refunds(anna, online_room):
    b = book(anna, online_room)
    pay.mark_paid(b.charge.pk, "pi_1", now=NOW)
    b = services.cancel_booking(b, by_member=anna, now=NOW)
    assert Charge.objects.get().status == Charge.Status.REFUNDED
    assert FakePaymentProvider.refunds == [b.charge.pk]
    assert "återbetalas" in mail.outbox[-1].body


def test_failed_refund_is_reported(anna, online_room):
    b = book(anna, online_room)
    pay.mark_paid(b.charge.pk, "pi_1", now=NOW)
    with mock.patch.object(FakePaymentProvider, "refund", side_effect=PaymentError("nere")):
        b = services.cancel_booking(b, by_member=anna, now=NOW)
    assert b.refund_error and "nere" in b.refund_error
    assert Charge.objects.get().status == Charge.Status.PAID


def test_member_can_release_pending_hold_close_to_start(anna, online_room):
    b = book(anna, online_room)
    services.cancel_booking(b, by_member=anna, now=b.start - timedelta(hours=1))
    b.refresh_from_db()
    assert b.status == Booking.Status.CANCELLED


def test_payment_failed_event_releases_hold(anna, online_room):
    b = book(anna, online_room)
    pay.mark_payment_failed(b.charge.pk, now=NOW)
    b.refresh_from_db()
    assert b.status == Booking.Status.CANCELLED


# --- Vyer ---------------------------------------------------------------------------


def test_full_online_flow_in_views(client, anna, online_room):
    from django.utils import timezone
    client.force_login(anna.user)
    arrival = timezone.localdate() + timedelta(days=5)
    r = client.post(reverse("booking:book", args=["overnattning"]), {"arrival": arrival.isoformat(), "nights": "1"})
    b = Booking.objects.get()
    assert r["Location"] == reverse("payments:checkout", args=[b.pk])
    r = client.get(r["Location"])
    assert r["Location"] == reverse("payments:fake_checkout", args=[b.charge.pk])
    assert "Betala 200 kr" in client.get(r["Location"]).content.decode()
    r = client.post(r["Location"], {"action": "pay"})
    assert "bokningen är klar" in client.get(r["Location"]).content.decode()
    b.refresh_from_db()
    assert b.status == Booking.Status.ACTIVE


def test_webhook_view(client, anna, online_room):
    b = book(anna, online_room)
    r = client.post(reverse("payments:webhook"), json.dumps({"charge_id": b.charge.pk, "paid": True, "ref": "pi_9"}), content_type="application/json")
    assert r.status_code == 200
    b.refresh_from_db()
    assert b.status == Booking.Status.ACTIVE


def test_cannot_pay_other_apartments_booking(client, anna, bertil, online_room):
    b = book(anna, online_room)
    client.force_login(bertil.user)
    assert client.get(reverse("payments:checkout", args=[b.pk])).status_code == 404


# --- Stripe-adaptern (utan nätverk) ---------------------------------------------------


@pytest.fixture
def stripe_settings(settings):
    settings.STRIPE_SECRET_KEY = "sk_test_dummy"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test"
    return settings


def _signed(payload: str, secret="whsec_test"):
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={ts},v1={sig}"}


def _event(type_, **obj):
    return json.dumps({"id": "evt_1", "object": "event", "type": type_, "data": {"object": obj}})


def test_stripe_webhook_paid(stripe_settings):
    from payments.providers.stripe import StripeProvider
    payload = _event("checkout.session.completed", payment_status="paid", payment_intent="pi_X", metadata={"charge_id": "7"})
    ev = StripeProvider().parse_webhook(payload.encode(), _signed(payload))
    assert (ev.charge_id, ev.paid, ev.payment_ref) == (7, True, "pi_X")


def test_stripe_webhook_expired(stripe_settings):
    from payments.providers.stripe import StripeProvider
    payload = _event("checkout.session.expired", metadata={"charge_id": "7"})
    ev = StripeProvider().parse_webhook(payload.encode(), _signed(payload))
    assert (ev.charge_id, ev.paid) == (7, False)


def test_stripe_webhook_bad_signature(stripe_settings):
    from payments.providers.stripe import StripeProvider
    payload = _event("checkout.session.completed", payment_status="paid", metadata={"charge_id": "7"})
    with pytest.raises(PaymentError):
        StripeProvider().parse_webhook(payload.encode(), _signed(payload, secret="fel"))


def test_stripe_create_checkout_params(stripe_settings, anna, online_room):
    from payments.providers.stripe import StripeProvider
    b = book(anna, online_room)
    p = StripeProvider()
    p.client = mock.Mock()
    p.client.checkout.sessions.create.return_value = NS(id="cs_1", url="https://checkout.stripe.com/x")
    co = p.create_checkout(b.charge, success_url="https://s", cancel_url="https://c", customer_email="anna@example.se")
    params = p.client.checkout.sessions.create.call_args.kwargs["params"]
    assert co.ref == "cs_1"
    assert params["line_items"][0]["price_data"]["unit_amount"] == 40000
    assert params["line_items"][0]["price_data"]["currency"] == "sek"
    assert params["metadata"] == {"charge_id": str(b.charge.pk)}
