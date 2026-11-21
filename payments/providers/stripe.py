"""Stripe Checkout (kort, Apple Pay, Google Pay).

Kräver STRIPE_SECRET_KEY och STRIPE_WEBHOOK_SECRET i miljön. Webhook-URL att
registrera i Stripe: https://<domän>/betalning/webhook/
Händelser: checkout.session.completed, checkout.session.expired.
"""

import time

import stripe
from django.conf import settings

from .base import Checkout, PaymentError, PaymentEvent, PaymentProvider


class StripeProvider(PaymentProvider):
    name = "stripe"

    def __init__(self):
        if not settings.STRIPE_SECRET_KEY:
            raise PaymentError("STRIPE_SECRET_KEY saknas")
        self.client = stripe.StripeClient(settings.STRIPE_SECRET_KEY)

    def create_checkout(self, charge, *, success_url, cancel_url, customer_email=""):
        params = {
            "mode": "payment",
            "line_items": [
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": "sek",
                        "unit_amount": charge.amount_ore,
                        "product_data": {"name": charge.description},
                    },
                }
            ],
            "client_reference_id": str(charge.pk),
            "metadata": {"charge_id": str(charge.pk)},
            "success_url": success_url,
            "cancel_url": cancel_url,
            # Stripe kräver minst 30 minuter; samma tid som bokningen hålls.
            "expires_at": int(time.time()) + max(30, settings.PAYMENT_HOLD_MINUTES) * 60,
            "locale": "sv",
        }
        if customer_email:
            params["customer_email"] = customer_email
        try:
            session = self.client.checkout.sessions.create(params=params)
        except stripe.StripeError as e:
            raise PaymentError(str(e)) from e
        return Checkout(ref=session.id, url=session.url)

    def parse_webhook(self, payload, headers):
        try:
            event = stripe.Webhook.construct_event(
                payload, headers.get("Stripe-Signature", ""), settings.STRIPE_WEBHOOK_SECRET
            )
        except (ValueError, stripe.SignatureVerificationError) as e:
            raise PaymentError(f"Ogiltig webhook: {e}") from e
        obj = event["data"]["object"]
        charge_id = (obj.get("metadata") or {}).get("charge_id")
        if not charge_id:
            return None
        if event["type"] == "checkout.session.completed" and obj.get("payment_status") == "paid":
            return PaymentEvent(int(charge_id), paid=True, payment_ref=obj.get("payment_intent") or "")
        if event["type"] == "checkout.session.expired":
            return PaymentEvent(int(charge_id), paid=False)
        return None

    def refund(self, charge):
        if not charge.provider_ref:
            raise PaymentError("Betalningen saknar referens för återbetalning")
        try:
            self.client.refunds.create(params={"payment_intent": charge.provider_ref})
        except stripe.StripeError as e:
            raise PaymentError(str(e)) from e

    def expire_checkout(self, charge):
        if charge.checkout_ref:
            try:
                self.client.checkout.sessions.expire(charge.checkout_ref)
            except stripe.StripeError:
                pass  # redan betald/utgången; webhooken avgör
