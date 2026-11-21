"""Medlemsimport från passersystemet."""

import logging
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from booking.models import Apartment, Booking, Member
from booking.services import cancel_booking

from .providers import get_provider

log = logging.getLogger(__name__)


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    deactivated: int = 0
    skipped: int = 0


def sync_members(provider=None) -> SyncResult:
    """Skapa/uppdatera medlemmar från VAKA. Personer som försvunnit ur VAKA inaktiveras
    och deras kommande bokningar avbokas. Manuellt tillagda medlemmar rörs inte."""
    provider = provider or get_provider()
    users = provider.list_users()  # hämta först: fel här ska inte inaktivera någon
    User = get_user_model()
    result = SyncResult()
    seen = set()

    with transaction.atomic():
        for pu in users:
            if not pu.email or not pu.apartment:
                # Utan e-post kan personen inte logga in; utan lägenhet kan vi inte tillämpa regler.
                result.skipped += 1
                continue
            seen.add(pu.ref)
            apartment, _ = Apartment.objects.get_or_create(number=pu.apartment)
            email = pu.email.strip().lower()
            member = Member.objects.filter(vaka_user_ref=pu.ref).select_related("user").first()
            if member is None:
                # Kanske finns redan manuellt med samma e-post: koppla ihop.
                member = Member.objects.filter(user__email__iexact=email).select_related("user").first()
            if member is None:
                user, _ = User.objects.get_or_create(
                    username=email, defaults={"email": email, "first_name": pu.name[:150]}
                )
                Member.objects.create(
                    user=user,
                    apartment=apartment,
                    name=pu.name,
                    vaka_user_ref=pu.ref,
                    source=Member.Source.VAKA,
                )
                result.created += 1
                continue
            member.name = pu.name
            member.apartment = apartment
            member.vaka_user_ref = pu.ref
            member.source = Member.Source.VAKA
            member.active = True
            member.save()
            if member.user.email.lower() != email:
                member.user.email = email
                member.user.username = email
            member.user.is_active = True
            member.user.save()
            result.updated += 1

        gone = Member.objects.filter(source=Member.Source.VAKA, active=True).exclude(
            vaka_user_ref__in=seen
        )
        now = timezone.now()
        for member in gone:
            member.active = False
            member.save(update_fields=["active"])
            member.user.is_active = False
            member.user.save(update_fields=["is_active"])
            for b in Booking.objects.holding().filter(member=member, start__gt=now):
                cancel_booking(b)
            result.deactivated += 1

    log.info("Medlemssynk: %s", result)
    return result
