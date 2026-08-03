"""Stripe PaymentIntent creation, webhook handling, and BTC payments."""

import logging
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import requests
import stripe
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from accounts.models import User
from billing.models import Invoice
from billing.services import InvoiceLockedError

stripe.api_key = settings.STRIPE_SECRET_KEY

logger = logging.getLogger(__name__)

BTC_WATCH_WINDOW = timedelta(minutes=15)
BTC_GRACE_PERIOD = timedelta(minutes=3)
BTC_PRICE_CACHE_KEY = "btc_usd_price"
BTC_PRICE_CACHE_TTL = timedelta(minutes=5).seconds
SATS_PER_BTC = 100_000_000


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


def attach_btc_payment(invoice: Invoice, address: str) -> Invoice:
    """Attaches a BTC address to an invoice as a payment option.

    The amount the renter must send is no longer fixed here — it's
    generated and rate-locked from the current market price at the
    moment the renter actually starts paying (`initiate_btc_watch`),
    not chosen by the landlord up front.

    Args:
        invoice: The invoice to attach a BTC address to.
        address: The landlord's BTC address to display to the renter.

    Returns:
        The updated invoice.

    Raises:
        InvoiceLockedError: If the invoice is pending a BTC payment,
            has an outstanding BTC remainder, paid, or void.
        BtcNotEnabledError: If the landlord hasn't enabled BTC
            payments.
    """
    if invoice.status in (
        Invoice.Status.PENDING,
        Invoice.Status.PARTIAL,
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
    invoice.save(update_fields=["btc_address"])
    return invoice


def _usd_to_sats(usd: Decimal, usd_per_btc: int) -> int:
    """Converts a USD amount to satoshis at a given BTC/USD price."""
    btc = usd / Decimal(usd_per_btc)
    return int(
        (btc * SATS_PER_BTC).to_integral_value(rounding=ROUND_HALF_UP)
    )


def _sats_to_usd(sats: int, usd_per_btc: int) -> Decimal:
    """Converts a satoshi amount to USD at a given BTC/USD price."""
    btc = Decimal(sats) / SATS_PER_BTC
    return (btc * usd_per_btc).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def get_btc_usd_price() -> int | None:
    """Returns the current BTC/USD price, cached for a few minutes.

    Used both for the landlord's informational estimate on the invoice
    draft page and to generate the renter's rate-locked payment amount
    in `initiate_btc_watch`, so a slightly stale price is fine and
    saves hitting mempool.space's rate-limited price endpoint on every
    request.

    Returns:
        The USD price of 1 BTC, or None if mempool.space is unreachable
        and no cached price is available yet.
    """
    cached = cache.get(BTC_PRICE_CACHE_KEY)
    if cached is not None:
        return cached

    base_url = settings.MEMPOOL_API_BASE_URL
    try:
        response = requests.get(f"{base_url}/v1/prices", timeout=5)
        response.raise_for_status()
        price = response.json().get("USD")
    except requests.RequestException:
        logger.warning("mempool.space price request failed")
        return None

    if price is None:
        return None
    cache.set(BTC_PRICE_CACHE_KEY, price, BTC_PRICE_CACHE_TTL)
    return price


def _invoice_usd_owed(invoice: Invoice) -> Decimal:
    """The USD amount still owed via BTC: the full total, or whatever's
    left after a prior underpayment was credited toward it."""
    if invoice.status == Invoice.Status.PARTIAL:
        return invoice.remainder_owed_usd
    return invoice.total


def _fetch_address_txs(address: str) -> list[dict] | None:
    """Fetches an address's transactions from mempool.space.

    Returns:
        The parsed tx list, or None if the request failed (logged).
    """
    base_url = settings.MEMPOOL_API_BASE_URL
    try:
        response = requests.get(f"{base_url}/address/{address}/txs", timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        logger.warning("mempool.space request failed for address %s", address)
        return None


def _paid_sats(tx: dict, address: str) -> int:
    """Sums a single tx's outputs paying `address`."""
    return sum(
        vout["value"]
        for vout in tx.get("vout", [])
        if vout.get("scriptpubkey_address") == address
    )


def _find_matching_output(
    txs: list[dict], address: str, amount_sats: int
) -> dict | None:
    """Finds the first tx paying `address` at least `amount_sats`."""
    for tx in txs:
        if _paid_sats(tx, address) >= amount_sats:
            return tx
    return None


def _find_largest_output(txs: list[dict], address: str) -> dict | None:
    """Finds the tx paying `address` the most, if anything paid it at all.

    Used once a watch window has fully lapsed with no full match, to
    detect a genuine underpayment worth crediting toward the invoice
    rather than silently discarding.
    """
    best: dict | None = None
    best_sats = 0
    for tx in txs:
        paid_sats = _paid_sats(tx, address)
        if paid_sats > 0 and paid_sats > best_sats:
            best_sats = paid_sats
            best = {"txid": tx["txid"], "paid_sats": paid_sats}
    return best


def _reconcile_lapsed_watch(invoice: Invoice, now) -> Invoice:
    """Takes one last look at a just-lapsed watch window before its quote
    is replaced.

    Honors the about-to-be-discarded amount for `BTC_GRACE_PERIOD` past
    its expiry, so a tx broadcast right at the edge (seen by mempool.space
    moments after the renter's browser stopped polling) still resolves
    normally instead of getting orphaned by a fresh, different quote.

    If nothing satisfies that (grace-period) amount but something short
    of it was sent, that's a genuine shortfall rather than a timing
    race: it's credited toward the invoice as a fixed, logged USD
    remainder (`Invoice.Status.PARTIAL`) rather than silently replaced.
    The credited tx is excluded from all future matching so it can't
    also satisfy the smaller remainder quote generated next.

    Args:
        invoice: The invoice whose watch window just lapsed.
        now: The current time (passed in so callers share one clock
            reading across this reconciliation).

    Returns:
        The updated invoice. If a full or grace-period match was
        found, its status is now PENDING/PAID. Otherwise, unchanged
        (no on-chain payment at all) or PARTIAL (a shortfall was
        credited).
    """
    txs = _fetch_address_txs(invoice.btc_address)
    if txs is None:
        return invoice
    if invoice.btc_credited_txid:
        txs = [t for t in txs if t.get("txid") != invoice.btc_credited_txid]

    if now <= invoice.btc_watch_expires_at + BTC_GRACE_PERIOD:
        match = _find_matching_output(
            txs, invoice.btc_address, invoice.btc_amount_sats
        )
        if match is not None:
            invoice.btc_txid = match["txid"]
            invoice.status = (
                Invoice.Status.PAID
                if match.get("status", {}).get("confirmed")
                else Invoice.Status.PENDING
            )
            invoice.save(update_fields=["status", "btc_txid"])
            return invoice

    underpayment = _find_largest_output(txs, invoice.btc_address)
    if underpayment is None:
        return invoice

    price = get_btc_usd_price()
    if price is None:
        return invoice

    credited_usd = _sats_to_usd(underpayment["paid_sats"], price)
    usd_owed = _invoice_usd_owed(invoice)
    invoice.status = Invoice.Status.PARTIAL
    invoice.remainder_owed_usd = max(usd_owed - credited_usd, Decimal("0"))
    invoice.btc_credited_txid = underpayment["txid"]
    invoice.btc_credited_usd = credited_usd
    invoice.btc_amount_sats = None
    invoice.btc_watch_expires_at = None
    invoice.save(
        update_fields=[
            "status",
            "remainder_owed_usd",
            "btc_credited_txid",
            "btc_credited_usd",
            "btc_amount_sats",
            "btc_watch_expires_at",
        ]
    )
    return invoice


def initiate_btc_watch(invoice: Invoice) -> Invoice:
    """Starts (or restarts) the 15-minute window for an initial BTC tx.

    Called when the renter opens the "Pay with BTC" panel. A no-op if
    the current quote is still live. Restarting (the prior window has
    lapsed) first reconciles that lapsed window (see
    `_reconcile_lapsed_watch`) before generating a fresh amount from
    the current market price — against the invoice's full total, or
    against whatever remainder is still owed if a prior underpayment
    left the invoice PARTIAL.

    Args:
        invoice: The invoice being watched. Must be SENT or PARTIAL,
            with a BTC address already attached.

    Returns:
        The updated invoice. If reconciling a lapsed window resolved
        it (PENDING/PAID) or logged a new shortfall (PARTIAL with no
        price data available), no new quote is generated.
    """
    if invoice.status not in (Invoice.Status.SENT, Invoice.Status.PARTIAL):
        return invoice
    if invoice.btc_txid:
        return invoice

    now = timezone.now()
    had_live_quote = (
        invoice.btc_watch_expires_at is not None
        and now <= invoice.btc_watch_expires_at
    )
    if had_live_quote:
        return invoice

    if invoice.btc_watch_expires_at is not None:
        invoice = _reconcile_lapsed_watch(invoice, now)
        if invoice.status in (Invoice.Status.PENDING, Invoice.Status.PAID):
            return invoice

    price = get_btc_usd_price()
    if price is None:
        return invoice

    invoice.btc_amount_sats = _usd_to_sats(_invoice_usd_owed(invoice), price)
    invoice.btc_watch_expires_at = now + BTC_WATCH_WINDOW
    invoice.save(update_fields=["btc_amount_sats", "btc_watch_expires_at"])
    return invoice


def check_btc_payment(invoice: Invoice) -> Invoice:
    """Polls mempool.space for an invoice's BTC payment status.

    Called by the renter's 60-second frontend timer while the "Pay
    with BTC" panel is open. A mempool.space hiccup (timeout, non-200,
    connection error) is logged and swallowed rather than raised, so
    it doesn't break the renter's page.

    Args:
        invoice: The invoice to check. No-op if already PAID/VOID, or
            if no tx has been seen yet and the watch window hasn't
            been started (or has lapsed — lapsed-window reconciliation
            happens in `initiate_btc_watch`, triggered by the renter
            restarting, not here).

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

        txs = _fetch_address_txs(invoice.btc_address)
        if txs is None:
            return invoice
        if invoice.btc_credited_txid:
            txs = [
                t for t in txs if t.get("txid") != invoice.btc_credited_txid
            ]
        match = _find_matching_output(
            txs, invoice.btc_address, invoice.btc_amount_sats
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
