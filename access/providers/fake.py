"""Fejkad leverantör som sparar "VAKA-data" i databasen. Används tills Axemas API finns."""

import logging
import secrets

from ..models import FakeDoorGrant, FakeVakaUser
from .base import AccessProvider, GrantResult, ProviderError, ProviderGrant, ProviderUser

log = logging.getLogger(__name__)


class FakeProvider(AccessProvider):
    supports_time_window = True
    #: Sätt till True i tester för att simulera att passersystemet inte svarar.
    fail = False

    def _check(self):
        if self.fail:
            raise ProviderError("Simulerat fel: passersystemet svarar inte")

    def list_users(self):
        self._check()
        return [
            ProviderUser(ref=u.ref, name=u.name, email=u.email, apartment=u.apartment)
            for u in FakeVakaUser.objects.all()
        ]

    def grant(self, user_ref, door_ref, valid_from, valid_to):
        self._check()
        g = FakeDoorGrant.objects.create(
            user_ref=user_ref, door_ref=door_ref, valid_from=valid_from, valid_to=valid_to,
            code=f"{secrets.randbelow(10**6):06d}",
        )
        log.info("FAKE VAKA: behörighet %s för %s till %s %s–%s", g.pk, user_ref, door_ref, valid_from, valid_to)
        return GrantResult(ref=str(g.pk), code=g.code)

    def revoke(self, grant_ref):
        self._check()
        FakeDoorGrant.objects.filter(pk=grant_ref).delete()
        log.info("FAKE VAKA: behörighet %s borttagen", grant_ref)

    def list_grants(self, door_ref):
        self._check()
        return [
            ProviderGrant(str(g.pk), g.user_ref, g.door_ref, g.valid_from, g.valid_to)
            for g in FakeDoorGrant.objects.filter(door_ref=door_ref)
        ]
