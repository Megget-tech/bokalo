import json
import logging

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from booking.models import Booking
from booking.views import member_required

from . import services
from .models import Charge
from .providers import get_payment_provider
from .providers.base import PaymentError

log = logging.getLogger(__name__)


def _own_booking(request, pk):
    booking = get_object_or_404(Booking.objects.select_related("resource", "charge"), pk=pk)
    if booking.apartment_id != request.member.apartment_id:
        raise Http404
    return booking


@member_required
def checkout(request, pk):
    booking = _own_booking(request, pk)
    charge = getattr(booking, "charge", None)
    if booking.status != Booking.Status.PENDING_PAYMENT or charge is None:
        return redirect("booking:home")
    try:
        url = services.get_checkout_url(
            charge,
            success_url=request.build_absolute_uri(reverse("payments:done", args=[booking.pk])),
            cancel_url=request.build_absolute_uri(reverse("booking:home")),
        )
    except PaymentError as e:
        log.error("Kunde inte starta betalning för bokning %s: %s", booking.pk, e)
        messages.error(request, "Betalningen kunde inte startas just nu. Försök igen om en stund.")
        return redirect("booking:home")
    return redirect(url)


@member_required
def done(request, pk):
    booking = _own_booking(request, pk)
    return render(request, "payments/done.html", {"booking": booking})


@csrf_exempt
@require_POST
def webhook(request):
    try:
        event = get_payment_provider().parse_webhook(request.body, request.headers)
    except PaymentError as e:
        log.warning("Avvisad webhook: %s", e)
        return HttpResponseBadRequest("invalid")
    if event is None:
        return HttpResponse("ignored")
    if not Charge.objects.filter(pk=event.charge_id).exists():
        return HttpResponse("unknown charge")
    if event.paid:
        services.mark_paid(event.charge_id, event.payment_ref)
    else:
        services.mark_payment_failed(event.charge_id)
    return HttpResponse("ok")


def _require_fake():
    if not settings.PAYMENT_PROVIDER.endswith("FakePaymentProvider"):
        raise Http404


@member_required
def fake_checkout(request, charge_id):
    """Låtsasbetalsida för utveckling (finns bara med den fejkade betaltjänsten)."""
    _require_fake()
    charge = get_object_or_404(Charge, pk=charge_id, apartment=request.member.apartment)
    if request.method == "POST":
        if request.POST.get("action") == "pay":
            services.mark_paid(charge.pk, f"fake_pi_{charge.pk}")
            return redirect("payments:done", pk=charge.booking_id)
        return redirect("booking:home")
    return render(request, "payments/fake_checkout.html", {"charge": charge})
