"""Skapa demodata: två lokaler, några lägenheter och fejkade VAKA-personer."""

from datetime import time

from django.core.management.base import BaseCommand

from access.models import FakeVakaUser
from access.sync import sync_members
from booking.models import Resource


class Command(BaseCommand):
    help = "Fyll databasen med demodata (för utveckling och test)."

    def handle(self, *args, **opts):
        Resource.objects.update_or_create(
            slug="bastu",
            defaults=dict(
                name="Bastu & relax", kind=Resource.Kind.FLEXIBLE, door_ref="DOOR-BASTU",
                description="Bastu, dusch och vilorum",
                open_time=time(7), close_time=time(22),
                min_duration_minutes=60, max_duration_minutes=180, step_minutes=30,
                max_active_bookings=2, max_days_ahead=30, cancel_hours_before=2,
                price=25, payment_method=Resource.PaymentMethod.ONLINE,
                rules_text="Duscha innan bastun.\nTorka av lavarna och stäng av aggregatet efter dig.",
            ),
        )
        Resource.objects.update_or_create(
            slug="overnattning",
            defaults=dict(
                name="Övernattningsrum", kind=Resource.Kind.OVERNIGHT, door_ref="DOOR-GAST",
                description="Två bäddar, pentry och dusch",
                max_active_bookings=1, max_days_ahead=90, cancel_hours_before=48, max_nights=3,
                price=200, payment_method=Resource.PaymentMethod.ONLINE,
                access_lead_minutes=0, access_grace_minutes=0,
                rules_text="Ta med egna lakan och handdukar.\nUtcheckning senast 11:59.",
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
        self.stdout.write(self.style.SUCCESS(
            "Demodata skapad. Logga in med t.ex. anna@example.se (koden skrivs i loggen)."
        ))
