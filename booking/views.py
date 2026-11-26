from datetime import date, datetime, time, timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from payments import services as payments

from . import calendar as cal
from . import rules, services
from .models import Booking, Resource
from .rules import BookingError


def member_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        member = getattr(request.user, "member", None)
        if member is None or not member.active:
            return render(request, "booking/no_member.html", status=403)
        request.member = member
        return view(request, *args, **kwargs)

    return wrapper


@member_required
def home(request):
    now = timezone.now()
    bookings = (
        Booking.objects.holding()
        .upcoming(now)
        .filter(apartment=request.member.apartment)
        .select_related("resource", "member", "charge")
    )
    return render(
        request,
        "booking/home.html",
        {"resources": Resource.objects.filter(active=True), "bookings": bookings, "now": now},
    )


def _parse_month(value, today):
    try:
        y, m = (int(x) for x in value.split("-"))
        return date(y, m, 1)
    except (AttributeError, ValueError):
        return today.replace(day=1)


def _parse_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _add_months(d, n):
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


@member_required
def resource_detail(request, slug):
    resource = get_object_or_404(Resource, slug=slug, active=True)
    now = timezone.now()
    today = timezone.localdate()
    selected = _parse_date(request.GET.get("datum"))
    month = _parse_month(request.GET.get("manad"), today) if not selected else selected.replace(day=1)
    first_month = today.replace(day=1)
    last_month = (today + timedelta(days=resource.max_days_ahead)).replace(day=1)
    month = min(max(month, first_month), last_month)

    weeks = cal.month_days(resource, request.member.apartment_id, month.year, month.month, now)
    days = {d.date: d for w in weeks for d in w}
    if selected and not (selected in days and days[selected].bookable):
        selected = None

    ctx = {
        "resource": resource,
        "weeks": weeks,
        "weekdays": cal.WEEKDAYS_SHORT,
        "month_title": cal.month_title(month.year, month.month),
        "prev_month": _add_months(month, -1) if month > first_month else None,
        "next_month": _add_months(month, 1) if month < last_month else None,
        "selected": selected,
        "today": today,
        "min_notice": payments.min_notice_minutes() if resource.pays_online else 0,
        "deadline_minutes": settings.PAYMENT_DEADLINE_MINUTES,
    }

    if selected:
        earliest = cal.earliest_start(resource, now)
        if resource.kind == Resource.Kind.FLEXIBLE:
            bounds = rules.day_bounds(resource, selected)
            busy = cal.holding_bookings(resource, bounds.start, bounds.end)
            starts = rules.flexible_start_times(resource, selected, busy, earliest)
            ctx["start_times"] = starts
            chosen = request.GET.get("start")
            chosen_start = next((s for s in starts if f"{timezone.localtime(s):%H:%M}" == chosen), None)
            if chosen_start:
                ctx["chosen_start"] = chosen_start
                ctx["durations"] = [
                    {
                        "minutes": m,
                        "label": rules.format_minutes(m),
                        "end": chosen_start + timedelta(minutes=m),
                        "price": payments.price_for(resource, chosen_start, chosen_start + timedelta(minutes=m)),
                    }
                    for m in rules.flexible_durations(resource, chosen_start, busy)
                ]
        else:
            last = rules.overnight_period(selected, resource.max_nights)
            busy = cal.holding_bookings(resource, last.start, last.end)
            options = []
            for n in rules.possible_nights(resource, selected, busy):
                p = rules.overnight_period(selected, n)
                options.append({"nights": n, "departure": p.end, "price": payments.price_for(resource, p.start, p.end)})
            ctx["night_options"] = options

    return render(request, "booking/resource_detail.html", ctx)


@require_POST
@member_required
def book(request, slug):
    resource = get_object_or_404(Resource, slug=slug, active=True)
    back = redirect("booking:resource", slug=slug)
    try:
        day = date.fromisoformat(request.POST["date"])
        back = redirect(f"{reverse('booking:resource', args=[slug])}?datum={day.isoformat()}#val")
        if resource.kind == Resource.Kind.FLEXIBLE:
            hh, mm = (int(x) for x in request.POST["start"].split(":"))
            start = datetime.combine(day, time(hh, mm), rules.local_tz())
            booking = services.create_flexible_booking(
                member=request.member, resource=resource, start=start,
                duration_minutes=int(request.POST["duration"]),
            )
        else:
            booking = services.create_overnight_booking(
                member=request.member, resource=resource, arrival=day,
                nights=int(request.POST.get("nights", 1)),
            )
    except (KeyError, ValueError):
        messages.error(request, "Ogiltig förfrågan.")
        return back
    except BookingError as e:
        messages.error(request, str(e))
        return back

    if booking.status == Booking.Status.PENDING_PAYMENT:
        return redirect("payments:checkout", pk=booking.pk)
    start = timezone.localtime(booking.start)
    messages.success(request, f"Bokat: {resource.name} {start:%-d/%-m} kl {start:%H:%M}. En bekräftelse har skickats till din e-post.")
    return redirect("booking:home")


@require_POST
@member_required
def cancel(request, pk):
    booking = get_object_or_404(Booking, pk=pk)
    if booking.apartment_id != request.member.apartment_id:
        raise Http404
    try:
        booking = services.cancel_booking(booking, by_member=request.member)
    except BookingError as e:
        messages.error(request, str(e))
    else:
        charge = getattr(booking, "charge", None)
        if getattr(booking, "refund_error", None):
            messages.warning(request, "Bokningen är avbokad, men återbetalningen kunde inte göras automatiskt. Styrelsen har fått besked.")
        elif charge and charge.status == "refunded":
            messages.success(request, f"Bokningen är avbokad och {charge.amount:.0f} kr återbetalas.")
        else:
            messages.success(request, "Bokningen är avbokad.")
    return redirect("booking:home")
