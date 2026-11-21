"""E-post till medlemmar och styrelse. Fel vid utskick loggas men stoppar aldrig en bokning."""

import logging
from datetime import timezone as dt_timezone

from django.conf import settings
from django.core.mail import EmailMessage, mail_admins, send_mail
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


def send_booking_confirmation(booking):
    to = _recipient(booking)
    if not to:
        return
    ctx = {"booking": booking, "charge": getattr(booking, "charge", None), "SITE_NAME": settings.SITE_NAME}
    msg = EmailMessage(
        subject=f"Bokningsbekräftelse: {booking.resource.name}",
        body=render_to_string("booking/email/confirmation.txt", ctx),
        to=[to],
    )
    msg.attach("bokning.ics", _ics(booking), "text/calendar")
    try:
        msg.send()
    except Exception:
        log.exception("Kunde inte skicka bekräftelse för bokning %s", booking.pk)


def send_cancellation(booking):
    to = _recipient(booking)
    if not to:
        return
    ctx = {"booking": booking, "charge": getattr(booking, "charge", None), "SITE_NAME": settings.SITE_NAME}
    try:
        send_mail(
            f"Avbokad: {booking.resource.name}",
            render_to_string("booking/email/cancellation.txt", ctx),
            None,
            [to],
        )
    except Exception:
        log.exception("Kunde inte skicka avbokningsmejl för bokning %s", booking.pk)


def alert_board(subject, body):
    """Larm till styrelsen (ADMINS i inställningarna)."""
    try:
        mail_admins(subject, body)
    except Exception:
        log.exception("Kunde inte skicka larm: %s", subject)
