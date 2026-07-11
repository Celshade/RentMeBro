"""Stripe PaymentIntent creation and webhook event handling."""

import stripe
from django.conf import settings

from billing.models import Invoice

stripe.api_key = settings.STRIPE_SECRET_KEY


def create_payment_intent_for_invoice(
    invoice: Invoice,
) -> stripe.PaymentIntent:
    """Creates (or reuses) a Stripe PaymentIntent for an invoice.

    Cash App Pay is enabled as a payment method so the renter can pay
    with Cash App; funds settle to the landlord's Stripe balance and
    payout to their linked bank account from there.

    Args:
        invoice: The invoice to create a PaymentIntent for.

    Returns:
        The Stripe PaymentIntent (existing, if one was already created).
    """
    if invoice.stripe_payment_intent_id:
        return stripe.PaymentIntent.retrieve(invoice.stripe_payment_intent_id)

    amount_cents = int(invoice.total * 100)
    intent = stripe.PaymentIntent.create(
        amount=amount_cents,
        currency='usd',
        payment_method_types=['cashapp'],
        metadata={'invoice_id': str(invoice.id)},
    )
    invoice.stripe_payment_intent_id = intent.id
    invoice.save(update_fields=['stripe_payment_intent_id'])
    return intent


def handle_payment_intent_succeeded(payment_intent: dict) -> None:
    """Marks the invoice referenced by a succeeded PaymentIntent as paid.

    Args:
        payment_intent: The Stripe PaymentIntent event payload; its
            metadata.invoice_id links it back to our Invoice.
    """
    invoice_id = payment_intent.get('metadata', {}).get('invoice_id')
    if not invoice_id:
        return
    Invoice.objects.filter(id=invoice_id).update(status=Invoice.Status.PAID)
