"""Gränssnittet mot betaltjänster. Stripe är en implementation; fler (Swish
Handel, Nets m.fl.) kan läggas till utan att bokningslogiken ändras."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class PaymentError(Exception):
    pass


@dataclass(frozen=True)
class Checkout:
    ref: str  # betaltjänstens id för betalsessionen
    url: str  # dit medlemmen skickas för att betala


@dataclass(frozen=True)
class PaymentEvent:
    charge_id: int
    paid: bool  # True = betald, False = betalsessionen gick ut
    payment_ref: str = ""  # referens som behövs för återbetalning
    checkout_ref: str = ""  # vilken betalsession händelsen gäller


class PaymentProvider(ABC):
    name: str = ""

    @abstractmethod
    def create_checkout(
        self, charge, *, success_url: str, cancel_url: str, customer_email: str = "", expires_at=None
    ) -> Checkout:
        ...

    @abstractmethod
    def parse_webhook(self, payload: bytes, headers) -> PaymentEvent | None:
        """Verifiera och tolka en webhook. None = händelse vi inte bryr oss om."""

    @abstractmethod
    def refund(self, charge) -> None:
        ...

    def expire_checkout(self, charge) -> None:
        """Stäng en öppen betalsession (frivilligt)."""
