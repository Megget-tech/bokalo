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

FLEXIBLE = "flexible"
OVERNIGHT = "overnight"


class BookingError(Exception):
    """Ett regelbrott med ett meddelande som kan visas för medlemmen."""


@dataclass(frozen=True)
class Period:
    start: datetime
    end: datetime


def local_tz():
    return ZoneInfo(settings.TIME_ZONE)


def timezone_local(dt: datetime) -> datetime:
    return dt.astimezone(local_tz())


def overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def _overlaps_any(start, end, busy) -> bool:
    return any(overlaps(start, end, b.start, b.end) for b in busy)


# --- Flexibel bokningstid ---------------------------------------------------------


def day_bounds(resource, day: date) -> Period:
    tz = local_tz()
    return Period(
        datetime.combine(day, resource.open_time, tz),
        datetime.combine(day, resource.close_time, tz),
    )


def flexible_start_times(resource, day: date, busy, earliest: datetime) -> list[datetime]:
    """Starttider då minst den kortaste bokningstiden är ledig.

    busy: bokningar (objekt med start/end) som upptar lokalen.
    earliest: tidigaste tillåtna starttid (t.ex. nu, eller nu + betalningsmarginal).
    """
    bounds = day_bounds(resource, day)
    step = timedelta(minutes=resource.step_minutes)
    shortest = timedelta(minutes=resource.min_duration_minutes)
    result = []
    t = bounds.start
    while t + shortest <= bounds.end:
        if t >= earliest and not _overlaps_any(t, t + shortest, busy):
            result.append(t)
        t += step
    return result


def flexible_durations(resource, start: datetime, busy) -> list[int]:
    """Tillåtna längder (minuter) från en starttid: från kortaste till längsta,
    i steg om intervallet, utan att krocka med nästa bokning eller stängningstid."""
    close = day_bounds(resource, timezone_local(start).date()).end
    result = []
    for minutes in range(
        resource.min_duration_minutes, resource.max_duration_minutes + 1, resource.step_minutes
    ):
        end = start + timedelta(minutes=minutes)
        if end > close or _overlaps_any(start, end, busy):
            break
        result.append(minutes)
    return result


def _check_flexible(resource, start, end):
    s, e = timezone_local(start), timezone_local(end)
    bounds = day_bounds(resource, s.date())
    if s < bounds.start or e > bounds.end:
        raise BookingError(
            f"{resource.name} kan bokas mellan {resource.open_time:%H:%M} och {resource.close_time:%H:%M}."
        )
    offset = (s - bounds.start).total_seconds() / 60
    minutes = (e - s).total_seconds() / 60
    if offset % resource.step_minutes:
        raise BookingError(f"Starttiden måste vara i steg om {resource.step_minutes} minuter.")
    if minutes % resource.step_minutes:
        raise BookingError(f"Längden måste vara i steg om {resource.step_minutes} minuter.")
    if not resource.min_duration_minutes <= minutes <= resource.max_duration_minutes:
        raise BookingError(
            f"Du kan boka mellan {format_minutes(resource.min_duration_minutes)} "
            f"och {format_minutes(resource.max_duration_minutes)}."
        )


# --- Övernattning ------------------------------------------------------------------


def overnight_period(arrival: date, nights: int) -> Period:
    """Övernattning: från 12:00 ankomstdagen till 11:59 avresedagen."""
    if nights < 1:
        raise BookingError("Välj minst ett dygn.")
    tz = local_tz()
    return Period(
        datetime.combine(arrival, OVERNIGHT_CHECKIN, tz),
        datetime.combine(arrival + timedelta(days=nights), OVERNIGHT_CHECKOUT, tz),
    )


def possible_nights(resource, arrival: date, busy) -> list[int]:
    """Antal dygn (1..max) som går att boka i följd från ett ankomstdatum."""
    result = []
    for n in range(1, resource.max_nights + 1):
        night = overnight_period(arrival + timedelta(days=n - 1), 1)
        if _overlaps_any(night.start, night.end, busy):
            break
        result.append(n)
    return result


def _check_overnight(resource, start, end):
    s, e = timezone_local(start), timezone_local(end)
    if s.time() != OVERNIGHT_CHECKIN or e.time() != OVERNIGHT_CHECKOUT:
        raise BookingError("Övernattning gäller från 12:00 till 11:59 dagen efter.")
    nights = (e.date() - s.date()).days
    if nights > resource.max_nights:
        raise BookingError(f"Du kan boka högst {resource.max_nights} dygn åt gången.")


# --- Gemensamt ----------------------------------------------------------------------


def check_new_booking(
    *,
    resource,
    start: datetime,
    end: datetime,
    now: datetime,
    active_count_for_apartment: int,
    has_overlap: bool,
    min_notice_minutes: int = 0,
):
    """Kontrollera en ny bokning. Kastar BookingError vid regelbrott.

    min_notice_minutes: hur långt före start bokningen senast måste göras
    (t.ex. för att hinna betala före betalningsgränsen).
    """
    if end <= start:
        raise BookingError("Sluttiden måste vara efter starttiden.")
    if start <= now:
        raise BookingError("Det går inte att boka en tid som redan har börjat.")
    if start < now + timedelta(minutes=min_notice_minutes):
        raise BookingError(
            f"Bokningen måste göras senast {format_minutes(min_notice_minutes)} före start, "
            "så att betalningen hinner gå igenom."
        )
    if start > now + timedelta(days=resource.max_days_ahead):
        raise BookingError(f"Du kan boka högst {resource.max_days_ahead} dagar framåt.")

    if resource.kind == FLEXIBLE:
        _check_flexible(resource, start, end)
    elif resource.kind == OVERNIGHT:
        _check_overnight(resource, start, end)

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


def format_minutes(minutes: int) -> str:
    """90 -> '1 h 30 min', 120 -> '2 h', 45 -> '45 min'."""
    h, m = divmod(int(minutes), 60)
    if h and m:
        return f"{h} h {m} min"
    if h:
        return f"{h} h"
    return f"{m} min"
