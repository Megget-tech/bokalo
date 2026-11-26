"""Axema VAKA-koppling. Implementeras när Axemas integrationsdokumentation finns.

Att ta reda på hos Axema:
- Bas-URL och autentisering (API-nyckel/OAuth) för VAKA Online.
- Hur man skapar en tidsbegränsad behörighet för en person till en dörr/ett område.
  Finns det inte: sätt supports_time_window = False så läggs behörigheter in
  strax före start och tas bort efter slut.
- Hur man listar personer (namn, e-post, lägenhet/objekt, id).
- Kan VAKA skapa en tillfällig PIN-kod för dörren (för tillträdeskod i påminnelsen)?
  Annars returnerar grant() en tom kod och medlemmen använder sin tagg.
- Hur man markerar behörigheter som skapats av oss, så att list_grants bara
  returnerar dem (t.ex. via en egen behörighetsgrupp eller ett namnprefix).
"""

from .base import AccessProvider


class AxemaProvider(AccessProvider):
    supports_time_window = True  # justeras när vi vet vad API:t klarar

    def list_users(self):
        raise NotImplementedError

    def grant(self, user_ref, door_ref, valid_from, valid_to):
        raise NotImplementedError

    def revoke(self, grant_ref):
        raise NotImplementedError

    def list_grants(self, door_ref):
        raise NotImplementedError
