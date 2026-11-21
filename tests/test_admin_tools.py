from django.core import mail

from access.models import AccessGrant
from access.providers.fake import FakeProvider
from access.reconcile import reconcile
from booking import services
from booking.importer import import_members_csv
from booking.models import Member

from .conftest import NOW, slot


def test_import_members_csv(db, anna):
    text = "﻿lägenhet;namn;e-post;vaka_id\n1005;Doris;doris@example.se;V5\n1001;Anna Ny;ANNA@example.se;\n1006;Fel;inte-epost;\n"
    r = import_members_csv(text)
    assert (r.created, r.updated) == (1, 1)
    assert len(r.errors) == 1 and "Rad 4" in r.errors[0]
    assert Member.objects.get(user__email="doris@example.se").vaka_user_ref == "V5"
    anna.refresh_from_db()
    assert anna.name == "Anna Ny" and anna.vaka_user_ref == "V1"


def test_import_requires_columns(db):
    r = import_members_csv("namn,epost\nX,x@example.se\n")
    assert r.errors == ["Saknade kolumner: lagenhet"]


def test_board_alerted_after_repeated_access_failures(settings, anna, sauna):
    settings.ADMINS = [("Styrelsen", "styrelsen@example.se")]
    s, e = slot(1, 19)
    services.create_booking(member=anna, resource=sauna, start=s, end=e, now=NOW)
    p = FakeProvider()
    p.fail = True
    for _ in range(4):
        reconcile(p, now=NOW)
    alerts = [m for m in mail.outbox if "Dörrbehörighet" in m.subject]
    assert len(alerts) == 1 and alerts[0].to == ["styrelsen@example.se"]
    assert AccessGrant.objects.get().attempts == 4
