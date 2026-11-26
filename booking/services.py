"""Bokningstjänster: skapar och avbokar bokningar under lås, så att två personer
inte kan boka samma tid samtidigt."""

from datetime import timedelta

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
        online = resource.pays_online
        rules.check_new_booking(
            resource=resource,
            start=start,
            end=end,
            now=now,
            active_count_for_apartment=active_count_for_apartment(resource, member.apartment, now),
            has_overlap=_overlapping(resource, start, end).exists(),
            min_notice_minutes=payments.min_notice_minutes() if online else 0,
        )
        amount = payments.price_for(resource, start, end)
        online = online and amount > 0
        booking = Booking.objects.create(
            resource=resource,
            member=member,
            apartment=member.apartment,
            start=start,
            end=end,
            # Onlinebetalning: tiden hålls fram till betalningsgränsen före start.
            status=Booking.Status.PENDING_PAYMENT if online else Booking.Status.ACTIVE,
            hold_expires_at=payments.payment_deadline(start) if online else None,
        )
        if amount > 0:
            payments.create_charge(booking, amount)
        transaction.on_commit(lambda: notifications.send_booking_created(booking))
        return booking


def create_flexible_booking(*, member, resource, start, duration_minutes, now=None) -> Booking:
    end = start + timedelta(minutes=int(duration_minutes))
    return create_booking(member=member, resource=resource, start=start, end=end, now=now)


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
        notifications.send_unpaid_cancelled(booking)
        count += 1
    return count


def send_due_reminders(now=None) -> int:
    """Skicka påminnelse med tillträdesinformation strax före start (efter betalning).

    Kräver att behörigheten är inlagd i passersystemet (så att koden finns)."""
    from django.conf import settings

    from access.models import AccessGrant

    now = now or timezone.now()
    due = Booking.objects.filter(
        status=Booking.Status.ACTIVE,
        reminder_sent_at__isnull=True,
        start__lte=now + timedelta(minutes=settings.REMINDER_MINUTES_BEFORE),
        end__gt=now,
        access_grant__state=AccessGrant.State.GRANTED,
    ).select_related("resource", "member__user", "access_grant")
    count = 0
    for booking in due:
        # Markera först så att en krasch inte ger dubbla mejl.
        updated = Booking.objects.filter(pk=booking.pk, reminder_sent_at__isnull=True).update(
            reminder_sent_at=now
        )
        if updated:
            notifications.send_access_reminder(booking)
            count += 1
    return count
