"""Gränssnittet mot passersystemet.

Allt som är specifikt för Axema hamnar i en implementation av AccessProvider.
Resten av systemet känner bara till det här gränssnittet.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


class ProviderError(Exception):
    """Passersystemet svarade med fel eller gick inte att nå."""


@dataclass(frozen=True)
class ProviderUser:
    ref: str
    name: str
    email: str = ""
    apartment: str = ""


@dataclass(frozen=True)
class GrantResult:
    ref: str
    #: Tillfällig kod för dörren, om passersystemet ger en (annars gäller taggen).
    code: str = ""


@dataclass(frozen=True)
class ProviderGrant:
    ref: str
    user_ref: str
    door_ref: str
    valid_from: datetime
    valid_to: datetime


class AccessProvider(ABC):
    #: True om passersystemet självt kan begränsa en behörighet till ett tidsintervall.
    #: Då läggs behörigheter in direkt vid bokning och dörren fungerar även om vår
    #: server ligger nere. Annars läggs de in strax före start och tas bort efter slut.
    supports_time_window: bool = True

    @abstractmethod
    def list_users(self) -> list[ProviderUser]:
        """Alla personer i passersystemet (för medlemsimport)."""

    @abstractmethod
    def grant(self, user_ref: str, door_ref: str, valid_from: datetime, valid_to: datetime) -> GrantResult:
        """Ge en person behörighet till en dörr. Returnerar referens och ev. tillträdeskod."""

    @abstractmethod
    def revoke(self, grant_ref: str) -> None:
        """Ta bort en behörighet. Ska inte fela om den redan är borta."""

    @abstractmethod
    def list_grants(self, door_ref: str) -> list[ProviderGrant]:
        """Behörigheter som det här systemet har skapat för en dörr (för avstämning)."""
