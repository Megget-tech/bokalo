"""Fejkad betaltjänst för utveckling och tester. "Betalsidan" ligger i appen själv
(/betalning/fejk/<id>/) så att hela flödet kan provas utan Stripe-konto."""

import json

from django.urls import reverse

from .base import Checkout, PaymentEvent, PaymentProvider


class FakePaymentProvider(PaymentProvider):
    name = "fake"
    refunds: list = []

    def create_checkout(self, charge, *, success_url, cancel_url, customer_email="", expires_at=None):
        return Checkout(ref=f"fake_cs_{charge.pk}", url=reverse("payments:fake_checkout", args=[charge.pk]))

    def parse_webhook(self, payload, headers):
        data = json.loads(payload)
        return PaymentEvent(
            int(data["charge_id"]), paid=data["paid"], payment_ref=data.get("ref", ""),
            checkout_ref=data.get("checkout_ref", ""),
        )

    def refund(self, charge):
        FakePaymentProvider.refunds.append(charge.pk)
