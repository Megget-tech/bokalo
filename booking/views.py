from datetime import date, datetime, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

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
        .select_related("resource", "member")
    )
    return render(
        request,
        "booking/home.html",
        {"resources": Resource.objects.filter(active=True), "bookings": bookings, "now": now},
    )


def _week_offset(request):
    try:
        return max(0, min(int(request.GET.get("vecka", 0)), 52))
    except ValueError:
        return 0


@member_required
def resource_detail(request, slug):
    resource = get_object_or_404(Resource, slug=slug, active=True)
    offset = _week_offset(request)
    now = timezone.now()
    today = timezone.localdate()
    first = today + timedelta(days=7 * offset)
    horizon = now + timedelta(days=resource.max_days_ahead)

    if resource.kind == Resource.Kind.SLOTS:
        days = [first + timedelta(days=i) for i in range(7)]
        period_start = datetime.combine(days[0], datetime.min.time(), rules.local_tz())
        period_end = period_start + timedelta(days=8)
    else:
        days = [first + timedelta(days=i) for i in range(14)]
        period_start = rules.overnight_period(days[0], 1).start
        period_end = rules.overnight_period(days[-1], 1).end

    taken = list(
        Booking.objects.holding()
        .filter(resource=resource, start__lt=period_end, end__gt=period_start)
        .only("start", "end", "apartment_id")
    )

    def state_for(start, end):
        for b in taken:
            if rules.overlaps(start, end, b.start, b.end):
                return "mine" if b.apartment_id == request.member.apartment_id else "taken"
        if start <= now or start > horizon:
            return "unavailable"
        return "free"

    if resource.kind == Resource.Kind.SLOTS:
        templates = list(resource.slot_templates.all())
        rows = [
            {
                "day": d,
                "slots": [
                    {"slot": s, "state": state_for(s.start, s.end)}
                    for s in rules.slots_for_date(templates, d)
                ],
            }
            for d in days
        ]
    else:
        rows = []
        for d in days:
            p = rules.overnight_period(d, 1)
            rows.append({"day": d, "state": state_for(p.start, p.end)})

    return render(
        request,
        "booking/resource_detail.html",
        {
            "resource": resource,
            "rows": rows,
            "offset": offset,
            "nights_range": range(1, resource.max_nights + 1),
        },
    )


@require_POST
@member_required
def book(request, slug):
    resource = get_object_or_404(Resource, slug=slug, active=True)
    try:
        if resource.kind == Resource.Kind.SLOTS:
            start = datetime.fromisoformat(request.POST["start"])
            day = rules.timezone_local(start).date()
            slot = next(
                (s for s in rules.slots_for_date(resource.slot_templates.all(), day) if s.start == start),
                None,
            )
            if slot is None:
                raise BookingError("Det valda passet finns inte.")
            booking = services.create_booking(
                member=request.member, resource=resource, start=slot.start, end=slot.end
            )
        else:
            arrival = date.fromisoformat(request.POST["arrival"])
            nights = int(request.POST.get("nights", 1))
            booking = services.create_overnight_booking(
                member=request.member, resource=resource, arrival=arrival, nights=nights
            )
    except (KeyError, ValueError):
        messages.error(request, "Ogiltig förfrågan.")
        return redirect("booking:resource", slug=slug)
    except BookingError as e:
        messages.error(request, str(e))
        return redirect("booking:resource", slug=slug)

    start = timezone.localtime(booking.start)
    messages.success(request, f"Bokat: {resource.name} {start:%-d/%-m kl %H:%M}.")
    return redirect("booking:home")


@require_POST
@member_required
def cancel(request, pk):
    booking = get_object_or_404(Booking, pk=pk)
    if booking.apartment_id != request.member.apartment_id:
        raise Http404
    try:
        services.cancel_booking(booking, by_member=request.member)
    except BookingError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "Bokningen är avbokad.")
    return redirect("booking:home")
