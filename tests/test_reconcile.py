from datetime import timedelta

import pytest

from access.models import AccessGrant, FakeDoorGrant
from access.providers.fake import FakeProvider
from access.reconcile import reconcile
from booking import services

from .conftest import NOW, slot


@pytest.fixture
def provider():
    return FakeProvider()


@pytest.fixture
def booking(anna, sauna):
    s, e = slot(1, 19)
    return services.create_booking(member=anna, resource=sauna, start=s, end=e, now=NOW)


def test_grant_created_with_lead_and_grace(provider, booking):
    r = reconcile(provider, now=NOW)
    assert r.granted == 1
    g = AccessGrant.objects.get(booking=booking)
    assert g.state == AccessGrant.State.GRANTED
    assert g.valid_from == booking.start - timedelta(minutes=10)
    assert g.valid_to == booking.end + timedelta(minutes=10)
    fg = FakeDoorGrant.objects.get()
    assert (fg.user_ref, fg.door_ref) == ("V1", "DOOR-BASTU")


def test_reconcile_is_idempotent(provider, booking):
    reconcile(provider, now=NOW)
    r = reconcile(provider, now=NOW)
    assert r.granted == 0 and r.revoked == 0
    assert FakeDoorGrant.objects.count() == 1


def test_cancel_revokes(provider, booking, anna):
    reconcile(provider, now=NOW)
    services.cancel_booking(booking, by_member=anna, now=NOW)
    r = reconcile(provider, now=NOW)
    assert r.revoked == 1
    assert FakeDoorGrant.objects.count() == 0
    assert AccessGrant.objects.get().state == AccessGrant.State.REVOKED


def test_expired_grant_is_removed(provider, booking):
    reconcile(provider, now=NOW)
    r = reconcile(provider, now=booking.end + timedelta(minutes=11))
    assert r.revoked == 1
    assert FakeDoorGrant.objects.count() == 0


def test_provider_failure_then_recovery(provider, booking):
    provider.fail = True
    r = reconcile(provider, now=NOW)
    g = AccessGrant.objects.get()
    assert g.state == AccessGrant.State.FAILED and g.attempts == 1 and r.errors
    provider.fail = False
    reconcile(provider, now=NOW)
    g.refresh_from_db()
    assert g.state == AccessGrant.State.GRANTED and g.last_error == ""


def test_failed_revoke_is_retried(provider, booking, anna):
    reconcile(provider, now=NOW)
    services.cancel_booking(booking, by_member=anna, now=NOW)
    provider.fail = True
    reconcile(provider, now=NOW)
    assert AccessGrant.objects.get().state == AccessGrant.State.GRANTED
    provider.fail = False
    reconcile(provider, now=NOW)
    assert AccessGrant.objects.get().state == AccessGrant.State.REVOKED
    assert FakeDoorGrant.objects.count() == 0


def test_grant_removed_in_vaka_is_recreated(provider, booking):
    reconcile(provider, now=NOW)
    FakeDoorGrant.objects.all().delete()  # någon tog bort den direkt i VAKA
    reconcile(provider, now=NOW)
    assert FakeDoorGrant.objects.count() == 1
    assert AccessGrant.objects.get().state == AccessGrant.State.GRANTED


def test_orphan_grant_in_vaka_is_removed(provider, booking):
    reconcile(provider, now=NOW)
    FakeDoorGrant.objects.create(user_ref="X", door_ref="DOOR-BASTU", valid_from=NOW, valid_to=NOW)
    r = reconcile(provider, now=NOW)
    assert r.orphans_removed == 1
    assert FakeDoorGrant.objects.count() == 1


def test_member_without_vaka_ref_fails_clearly(provider, booking, anna):
    anna.vaka_user_ref = None
    anna.save()
    reconcile(provider, now=NOW)
    g = AccessGrant.objects.get()
    assert g.state == AccessGrant.State.FAILED
    assert "VAKA-id" in g.last_error


def test_without_time_window_support_grants_only_near_start(provider, booking):
    provider.supports_time_window = False
    assert reconcile(provider, now=NOW).granted == 0
    assert reconcile(provider, now=booking.start - timedelta(minutes=5)).granted == 1


def test_overnight_guests_never_share_access(provider, anna, bertil, guestroom):
    from datetime import date
    guestroom.access_lead_minutes = guestroom.access_grace_minutes = 0
    guestroom.save()
    services.create_overnight_booking(member=anna, resource=guestroom, arrival=date(2026, 12, 10), nights=1, now=NOW)
    services.create_overnight_booking(member=bertil, resource=guestroom, arrival=date(2026, 12, 11), nights=1, now=NOW)
    reconcile(provider, now=NOW)
    a, b = AccessGrant.objects.order_by("valid_from")
    assert a.valid_to < b.valid_from
