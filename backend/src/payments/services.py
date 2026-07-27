"""Stripe PaymentIntent creation and webhook event handling."""

import stripe
from django.conf import settings

from accounts.models import User
from billing.models import Invoice

stripe.api_key = settings.STRIPE_SECRET_KEY


class LandlordNotOnboardedError(Exception):
    """The invoice's landlord hasn't finished Stripe Connect setup."""


def create_payment_intent_for_invoice(
    invoice: Invoice,
) -> stripe.PaymentIntent:
    """Creates (or reuses) a Stripe PaymentIntent for an invoice.

    Cash App Pay is enabled as a payment method so the renter can pay
    with Cash App. The PaymentIntent is created directly on the
    landlord's connected Stripe Standard account (a "direct charge"),
    so funds settle straight to the landlord rather than passing
    through the platform's own balance.

    Args:
        invoice: The invoice to create a PaymentIntent for.

    Returns:
        The Stripe PaymentIntent (existing, if one was already created).

    Raises:
        LandlordNotOnboardedError: The landlord hasn't completed
            Stripe Connect onboarding yet.
    """
    landlord = invoice.billing_period.landlord
    if not landlord.stripe_charges_enabled:
        raise LandlordNotOnboardedError(
            "Landlord hasn't finished payment setup yet."
        )

    if invoice.stripe_payment_intent_id:
        return stripe.PaymentIntent.retrieve(
            invoice.stripe_payment_intent_id,
            stripe_account=landlord.stripe_account_id,
        )

    amount_cents = int(invoice.total * 100)
    intent = stripe.PaymentIntent.create(
        amount=amount_cents,
        currency='usd',
        payment_method_types=['cashapp'],
        metadata={'invoice_id': str(invoice.id)},
        stripe_account=landlord.stripe_account_id,
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


def start_connect_onboarding(landlord: User) -> str:
    """Creates (if needed) the landlord's connected account and returns
    a one-time Stripe-hosted onboarding URL.

    Args:
        landlord: The landlord to onboard.

    Returns:
        The onboarding URL to redirect the landlord to.
    """
    if not landlord.stripe_account_id:
        account = stripe.Account.create(type='standard')
        landlord.stripe_account_id = account.id
        landlord.save(update_fields=['stripe_account_id'])

    account_link = stripe.AccountLink.create(
        account=landlord.stripe_account_id,
        type='account_onboarding',
        refresh_url=f'{settings.FRONTEND_URL}/landlord/stripe/refresh',
        return_url=f'{settings.FRONTEND_URL}/landlord/stripe/return',
    )
    return account_link.url


def handle_account_updated(account: dict) -> None:
    """Syncs a connected account's charges_enabled flag to its landlord.

    Args:
        account: The Stripe Account event payload for a connected
            account (event['data']['object']).
    """
    User.objects.filter(stripe_account_id=account.get('id')).update(
        stripe_charges_enabled=bool(account.get('charges_enabled'))
    )
