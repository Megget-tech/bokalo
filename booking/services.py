"""Bokningstjänster: skapar och avbokar bokningar under lås, så att två personer
inte kan boka samma tid samtidigt."""

from django.db import transaction
from django.utils import timezone

from payments import services as payments

from . import notifications, rules
from .models import Booking, Member, Resource
from .rules import BookingError


def _overlapping(resource, start, end, exclude_id=None):
    qs = Booking.objects.holding().filter(resource=resource, start__lt=end, end__gt=start)
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    return qs


def active_count_for_apartment(resource, apartment, now):
    return (
        Booking.objects.holding()
        .upcoming(now)
        .filter(resource=resource, apartment=apartment)
        .count()
    )


def create_booking(*, member: Member, resource: Resource, start, end, now=None) -> Booking:
    now = now or timezone.now()
    if not member.active:
        raise BookingError("Ditt konto är inte aktivt. Kontakta styrelsen.")
    if not resource.active:
        raise BookingError("Lokalen går inte att boka just nu.")

    with transaction.atomic():
        # Lås lokalen så att samtidiga bokningar av samma lokal köas.
        resource = Resource.objects.select_for_update().get(pk=resource.pk)
        valid_slots = None
        if resource.kind == Resource.Kind.SLOTS:
            day = rules.timezone_local(start).date()
            valid_slots = rules.slots_for_date(resource.slot_templates.all(), day)

        rules.check_new_booking(
            resource=resource,
            start=start,
            end=end,
            now=now,
            active_count_for_apartment=active_count_for_apartment(resource, member.apartment, now),
            has_overlap=_overlapping(resource, start, end).exists(),
            valid_slots=valid_slots,
        )
        amount = payments.price_for(resource, start, end)
        online = amount > 0 and resource.payment_method == Resource.PaymentMethod.ONLINE
        booking = Booking.objects.create(
            resource=resource,
            member=member,
            apartment=member.apartment,
            start=start,
            end=end,
            # Onlinebetalning: tiden hålls en stund medan medlemmen betalar.
            status=Booking.Status.PENDING_PAYMENT if online else Booking.Status.ACTIVE,
            hold_expires_at=payments.hold_expiry(now) if online else None,
        )
        if amount > 0:
            payments.create_charge(booking, amount)
        if booking.status == Booking.Status.ACTIVE:
            transaction.on_commit(lambda: notifications.send_booking_confirmation(booking))
        return booking


def create_overnight_booking(*, member, resource, arrival, nights, now=None) -> Booking:
    period = rules.overnight_period(arrival, nights)
    return create_booking(member=member, resource=resource, start=period.start, end=period.end, now=now)


def cancel_booking(booking: Booking, *, by_member: Member | None = None, now=None, notify=True) -> Booking:
    """Avboka. by_member=None betyder att styrelsen/systemet avbokar (inga tidsgränser).

    Avgiften makuleras, eller återbetalas om den är betald online.
    Dörrbehörigheten tas bort av avstämningen (access.reconcile) vid nästa körning.
    """
    now = now or timezone.now()
    with transaction.atomic():
        booking = Booking.objects.select_for_update().select_related("resource").get(pk=booking.pk)
        if booking.status == Booking.Status.CANCELLED:
            return booking
        was_active = booking.status == Booking.Status.ACTIVE
        if by_member is not None:
            if booking.apartment_id != by_member.apartment_id:
                raise BookingError("Du kan bara avboka din lägenhets bokningar.")
            if was_active:  # en obetald reservation får alltid släppas
                rules.check_cancel(
                    booking_start=booking.start,
                    now=now,
                    cancel_hours_before=booking.resource.cancel_hours_before,
                )
        booking.status = Booking.Status.CANCELLED
        booking.cancelled_at = now
        booking.save(update_fields=["status", "cancelled_at"])
    booking.refund_error = payments.on_booking_cancelled(booking)
    if notify and was_active:
        notifications.send_cancellation(booking)
    return booking


def release_expired_holds(now=None) -> int:
    """Släpp obetalda bokningar vars reservationstid har gått ut."""
    now = now or timezone.now()
    expired = Booking.objects.filter(status=Booking.Status.PENDING_PAYMENT, hold_expires_at__lt=now)
    count = 0
    for booking in expired:
        cancel_booking(booking, now=now)
        count += 1
    return count
