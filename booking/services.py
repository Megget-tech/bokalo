"""Bokningstjänster: skapar och avbokar bokningar under lås, så att två personer
inte kan boka samma tid samtidigt."""

from django.db import transaction
from django.utils import timezone

from . import rules
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
        # Onlinebetalning (fas 2) sätter status PENDING_PAYMENT med hold_expires_at.
        return Booking.objects.create(
            resource=resource,
            member=member,
            apartment=member.apartment,
            start=start,
            end=end,
            status=Booking.Status.ACTIVE,
        )


def create_overnight_booking(*, member, resource, arrival, nights, now=None) -> Booking:
    period = rules.overnight_period(arrival, nights)
    return create_booking(member=member, resource=resource, start=period.start, end=period.end, now=now)


def cancel_booking(booking: Booking, *, by_member: Member | None = None, now=None) -> Booking:
    """Avboka. by_member=None betyder att styrelsen/systemet avbokar (inga tidsgränser)."""
    now = now or timezone.now()
    with transaction.atomic():
        booking = Booking.objects.select_for_update().select_related("resource").get(pk=booking.pk)
        if booking.status == Booking.Status.CANCELLED:
            return booking
        if by_member is not None:
            if booking.apartment_id != by_member.apartment_id:
                raise BookingError("Du kan bara avboka din lägenhets bokningar.")
            rules.check_cancel(
                booking_start=booking.start,
                now=now,
                cancel_hours_before=booking.resource.cancel_hours_before,
            )
        booking.status = Booking.Status.CANCELLED
        booking.cancelled_at = now
        booking.save(update_fields=["status", "cancelled_at"])
    # Dörrbehörigheten tas bort av avstämningen (access.reconcile) vid nästa körning.
    return booking


def release_expired_holds(now=None) -> int:
    """Släpp obetalda bokningar vars reservationstid har gått ut."""
    now = now or timezone.now()
    return Booking.objects.filter(
        status=Booking.Status.PENDING_PAYMENT, hold_expires_at__lt=now
    ).update(status=Booking.Status.CANCELLED, cancelled_at=now)
