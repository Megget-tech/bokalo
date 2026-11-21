"""Bokningsregler som ren logik (inga databasanrop), så att de är lätta att testa.

Tider är alltid tidszonsmedvetna. Lokal tid är föreningens (settings.TIME_ZONE).
Intervall är halvöppna: [start, end).
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings

OVERNIGHT_CHECKIN = time(12, 0)
OVERNIGHT_CHECKOUT = time(11, 59)


class BookingError(Exception):
    """Ett regelbrott med ett meddelande som kan visas för medlemmen."""


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime


def local_tz():
    return ZoneInfo(settings.TIME_ZONE)


def slots_for_date(templates, day: date) -> list[Slot]:
    """Fasta pass för ett datum utifrån passmallar (objekt med weekday/start_time/end_time)."""
    tz = local_tz()
    slots = [
        Slot(datetime.combine(day, t.start_time, tz), datetime.combine(day, t.end_time, tz))
        for t in templates
        if t.weekday == day.weekday()
    ]
    return sorted(slots, key=lambda s: s.start)


def overnight_period(arrival: date, nights: int) -> Slot:
    """Övernattning: från 12:00 ankomstdagen till 11:59 avresedagen."""
    if nights < 1:
        raise BookingError("Välj minst en natt.")
    tz = local_tz()
    departure = arrival + timedelta(days=nights)
    return Slot(
        datetime.combine(arrival, OVERNIGHT_CHECKIN, tz),
        datetime.combine(departure, OVERNIGHT_CHECKOUT, tz),
    )


def overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def check_new_booking(
    *,
    resource,
    start: datetime,
    end: datetime,
    now: datetime,
    active_count_for_apartment: int,
    has_overlap: bool,
    valid_slots: list[Slot] | None = None,
):
    """Kontrollera en ny bokning. Kastar BookingError vid regelbrott.

    valid_slots: tillåtna pass för datumet (krävs för resurser med fasta pass).
    """
    if end <= start:
        raise BookingError("Sluttiden måste vara efter starttiden.")
    if start <= now:
        raise BookingError("Det går inte att boka en tid som redan har börjat.")
    if start > now + timedelta(days=resource.max_days_ahead):
        raise BookingError(f"Du kan boka högst {resource.max_days_ahead} dagar framåt.")

    if resource.kind == "slots":
        if not any(s.start == start and s.end == end for s in (valid_slots or [])):
            raise BookingError("Det valda passet finns inte.")
    elif resource.kind == "overnight":
        s, e = timezone_local(start), timezone_local(end)
        if s.time() != OVERNIGHT_CHECKIN or e.time() != OVERNIGHT_CHECKOUT:
            raise BookingError("Övernattning gäller från 12:00 till 11:59 dagen efter.")
        nights = (e.date() - s.date()).days
        if nights > resource.max_nights:
            raise BookingError(f"Du kan boka högst {resource.max_nights} nätter åt gången.")

    if has_overlap:
        raise BookingError("Tiden är redan bokad.")
    if active_count_for_apartment >= resource.max_active_bookings:
        raise BookingError(
            f"Din lägenhet har redan {resource.max_active_bookings} kommande bokningar "
            f"av {resource.name}, vilket är max."
        )


def check_cancel(*, booking_start: datetime, now: datetime, cancel_hours_before: int):
    """Medlemmar får avboka fram till avbokningsgränsen. Styrelsen kan alltid avboka i admin."""
    if booking_start <= now:
        raise BookingError("Bokningen har redan börjat och kan inte avbokas.")
    if booking_start - now < timedelta(hours=cancel_hours_before):
        raise BookingError(
            f"Avbokning måste göras senast {cancel_hours_before} timmar före start. "
            "Kontakta styrelsen."
        )


def timezone_local(dt: datetime) -> datetime:
    return dt.astimezone(local_tz())
