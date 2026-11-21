import pytest

from access.models import FakeVakaUser
from access.providers.base import ProviderError
from access.providers.fake import FakeProvider
from access.sync import sync_members
from booking import services
from booking.models import Booking, Member

from .conftest import NOW, slot


@pytest.fixture
def vaka(db):
    FakeVakaUser.objects.create(ref="V1", name="Anna", email="Anna@Example.se", apartment="1001")
    FakeVakaUser.objects.create(ref="V2", name="Bertil", email="bertil@example.se", apartment="1002")
    FakeVakaUser.objects.create(ref="V9", name="Utan e-post", email="", apartment="1003")


def test_creates_members(vaka):
    r = sync_members(FakeProvider())
    assert (r.created, r.skipped) == (2, 1)
    anna = Member.objects.get(vaka_user_ref="V1")
    assert anna.user.email == "anna@example.se"
    assert anna.apartment.number == "1001"


def test_second_sync_updates(vaka):
    sync_members(FakeProvider())
    FakeVakaUser.objects.filter(ref="V2").update(apartment="1005")
    r = sync_members(FakeProvider())
    assert r.created == 0 and r.updated == 2
    assert Member.objects.get(vaka_user_ref="V2").apartment.number == "1005"


def test_removed_from_vaka_deactivates_and_cancels(vaka, sauna, monkeypatch):
    sync_members(FakeProvider())
    bertil = Member.objects.get(vaka_user_ref="V2")
    s, e = slot(1, 19)
    b = services.create_booking(member=bertil, resource=sauna, start=s, end=e, now=NOW)
    monkeypatch.setattr("django.utils.timezone.now", lambda: NOW)
    FakeVakaUser.objects.filter(ref="V2").delete()
    r = sync_members(FakeProvider())
    assert r.deactivated == 1
    bertil.refresh_from_db()
    assert not bertil.active and not bertil.user.is_active
    b.refresh_from_db()
    assert b.status == Booking.Status.CANCELLED


def test_manual_members_untouched(vaka, anna):
    Member.objects.filter(pk=anna.pk).update(vaka_user_ref=None, source=Member.Source.MANUAL)
    FakeVakaUser.objects.all().delete()
    sync_members(FakeProvider())
    anna.refresh_from_db()
    assert anna.active


def test_provider_error_changes_nothing(vaka):
    sync_members(FakeProvider())
    p = FakeProvider()
    p.fail = True
    with pytest.raises(ProviderError):
        sync_members(p)
    assert Member.objects.filter(active=True).count() == 2
