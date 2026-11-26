"""E-post till medlemmar och styrelse. Fel vid utskick loggas men stoppar aldrig en bokning."""

import logging
from datetime import timezone as dt_timezone

from django.conf import settings
from django.core.mail import EmailMessage, mail_admins
from django.template.loader import render_to_string
from django.utils import timezone

log = logging.getLogger(__name__)


def _ics(booking) -> str:
    def fmt(dt):
        return dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    return "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//brf-bokning//SV",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:booking-{booking.pk}@brf-bokning",
        f"DTSTAMP:{fmt(timezone.now())}",
        f"DTSTART:{fmt(booking.start)}",
        f"DTEND:{fmt(booking.end)}",
        f"SUMMARY:{booking.resource.name}",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ])


def _recipient(booking):
    if booking.member and booking.member.user.email:
        return booking.member.user.email
    return None


def _context(booking, **extra):
    from django.urls import reverse

    from .rules import format_minutes

    return {
        "booking": booking,
        "charge": getattr(booking, "charge", None),
        "duration": format_minutes(booking.duration_minutes),
        "SITE_NAME": settings.SITE_NAME,
        "site_url": settings.SITE_URL,
        "pay_url": settings.SITE_URL + reverse("payments:checkout", args=[booking.pk]),
        "deadline_minutes": settings.PAYMENT_DEADLINE_MINUTES,
        **extra,
    }


def _send(booking, subject, template, *, ics=False, **extra):
    to = _recipient(booking)
    if not to:
        return
    msg = EmailMessage(
        subject=subject,
        body=render_to_string(template, _context(booking, **extra)),
        to=[to],
    )
    if ics:
        msg.attach("bokning.ics", _ics(booking), "text/calendar")
    try:
        msg.send()
    except Exception:
        log.exception("Kunde inte skicka '%s' för bokning %s", subject, booking.pk)


def send_booking_created(booking):
    """Direkt efter bokning: bekräftelse, eller betallänk om betalning krävs."""
    if booking.status == booking.Status.PENDING_PAYMENT:
        _send(booking, f"Betala din bokning: {booking.resource.name}", "booking/email/payment_required.txt", ics=True)
    else:
        _send(booking, f"Bokningsbekräftelse: {booking.resource.name}", "booking/email/confirmation.txt", ics=True)


def send_payment_received(booking):
    _send(booking, f"Betalning mottagen: {booking.resource.name}", "booking/email/payment_received.txt")


def send_access_reminder(booking):
    grant = getattr(booking, "access_grant", None)
    _send(
        booking,
        f"Snart dags: {booking.resource.name}",
        "booking/email/access_reminder.txt",
        access_code=grant.access_code if grant else "",
    )


def send_unpaid_cancelled(booking):
    _send(booking, f"Bokningen avbröts: {booking.resource.name}", "booking/email/unpaid_cancelled.txt")


def send_cancellation(booking):
    _send(booking, f"Avbokad: {booking.resource.name}", "booking/email/cancellation.txt")


def alert_board(subject, body):
    """Larm till styrelsen (ADMINS i inställningarna)."""
    try:
        mail_admins(subject, body)
    except Exception:
        log.exception("Kunde inte skicka larm: %s", subject)
