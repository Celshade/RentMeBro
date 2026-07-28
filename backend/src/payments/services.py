"""Stripe PaymentIntent creation and webhook event handling."""

import logging

import stripe
from django.conf import settings

from accounts.models import User
from billing.models import Invoice

stripe.api_key = settings.STRIPE_SECRET_KEY

logger = logging.getLogger(__name__)


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

    A stable idempotency_key (keyed on the invoice, not per-call) is
    passed to PaymentIntent.create so a retried request (e.g. the
    renter's browser re-firing the pay request before the first
    response lands) can't create a second PaymentIntent for the same
    invoice in the gap between the create() call succeeding and
    invoice.stripe_payment_intent_id being saved.

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
        idempotency_key=f'invoice-{invoice.id}-intent',
    )
    invoice.stripe_payment_intent_id = intent.id
    invoice.save(update_fields=['stripe_payment_intent_id'])
    return intent


def handle_payment_intent_succeeded(
    payment_intent: dict, connected_account_id: str | None = None
) -> None:
    """Marks the invoice referenced by a succeeded PaymentIntent as paid.

    Standard Connect accounts are landlord-owned, so a landlord has
    real API access to their own account and could otherwise submit a
    PaymentIntent with a forged metadata.invoice_id pointing at an
    invoice that isn't theirs. Requiring the event's connected account
    to match the invoice's actual landlord closes that off.

    Stripe webhooks are at-least-once delivery, so this can run twice
    for the same event. That's harmless today only because setting
    status to PAID a second time is a no-op; if this handler grows a
    non-idempotent side effect (an email, a counter increment, etc.),
    add dedup keyed on the Stripe event id before doing so.

    Args:
        payment_intent: The Stripe PaymentIntent event payload; its
            metadata.invoice_id links it back to our Invoice.
        connected_account_id: The connected account the event fired
            on (event['account']), or None for a platform-account
            event.
    """
    invoice_id = payment_intent.get('metadata', {}).get('invoice_id')
    if not invoice_id:
        return
    invoice = (
        Invoice.objects.filter(id=invoice_id)
        .select_related('billing_period__landlord')
        .first()
    )
    if invoice is None:
        return
    landlord = invoice.billing_period.landlord
    if connected_account_id != landlord.stripe_account_id:
        return
    invoice.status = Invoice.Status.PAID
    invoice.save(update_fields=['status'])


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


def refresh_connect_status(landlord: User) -> None:
    """Pulls the landlord's connected account status directly from
    Stripe and syncs it, instead of relying solely on the account.updated
    webhook.

    Used when the landlord lands back on our return URL from Stripe
    Connect onboarding, since webhook delivery can lag behind (or, in
    local dev without `stripe listen` running, never arrive at all).

    Args:
        landlord: The landlord to refresh. No-op if they haven't
            started onboarding yet.
    """
    if not landlord.stripe_account_id:
        return
    account = stripe.Account.retrieve(landlord.stripe_account_id)
    handle_account_updated(account)


def handle_account_updated(account: dict) -> None:
    """Syncs a connected account's charges_enabled flag to its landlord.

    Args:
        account: The Stripe Account event payload for a connected
            account (event['data']['object']).
    """
    try:
        User.objects.filter(stripe_account_id=account['id']).update(
            stripe_charges_enabled=bool(account['charges_enabled'])
        )
    except KeyError:
        logger.warning(
            "account.updated payload missing 'id' or 'charges_enabled': %r",
            account,
        )
