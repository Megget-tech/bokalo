"""Månadskalender: vilka dagar är lediga, delvis bokade eller fullbokade."""

import calendar as pycal
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from . import rules
from .models import Booking, Resource

# Dagstatus som visas i kalendern
FREE = "free"  # ledigt
PARTIAL = "partial"  # delvis bokat, men det finns lediga tider
FULL = "full"  # fullbokat
MINE = "mine"  # lägenheten har en bokning den dagen
CLOSED = "closed"  # passerat eller för långt fram

MONTHS = ["januari", "februari", "mars", "april", "maj", "juni", "juli",
          "augusti", "september", "oktober", "november", "december"]
WEEKDAYS_SHORT = ["mån", "tis", "ons", "tor", "fre", "lör", "sön"]


@dataclass
class Day:
    date: date
    in_month: bool
    state: str
    bookable: bool  # går att klicka på för att se tider


def month_title(year, month):
    return f"{MONTHS[month - 1].capitalize()} {year}"


def holding_bookings(resource, start, end):
    return list(
        Booking.objects.holding()
        .filter(resource=resource, start__lt=end, end__gt=start)
        .only("start", "end", "apartment_id")
    )


def earliest_start(resource, now):
    """Tidigaste starttid som går att boka just nu (betalda lokaler kräver framförhållning)."""
    from payments import services as payments

    minutes = payments.min_notice_minutes() if resource.pays_online else 0
    return now + timedelta(minutes=minutes)


def month_days(resource: Resource, apartment_id, year: int, month: int, now=None) -> list[list[Day]]:
    now = now or timezone.now()
    tz = rules.local_tz()
    weeks = pycal.Calendar(firstweekday=0).monthdatescalendar(year, month)
    first, last = weeks[0][0], weeks[-1][-1]
    range_start = datetime.combine(first, time.min, tz)
    range_end = datetime.combine(last + timedelta(days=2), time.min, tz)
    bookings = holding_bookings(resource, range_start, range_end)
    earliest = earliest_start(resource, now)
    horizon = now + timedelta(days=resource.max_days_ahead)

    result = []
    for week in weeks:
        row = []
        for d in week:
            state = _day_state(resource, d, bookings, apartment_id, earliest, horizon)
            row.append(Day(d, d.month == month, state, state in (FREE, PARTIAL, MINE) and _has_free(resource, d, bookings, earliest, horizon)))
        result.append(row)
    return result


def _period_for_day(resource, d):
    if resource.kind == Resource.Kind.OVERNIGHT:
        return rules.overnight_period(d, 1)
    return rules.day_bounds(resource, d)


def _has_free(resource, d, bookings, earliest, horizon):
    if resource.kind == Resource.Kind.OVERNIGHT:
        night = rules.overnight_period(d, 1)
        return (
            earliest <= night.start <= horizon
            and not any(rules.overlaps(night.start, night.end, b.start, b.end) for b in bookings)
        )
    starts = rules.flexible_start_times(resource, d, bookings, earliest)
    return any(s <= horizon for s in starts)


def _day_state(resource, d, bookings, apartment_id, earliest, horizon):
    period = _period_for_day(resource, d)
    if period.end <= earliest or period.start > horizon:
        return CLOSED
    todays = [b for b in bookings if rules.overlaps(period.start, period.end, b.start, b.end)]
    if any(b.apartment_id == apartment_id for b in todays):
        return MINE
    if not _has_free(resource, d, bookings, earliest, horizon):
        return FULL if todays else CLOSED
    return PARTIAL if todays else FREE
