"""Avstämning mellan bokningar och behörigheter i passersystemet.

Körs regelbundet av workern. Den är idempotent: den räknar ut vilka behörigheter
som *borde* finnas och rättar till skillnaden, så att nätverksfel, omstarter och
ändringar som gjorts direkt i VAKA rättas till av sig själva vid nästa körning.
"""

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from booking.models import Booking

from .models import AccessGrant
from .providers import get_provider
from .providers.base import ProviderError

log = logging.getLogger(__name__)

# Övre gräns för marginal efter slut (för databasfiltret).
MAX_MARGIN_MINUTES = 24 * 60


@dataclass
class Result:
    granted: int = 0
    revoked: int = 0
    failed: int = 0
    orphans_removed: int = 0
    errors: list[str] = field(default_factory=list)


def access_window(booking):
    r = booking.resource
    return (
        booking.start - timedelta(minutes=r.access_lead_minutes),
        booking.end + timedelta(minutes=r.access_grace_minutes),
    )


def _fail(grant, booking, message, result):
    grant.state = AccessGrant.State.FAILED
    grant.attempts += 1
    grant.last_error = message
    grant.save()
    result.failed += 1
    result.errors.append(f"{booking}: {message}")
    log.warning("Behörighet misslyckades för %s: %s", booking, message)


def _bookings_needing_access(provider, now):
    qs = Booking.objects.filter(
        status=Booking.Status.ACTIVE, end__gt=now - timedelta(minutes=MAX_MARGIN_MINUTES)
    ).select_related("resource", "member")
    result = []
    for b in qs:
        valid_from, valid_to = access_window(b)
        if valid_to <= now:
            continue
        # Utan tidsfönster i passersystemet: lägg bara in det som ska gälla nu.
        if not provider.supports_time_window and valid_from > now:
            continue
        result.append(b)
    return result


def _check_drift(provider, result):
    """Jämför våra registrerade behörigheter med vad passersystemet faktiskt har."""
    granted = AccessGrant.objects.filter(state=AccessGrant.State.GRANTED).select_related(
        "booking__resource"
    )
    by_door = {}
    for g in granted:
        by_door.setdefault(g.booking.resource.door_ref, []).append(g)

    for door_ref, ours in by_door.items():
        actual = {pg.ref for pg in provider.list_grants(door_ref)}
        known = set()
        for g in ours:
            known.add(g.provider_ref)
            if g.provider_ref not in actual:
                _fail(g, g.booking, "Behörigheten saknades i passersystemet, läggs in igen", result)
        for ref in actual - known:
            provider.revoke(ref)
            result.orphans_removed += 1


def reconcile(provider=None, now=None) -> Result:
    provider = provider or get_provider()
    now = now or timezone.now()
    result = Result()

    try:
        _check_drift(provider, result)
    except ProviderError as e:
        result.errors.append(f"Avstämning mot passersystemet misslyckades: {e}")
        log.warning("Driftkontroll misslyckades: %s", e)

    # 1. Lägg in behörigheter som saknas eller har fel tider.
    for booking in _bookings_needing_access(provider, now):
        valid_from, valid_to = access_window(booking)
        grant, _ = AccessGrant.objects.get_or_create(
            booking=booking, defaults={"state": AccessGrant.State.FAILED}
        )
        if (
            grant.state == AccessGrant.State.GRANTED
            and grant.valid_from == valid_from
            and grant.valid_to == valid_to
        ):
            continue
        if not booking.resource.door_ref:
            _fail(grant, booking, "Lokalen saknar dörr i passersystemet (door_ref)", result)
            continue
        if not booking.member or not booking.member.vaka_user_ref:
            _fail(grant, booking, "Medlemmen saknar koppling till VAKA (VAKA-id)", result)
            continue
        try:
            if grant.state == AccessGrant.State.GRANTED and grant.provider_ref:
                provider.revoke(grant.provider_ref)  # tiderna har ändrats
            ref = provider.grant(
                booking.member.vaka_user_ref, booking.resource.door_ref, valid_from, valid_to
            )
        except ProviderError as e:
            _fail(grant, booking, str(e), result)
            continue
        grant.provider_ref = ref
        grant.state = AccessGrant.State.GRANTED
        grant.valid_from, grant.valid_to = valid_from, valid_to
        grant.last_error = ""
        grant.attempts = 0
        grant.save()
        result.granted += 1

    # 2. Ta bort behörigheter för avbokade eller passerade bokningar.
    to_revoke = AccessGrant.objects.filter(state=AccessGrant.State.GRANTED).filter(
        ~Q(booking__status=Booking.Status.ACTIVE) | Q(valid_to__lte=now)
    )
    for grant in to_revoke.select_related("booking"):
        try:
            provider.revoke(grant.provider_ref)
        except ProviderError as e:
            # Ligger kvar som GRANTED och försöks igen nästa körning.
            grant.attempts += 1
            grant.last_error = f"Kunde inte ta bort: {e}"
            grant.save()
            result.errors.append(f"{grant.booking}: {grant.last_error}")
            continue
        grant.state = AccessGrant.State.REVOKED
        grant.last_error = ""
        grant.save()
        result.revoked += 1

    return result
