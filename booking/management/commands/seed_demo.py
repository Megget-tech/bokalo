"""Skapa demodata: två lokaler, några lägenheter och fejkade VAKA-personer."""

from datetime import time

from django.core.management.base import BaseCommand

from access.models import FakeVakaUser
from access.sync import sync_members
from booking.models import Resource, SlotTemplate

SAUNA_SLOTS = [(time(7), time(10)), (time(10), time(13)), (time(13), time(16)),
               (time(16), time(19)), (time(19), time(22))]


class Command(BaseCommand):
    help = "Fyll databasen med demodata (för utveckling)."

    def handle(self, *args, **opts):
        sauna, _ = Resource.objects.update_or_create(
            slug="bastu",
            defaults=dict(
                name="Bastu & relax", kind=Resource.Kind.SLOTS, door_ref="DOOR-BASTU",
                max_active_bookings=2, max_days_ahead=14, cancel_hours_before=2,
                rules_text="Städa efter dig.\nStäng av bastuaggregatet.",
            ),
        )
        if not sauna.slot_templates.exists():
            SlotTemplate.objects.bulk_create(
                SlotTemplate(resource=sauna, weekday=d, start_time=s, end_time=e)
                for d in range(7) for s, e in SAUNA_SLOTS
            )
        Resource.objects.update_or_create(
            slug="overnattning",
            defaults=dict(
                name="Övernattningsrum", kind=Resource.Kind.OVERNIGHT, door_ref="DOOR-GAST",
                max_active_bookings=1, max_days_ahead=90, cancel_hours_before=48, max_nights=3,
                price_per_night=200, access_lead_minutes=0, access_grace_minutes=0, payment_method=Resource.PaymentMethod.INVOICE,
                rules_text="Bädda med egna lakan.\nUtcheckning senast 11:59.",
            ),
        )
        for ref, name, email, apt in [
            ("V1001", "Anna Andersson", "anna@example.se", "1001"),
            ("V1002", "Bertil Berg", "bertil@example.se", "1002"),
            ("V1003", "Cecilia Carlsson", "cecilia@example.se", "1002"),
        ]:
            FakeVakaUser.objects.update_or_create(
                ref=ref, defaults=dict(name=name, email=email, apartment=apt)
            )
        self.stdout.write(str(sync_members()))
        self.stdout.write(self.style.SUCCESS("Demodata skapad. Logga in med t.ex. anna@example.se (koden skrivs i terminalen)."))
