"""Avgifter och betalningar kopplade till bokningar."""

import csv
import io
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from booking.models import Booking, Resource

from .models import Charge
from .providers import get_payment_provider
from .providers.base import PaymentError

log = logging.getLogger(__name__)


def price_for(resource: Resource, start, end) -> Decimal:
    if not resource.requires_payment:
        return Decimal(0)
    if resource.kind == Resource.Kind.OVERNIGHT:
        units = Decimal((timezone.localtime(end).date() - timezone.localtime(start).date()).days)
    else:
        units = Decimal(int((end - start).total_seconds() // 60)) / Decimal(60)  # timmar
    return (resource.price * max(units, Decimal(0))).quantize(Decimal("0.01"))


def payment_deadline(start):
    """Senaste tidpunkt för betalning: ett visst antal minuter före start."""
    return start - timedelta(minutes=settings.PAYMENT_DEADLINE_MINUTES)


def min_notice_minutes() -> int:
    """Hur långt före start en betald bokning senast får göras (för att hinna betala)."""
    return settings.PAYMENT_DEADLINE_MINUTES + settings.PAYMENT_MIN_TIME_TO_PAY_MINUTES


def create_charge(booking: Booking, amount: Decimal) -> Charge:
    resource = booking.resource
    local = timezone.localtime(booking.start)
    if resource.kind == Resource.Kind.OVERNIGHT:
        what = f"{resource.name} {local:%Y-%m-%d}, {booking.nights} dygn"
    else:
        end_local = timezone.localtime(booking.end)
        what = f"{resource.name} {local:%Y-%m-%d %H:%M}–{end_local:%H:%M}"
    online = resource.payment_method == Resource.PaymentMethod.ONLINE
    return Charge.objects.create(
        booking=booking,
        apartment=booking.apartment,
        amount=amount,
        description=what,
        method=Charge.Method.ONLINE if online else Charge.Method.INVOICE,
    )


def get_checkout_url(charge: Charge, *, success_url: str, cancel_url: str, now=None) -> str:
    """Skapa (eller återanvänd) en betalsession för en öppen onlineavgift."""
    now = now or timezone.now()
    if charge.status != Charge.Status.OPEN or charge.method != Charge.Method.ONLINE:
        raise PaymentError("Avgiften går inte att betala online.")
    if charge.checkout_url and charge.checkout_expires_at and charge.checkout_expires_at > now + timedelta(minutes=5):
        return charge.checkout_url
    provider = get_payment_provider()
    email = charge.booking.member.user.email if charge.booking.member else ""
    # Betalsidan ska helst sluta gälla vid betalningsgränsen. Stripe kräver 30 min–24 h.
    deadline = charge.booking.hold_expires_at or (now + timedelta(hours=24))
    expires_at = min(max(deadline, now + timedelta(minutes=30)), now + timedelta(hours=23, minutes=55))
    checkout = provider.create_checkout(
        charge, success_url=success_url, cancel_url=cancel_url, customer_email=email, expires_at=expires_at
    )
    charge.provider = provider.name
    charge.checkout_ref = checkout.ref
    charge.checkout_url = checkout.url
    charge.checkout_expires_at = expires_at
    charge.save(update_fields=["provider", "checkout_ref", "checkout_url", "checkout_expires_at"])
    return checkout.url


def mark_paid(charge_id: int, payment_ref: str, now=None) -> Charge:
    """Hantera en lyckad betalning. Idempotent (webhooks kan komma flera gånger)."""
    from booking.notifications import send_payment_received

    now = now or timezone.now()
    refund_needed = False
    with transaction.atomic():
        charge = Charge.objects.select_for_update().select_related("booking").get(pk=charge_id)
        # VOID tas med: en betalning kan komma in strax efter att reservationen släppts.
        if charge.status not in (Charge.Status.OPEN, Charge.Status.VOID):
            return charge
        charge.status = Charge.Status.PAID
        charge.paid_at = now
        charge.provider_ref = payment_ref
        charge.save()

        booking = Booking.objects.select_for_update().get(pk=charge.booking_id)
        if booking.status == Booking.Status.PENDING_PAYMENT:
            booking.status = Booking.Status.ACTIVE
            booking.hold_expires_at = None
            booking.save(update_fields=["status", "hold_expires_at"])
            transaction.on_commit(lambda: send_payment_received(booking))
        elif booking.status == Booking.Status.CANCELLED:
            # Betalningen kom efter att reservationen släppts. Återaktivera om tiden
            # fortfarande är ledig, annars återbetala.
            Resource.objects.select_for_update().get(pk=booking.resource_id)
            taken = (
                Booking.objects.holding()
                .filter(resource_id=booking.resource_id, start__lt=booking.end, end__gt=booking.start)
                .exists()
            )
            if taken or booking.start <= now:
                refund_needed = True
            else:
                booking.status = Booking.Status.ACTIVE
                booking.cancelled_at = None
                booking.hold_expires_at = None
                booking.save(update_fields=["status", "cancelled_at", "hold_expires_at"])
                transaction.on_commit(lambda: send_payment_received(booking))
    if refund_needed:
        log.warning("Betalning för avbokad bokning %s, återbetalar", booking.pk)
        refund(charge)
    return charge


def on_checkout_expired(charge_id: int, checkout_ref: str = "") -> None:
    """En betalsession gick ut. Bokningen ligger kvar till betalningsgränsen; nästa
    klick på betallänken skapar en ny session."""
    Charge.objects.filter(pk=charge_id, status=Charge.Status.OPEN, checkout_ref=checkout_ref).update(
        checkout_ref="", checkout_url="", checkout_expires_at=None
    )


def refund(charge: Charge) -> Charge:
    if charge.status != Charge.Status.PAID:
        raise PaymentError("Bara betalda avgifter kan återbetalas.")
    if charge.method == Charge.Method.ONLINE:
        get_payment_provider().refund(charge)
    charge.status = Charge.Status.REFUNDED
    charge.save(update_fields=["status"])
    return charge


def on_booking_cancelled(booking: Booking) -> str | None:
    """Makulera eller återbetala avgiften för en avbokad bokning.
    Returnerar ett felmeddelande om återbetalningen misslyckades."""
    charge = getattr(booking, "charge", None)
    if charge is None:
        return None
    if charge.status == Charge.Status.OPEN:
        if charge.exported_at:
            # Redan skickad till förvaltaren: kräver manuell kreditering.
            log.warning("Avgift %s var redan exporterad när bokningen avbokades", charge.pk)
        charge.status = Charge.Status.VOID
        charge.save(update_fields=["status"])
        if charge.method == Charge.Method.ONLINE and charge.checkout_ref:
            try:
                get_payment_provider().expire_checkout(charge)
            except PaymentError:
                pass
    elif charge.status == Charge.Status.PAID:
        try:
            refund(charge)
        except PaymentError as e:
            log.error("Återbetalning misslyckades för avgift %s: %s", charge.pk, e)
            return f"Återbetalningen misslyckades: {e}"
    return None


CSV_HEADER = ["Lägenhet", "Namn", "Beskrivning", "Belopp", "Bokningsdatum", "Avgifts-id"]


def export_invoice_csv(charges, now=None) -> str:
    """CSV för förvaltaren (avgiftsavi). Markerar avgifterna som exporterade."""
    now = now or timezone.now()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(CSV_HEADER)
    ids = []
    for c in charges.select_related("apartment", "booking__member"):
        member = c.booking.member
        w.writerow([
            c.apartment.number,
            member.name if member else "",
            c.description,
            f"{c.amount:.2f}".replace(".", ","),
            timezone.localtime(c.created_at).strftime("%Y-%m-%d"),
            c.pk,
        ])
        ids.append(c.pk)
    Charge.objects.filter(pk__in=ids).update(exported_at=now)
    return buf.getvalue()


