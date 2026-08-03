"""Stripe PaymentIntent creation, webhook handling, and BTC payments."""

import logging
from datetime import timedelta

import requests
import stripe
from django.conf import settings
from django.utils import timezone

from accounts.models import User
from billing.models import Invoice
from billing.services import InvoiceLockedError

stripe.api_key = settings.STRIPE_SECRET_KEY

logger = logging.getLogger(__name__)

BTC_WATCH_WINDOW = timedelta(minutes=15)


class LandlordNotOnboardedError(Exception):
    """The invoice's landlord hasn't finished Stripe Connect setup."""


class InvoiceAlreadyPaidError(Exception):
    """The invoice's PaymentIntent already succeeded on Stripe."""


class BtcNotEnabledError(Exception):
    """The invoice's landlord hasn't enabled BTC payments."""


# PaymentIntent statuses that can't back a new Elements confirmation;
# Stripe rejects Elements.create() with a client_secret pointing at
# one of these ("terminal state" error).
_TERMINAL_INTENT_STATUSES = frozenset({'succeeded', 'canceled'})


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

    A previously-created intent can end up in a terminal state without
    invoice.status reflecting it yet: 'canceled' (the renter abandoned
    or failed a prior attempt) or 'succeeded' (the webhook marking the
    invoice paid hasn't landed yet). Reusing a canceled intent would
    permanently strand the renter, since retrieve() alone never mints
    a new one, so a fresh intent is created instead, keyed off the
    stale intent's id so concurrent requests still collapse onto the
    same replacement instead of racing to create two. A succeeded
    intent instead means the invoice just hasn't been reconciled yet,
    so that's done inline rather than making the renter wait on the
    webhook.

    Args:
        invoice: The invoice to create a PaymentIntent for.

    Returns:
        The Stripe PaymentIntent (existing, if one was already created
        and still usable).

    Raises:
        LandlordNotOnboardedError: The landlord hasn't completed
            Stripe Connect onboarding yet.
        InvoiceAlreadyPaidError: The invoice's prior PaymentIntent
            already succeeded; the invoice has now been reconciled.
    """
    landlord = invoice.billing_period.landlord
    if not landlord.stripe_charges_enabled:
        raise LandlordNotOnboardedError(
            "Landlord hasn't finished payment setup yet."
        )

    idempotency_key = f'invoice-{invoice.id}-intent'
    if invoice.stripe_payment_intent_id:
        intent = stripe.PaymentIntent.retrieve(
            invoice.stripe_payment_intent_id,
            stripe_account=landlord.stripe_account_id,
        )
        if intent.status not in _TERMINAL_INTENT_STATUSES:
            return intent
        if intent.status == 'succeeded':
            handle_payment_intent_succeeded(
                intent.to_dict(),
                connected_account_id=landlord.stripe_account_id,
            )
            raise InvoiceAlreadyPaidError(
                'This invoice was already paid.'
            )
        idempotency_key = (
            f'invoice-{invoice.id}-intent-retry-'
            f'{invoice.stripe_payment_intent_id}'
        )

    amount_cents = int(invoice.total * 100)
    intent = stripe.PaymentIntent.create(
        amount=amount_cents,
        currency='usd',
        payment_method_types=['cashapp'],
        metadata={'invoice_id': str(invoice.id)},
        stripe_account=landlord.stripe_account_id,
        idempotency_key=idempotency_key,
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


def enable_btc_payments(landlord: User) -> None:
    """Enables BTC payments for a landlord after they confirm the dialogue.

    Args:
        landlord: The landlord enabling BTC payments.
    """
    landlord.btc_payments_enabled = True
    landlord.btc_terms_accepted_at = timezone.now()
    landlord.save(
        update_fields=["btc_payments_enabled", "btc_terms_accepted_at"]
    )


def attach_btc_payment(
    invoice: Invoice, address: str, amount_sats: int
) -> Invoice:
    """Attaches a fixed BTC address/amount to an invoice as a payment option.

    Args:
        invoice: The invoice to attach BTC payment info to.
        address: The landlord's BTC address to display to the renter.
        amount_sats: The fixed amount, in satoshis, the renter must send.

    Returns:
        The updated invoice.

    Raises:
        InvoiceLockedError: If the invoice is pending a BTC payment,
            paid, or void.
        BtcNotEnabledError: If the landlord hasn't enabled BTC
            payments.
    """
    if invoice.status in (
        Invoice.Status.PENDING,
        Invoice.Status.PAID,
        Invoice.Status.VOID,
    ):
        raise InvoiceLockedError(
            f"Invoice {invoice.id} is {invoice.status} and can no longer "
            "be edited."
        )
    landlord = invoice.billing_period.landlord
    if not landlord.btc_payments_enabled:
        raise BtcNotEnabledError(
            "Landlord hasn't enabled BTC payments yet."
        )

    invoice.btc_address = address
    invoice.btc_amount_sats = amount_sats
    invoice.save(update_fields=["btc_address", "btc_amount_sats"])
    return invoice


def initiate_btc_watch(invoice: Invoice) -> Invoice:
    """Starts (or restarts) the 15-minute window for an initial BTC tx.

    Called when the renter opens the "Pay with BTC" panel. Restartable:
    reopening the panel after the window has lapsed with no tx seen
    starts a fresh 15 minutes. Once a tx has been seen (btc_txid is
    set), the window no longer applies, so this is a no-op.

    Args:
        invoice: The invoice being watched. Must be SENT with a BTC
            address already attached.

    Returns:
        The updated invoice.
    """
    if invoice.status != Invoice.Status.SENT or invoice.btc_txid:
        return invoice

    invoice.btc_watch_expires_at = timezone.now() + BTC_WATCH_WINDOW
    invoice.save(update_fields=["btc_watch_expires_at"])
    return invoice


def _find_matching_output(
    txs: list[dict], address: str, amount_sats: int
) -> dict | None:
    """Finds the first tx paying `address` at least `amount_sats`."""
    for tx in txs:
        paid_sats = sum(
            vout["value"]
            for vout in tx.get("vout", [])
            if vout.get("scriptpubkey_address") == address
        )
        if paid_sats >= amount_sats:
            return tx
    return None


def check_btc_payment(invoice: Invoice) -> Invoice:
    """Polls mempool.space for an invoice's BTC payment status.

    Called by the renter's 60-second frontend timer while the "Pay
    with BTC" panel is open. A mempool.space hiccup (timeout, non-200,
    connection error) is logged and swallowed rather than raised, so
    it doesn't break the renter's page.

    Args:
        invoice: The invoice to check. No-op if already PAID/VOID, or
            if no tx has been seen yet and the watch window hasn't
            been started (or has lapsed).

    Returns:
        The updated invoice.
    """
    if invoice.status in (Invoice.Status.PAID, Invoice.Status.VOID):
        return invoice
    if not invoice.btc_txid and (
        invoice.btc_watch_expires_at is None
        or timezone.now() > invoice.btc_watch_expires_at
    ):
        return invoice

    base_url = settings.MEMPOOL_API_BASE_URL
    try:
        if invoice.btc_txid:
            response = requests.get(
                f"{base_url}/tx/{invoice.btc_txid}/status", timeout=5
            )
            response.raise_for_status()
            confirmed = response.json().get("confirmed", False)
            if confirmed:
                invoice.status = Invoice.Status.PAID
                invoice.save(update_fields=["status"])
            return invoice

        response = requests.get(
            f"{base_url}/address/{invoice.btc_address}/txs", timeout=5
        )
        response.raise_for_status()
        match = _find_matching_output(
            response.json(), invoice.btc_address, invoice.btc_amount_sats
        )
    except requests.RequestException:
        logger.warning(
            "mempool.space request failed for invoice %s", invoice.id
        )
        return invoice

    if match is None:
        return invoice

    invoice.btc_txid = match["txid"]
    invoice.status = (
        Invoice.Status.PAID
        if match.get("status", {}).get("confirmed")
        else Invoice.Status.PENDING
    )
    invoice.save(update_fields=["status", "btc_txid"])
    return invoice
