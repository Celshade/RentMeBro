"""Stripe PaymentIntent creation, webhook handling, and BTC payments."""

import logging
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import ROUND_HALF_UP, Decimal

import requests
import stripe
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from billing.models import Invoice, InvoiceLineItem
from billing.services import InvoiceLockedError
from payments.models import InvoiceSettlement

stripe.api_key = settings.STRIPE_SECRET_KEY

logger = logging.getLogger(__name__)

BTC_WATCH_WINDOW = timedelta(minutes=15)
BTC_GRACE_PERIOD = timedelta(minutes=3)
CARD_ROUND_WINDOW = timedelta(minutes=15)
BTC_PRICE_CACHE_KEY = "btc_usd_price"
BTC_PRICE_CACHE_TTL = timedelta(minutes=5).seconds
SATS_PER_BTC = 100_000_000

# PaymentIntent statuses that can't back a new Elements confirmation;
# Stripe rejects Elements.create() with a client_secret pointing at
# one of these ("terminal state" error).
_TERMINAL_INTENT_STATUSES = frozenset({'succeeded', 'canceled'})

# Statuses that mean "the renter has actually started paying" -- see
# `Invoice.card_round_is_live`. A PaymentIntent merely sitting at
# requires_payment_method blocks nothing.
_CARD_IN_FLIGHT_STATUSES = frozenset({'processing', 'requires_action'})

# Statuses `create_payment_intent_for_invoice`'s reuse branch may
# safely re-price a stale intent for; anything else (e.g. `processing`)
# is real money in flight and must be left alone.
_REPRICEABLE_INTENT_STATUSES = frozenset(
    {'requires_payment_method', 'requires_confirmation'}
)


class LandlordNotOnboardedError(Exception):
    """The invoice's landlord hasn't finished Stripe Connect setup."""


class InvoiceAlreadyPaidError(Exception):
    """The invoice's PaymentIntent already succeeded on Stripe."""


class BtcNotEnabledError(Exception):
    """The invoice's landlord hasn't enabled BTC payments."""


class BtcLineItemError(Exception):
    """The line item BTC was scoped to isn't valid for this invoice."""


class NothingLeftToChargeError(Exception):
    """Every unpaid item is locked to BTC; the card leg owes nothing."""


class PaymentLockError(Exception):
    """A payment-method lock can't be set as requested."""


class CardCancelNotAllowedError(Exception):
    """The renter's in-flight card payment can't be cancelled."""


class BtcWatchCancelError(Exception):
    """The renter's live BTC quote can't be cancelled."""


class InvalidManualRailError(Exception):
    """The requested rail isn't a valid manual payment method."""


class ManualSettlementError(Exception):
    """The line item is already settled or has a payment in flight."""


def resolve_settled_status(invoice: Invoice) -> str:
    """Works out an invoice's status from its settlements so far.

    A BTC shortfall is the separate UNDERPAID status and outranks
    everything else, since it needs chasing rather than more payments
    landing normally. Otherwise the invoice is PAID once every line
    item has a settlement covering it, and PARTIAL while any remain
    unpaid. A zero-line-item invoice is vacuously PAID.

    Args:
        invoice: The invoice to resolve. Its settlements should
            already reflect the round that just landed.

    Returns:
        The status the invoice should now hold.
    """
    if invoice.remainder_owed_usd and invoice.remainder_owed_usd > 0:
        return Invoice.Status.UNDERPAID
    if invoice.is_fully_paid:
        return Invoice.Status.PAID
    return Invoice.Status.PARTIAL


def _excluded_txids(invoice: Invoice) -> set[str]:
    """txids the tx-matching state machine must never re-match.

    Settled and credited (shortfall) txids across every past BTC
    round, plus the invoice's current credited txid. Without this, a
    second BTC round on a reused address could cross-match a
    transaction that already paid an earlier round. The watch's time
    bound is still the primary defence; this is belt-and-braces for
    clock skew and the deliberately backward-looking grace window.
    """
    excluded = {invoice.btc_credited_txid}
    for settlement in invoice.settlements.filter(
        rail=InvoiceSettlement.Rail.BTC
    ):
        excluded.add(settlement.txid)
        excluded.add(settlement.credited_txid)
    excluded.discard('')
    return excluded


def _settle_btc_leg(
    invoice: Invoice, confirmed: bool, paid_sats: int | None = None
) -> None:
    """Records the BTC leg's outcome and re-resolves the invoice status.

    An unconfirmed tx leaves the invoice PENDING no matter how the
    card leg stands: the money is visible in the mempool but not
    final, so nothing has settled yet.

    A confirmed tx creates one `InvoiceSettlement` row for the round
    (keyed on (invoice, txid), so a concurrent poll confirming the
    same tx twice collapses onto one row) covering whatever
    `btc_round_line_items` was snapshotted to at quote time, then
    resets the in-flight fields so a second BTC round becomes
    representable. `btc_settled_at` is restamped on every settle --
    it means "the most recent BTC round settled," not "the first."

    Args:
        invoice: The invoice whose BTC tx was just matched. Its
            `btc_txid` should already be set on the instance.
        confirmed: Whether the matched tx has a confirmation yet.
        paid_sats: What the matched tx actually paid, if it may exceed
            the quote. Callers pass None for an exact match, since by
            definition it paid no more than quoted. Re-passed on every
            poll of an already-settled tx (a still-PARTIAL invoice
            keeps polling for its other leg), so the overpaid
            email is gated on `created`, not on this being set.
    """
    if not confirmed:
        invoice.status = Invoice.Status.PENDING
        invoice.save(update_fields=["status", "btc_txid"])
        return

    txid = invoice.btc_txid
    amount_sats = invoice.btc_amount_sats
    # Falls back to the current scope if the round was never snapshotted
    # (e.g. a pre-snapshot invoice, or a test driving the tx-matching
    # state machine directly without going through initiate_btc_watch).
    covered_items = (
        list(invoice.btc_round_line_items.all())
        or invoice.btc_scope_line_items
    )

    overpaid_usd = None
    quoted_usd = None
    received_usd = None
    if paid_sats is not None and amount_sats and paid_sats > amount_sats:
        price = get_btc_usd_price()
        if price is not None:
            quoted_usd = _sats_to_usd(amount_sats, price)
            received_usd = _sats_to_usd(paid_sats, price)
            overpaid_usd = received_usd - quoted_usd

    with transaction.atomic():
        settlement, created = InvoiceSettlement.objects.get_or_create(
            invoice=invoice,
            rail=InvoiceSettlement.Rail.BTC,
            txid=txid,
            defaults={
                "amount_usd": sum(
                    (item.amount for item in covered_items), Decimal(0)
                ),
                "amount_sats": amount_sats,
                "credited_txid": invoice.btc_credited_txid,
                "credited_usd": invoice.btc_credited_usd,
                "overpaid_usd": overpaid_usd,
                "settled_at": timezone.now(),
            },
        )
        if created:
            settlement.line_items.set(covered_items)

        invoice.btc_amount_sats = None
        invoice.btc_txid = ""
        invoice.btc_watch_expires_at = None
        invoice.remainder_owed_usd = None
        invoice.btc_credited_txid = ""
        invoice.btc_credited_usd = None
        invoice.btc_settled_at = timezone.now()
        invoice.btc_round_line_items.clear()
        invoice._prefetched_objects_cache = {}
        invoice.status = resolve_settled_status(invoice)
        invoice.save(
            update_fields=[
                "btc_amount_sats",
                "btc_txid",
                "btc_watch_expires_at",
                "remainder_owed_usd",
                "btc_credited_txid",
                "btc_credited_usd",
                "btc_settled_at",
                "status",
            ]
        )

    if created and overpaid_usd is not None:
        _notify_landlord_discrepancy(
            invoice,
            kind="overpaid",
            quoted_usd=quoted_usd,
            received_usd=received_usd,
        )


_MANUAL_RAILS = frozenset({
    InvoiceSettlement.Rail.CASH,
    InvoiceSettlement.Rail.CHECK,
    InvoiceSettlement.Rail.OTHER,
})


def mark_line_item_paid_manually(
    invoice: Invoice, line_item_id: int, rail: str, note: str = ''
) -> Invoice:
    """Records a landlord-attested payment taken outside either rail.

    Creates one `InvoiceSettlement` covering just this item and
    re-resolves the invoice status exactly like `_settle_btc_leg` --
    `paid_line_item_ids` is derived purely from settlements, so the
    item becomes paid/frozen through the existing model with no
    special-casing.

    Args:
        invoice: The invoice the line item belongs to.
        line_item_id: The line item being marked paid.
        rail: 'cash', 'check', or 'other'.
        note: An optional free-text note (e.g. a check number).

    Returns:
        The updated invoice.

    Raises:
        InvalidManualRailError: The rail isn't a manual one.
        BtcLineItemError: The line item isn't part of this invoice.
        ManualSettlementError: The item is already paid or has a
            payment in flight.
    """
    if rail not in _MANUAL_RAILS:
        raise InvalidManualRailError(f"'{rail}' isn't a manual payment rail.")
    line_item = invoice.line_items.filter(id=line_item_id).first()
    if line_item is None:
        raise BtcLineItemError(
            f"Line item {line_item_id} isn't part of this invoice."
        )
    if line_item.id in invoice.frozen_line_item_ids:
        raise ManualSettlementError(
            f"Line item {line_item_id} is already settled or has a "
            "payment in flight and can't be marked paid manually."
        )

    with transaction.atomic():
        settlement = InvoiceSettlement.objects.create(
            invoice=invoice,
            rail=rail,
            amount_usd=line_item.amount,
            note=note,
            settled_at=timezone.now(),
        )
        settlement.line_items.set([line_item])
        invoice._prefetched_objects_cache = {}
        invoice.status = resolve_settled_status(invoice)
        invoice.save(update_fields=["status"])
    return invoice


def _card_round_expiry(payment_intent: dict, now: datetime) -> datetime:
    """Works out when the renter's current card action window lapses.

    Reads the Cash App QR's true expiry off the PaymentIntent's
    `next_action` -- readable only once the intent reaches
    `requires_action` -- and falls back to `now + CARD_ROUND_WINDOW`
    when it's absent, unparseable, or already past. Returning the
    fallback in the already-past case (rather than the stale
    timestamp itself) gives natural backoff: at most one Stripe call
    per invoice per window, instead of a poll on every single retrieve.

    Args:
        payment_intent: The Stripe PaymentIntent payload (a dict, not
            a Stripe object).
        now: The current time, so callers share one clock reading.

    Returns:
        The expiry to store on `stripe_round_expires_at`.
    """
    next_action = payment_intent.get('next_action') or {}
    cashapp = next_action.get(
        'cashapp_handle_redirect_or_display_qr_code'
    ) or {}
    qr_code = cashapp.get('qr_code') or {}
    raw = qr_code.get('expires_at')
    if isinstance(raw, int):
        try:
            expiry = datetime.fromtimestamp(raw, tz=dt_timezone.utc)
        except (OverflowError, OSError, ValueError):
            expiry = None
        if expiry is not None and expiry > now:
            return expiry
    return now + CARD_ROUND_WINDOW


def _sync_card_intent_state(
    invoice: Invoice, payment_intent: dict, *, clear_round: bool = False
) -> None:
    """The single writer for `stripe_intent_status` and
    `stripe_round_expires_at`, so the webhook handlers, the `/pay/`
    reuse branch, and the poll can't drift on how an expiry is
    derived.

    Args:
        invoice: The invoice to update in place.
        payment_intent: The Stripe PaymentIntent payload (a dict, not
            a Stripe object -- callers pass `.to_dict()`).
        clear_round: Also empty `stripe_round_line_items`. Only ever
            set once Stripe has confirmed a terminal cancel, never
            speculatively.
    """
    intent_status = payment_intent.get('status', '')
    invoice.stripe_intent_status = intent_status
    if intent_status in _CARD_IN_FLIGHT_STATUSES:
        invoice.stripe_round_expires_at = _card_round_expiry(
            payment_intent, timezone.now()
        )
    else:
        invoice.stripe_round_expires_at = None
    invoice.save(
        update_fields=['stripe_intent_status', 'stripe_round_expires_at']
    )
    if clear_round:
        invoice.stripe_round_line_items.clear()


def create_payment_intent_for_invoice(
    invoice: Invoice, pay_full: bool = False,
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

    An intent still open for confirmation (`requires_payment_method`
    or `requires_confirmation`) is re-priced in place if the billed
    amount has since changed -- a settled BTC round or a switched
    `pay_full` choice -- since Stripe Elements is already showing the
    renter this intent's client_secret. An intent past that point
    (`processing`) is real money in flight and is never touched.

    Bills `stripe_portion_usd` by default -- the expected card
    portion, which excludes whatever's scoped to BTC -- or
    `card_full_owed_usd` when `pay_full` is set, letting the renter
    pay everything still card-payable in one charge regardless of the
    landlord's BTC expectation. Either way, only a `payment_lock='btc'`
    item is ever excluded outright.

    Args:
        invoice: The invoice to create a PaymentIntent for.
        pay_full: Bill `card_full_owed_usd` instead of
            `stripe_portion_usd`.

    Returns:
        The Stripe PaymentIntent (existing, if one was already created
        and still usable).

    Raises:
        LandlordNotOnboardedError: The landlord hasn't completed
            Stripe Connect onboarding yet.
        InvoiceAlreadyPaidError: The invoice's prior PaymentIntent
            already succeeded; the invoice has now been reconciled.
        NothingLeftToChargeError: Every unpaid item is locked to BTC,
            so the card leg has nothing left to bill.
    """
    landlord = invoice.billing_period.landlord
    if not landlord.stripe_charges_enabled:
        raise LandlordNotOnboardedError(
            "Landlord hasn't finished payment setup yet."
        )

    billed_items = (
        invoice.card_full_line_items
        if pay_full
        else invoice.stripe_scope_line_items
    )
    amount_usd = (
        invoice.card_full_owed_usd if pay_full else invoice.stripe_portion_usd
    )
    amount_cents = int(amount_usd * 100)

    idempotency_key = f'invoice-{invoice.id}-intent'
    if invoice.stripe_payment_intent_id:
        intent = stripe.PaymentIntent.retrieve(
            invoice.stripe_payment_intent_id,
            stripe_account=landlord.stripe_account_id,
        )
        if intent.status not in _TERMINAL_INTENT_STATUSES:
            if intent.status in _REPRICEABLE_INTENT_STATUSES:
                if intent.amount != amount_cents:
                    intent = stripe.PaymentIntent.modify(
                        intent.id,
                        amount=amount_cents,
                        stripe_account=landlord.stripe_account_id,
                    )
                # Re-set even when the amount is unchanged -- a
                # landlord re-scope that leaves the total the same
                # (swapping a payment_lock, moving an item between
                # rails) must not leave this snapshot stale.
                invoice.stripe_round_line_items.set(billed_items)
            else:
                logger.warning(
                    "Invoice %s has a %s PaymentIntent; leaving it alone.",
                    invoice.id, intent.status,
                )
            _sync_card_intent_state(invoice, intent.to_dict())
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

    if amount_cents <= 0:
        raise NothingLeftToChargeError(
            'The landlord has set this invoice to be paid in BTC.'
        )
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
    invoice.stripe_round_line_items.set(billed_items)
    _sync_card_intent_state(invoice, intent.to_dict())
    return intent


def handle_payment_intent_succeeded(
    payment_intent: dict, connected_account_id: str | None = None
) -> None:
    """Settles the card leg of the invoice a succeeded PaymentIntent
    refers to.

    Creates one `InvoiceSettlement` row for the round (keyed on
    (invoice, stripe_payment_intent_id), so Stripe's at-least-once
    webhook redelivery can't create a second row), covering whichever
    items `stripe_round_line_items` was snapshotted to when the intent
    was created -- falling back to `stripe_scope_line_items` for an
    intent created before this snapshot existed. Settling only means
    PAID once every line item has a settlement; on a split invoice it
    means PARTIAL until the BTC side lands too.

    Standard Connect accounts are landlord-owned, so a landlord has
    real API access to their own account and could otherwise submit a
    PaymentIntent with a forged metadata.invoice_id pointing at an
    invoice that isn't theirs. Requiring the event's connected account
    to match the invoice's actual landlord closes that off.

    Args:
        payment_intent: The Stripe PaymentIntent event payload; its
            metadata.invoice_id links it back to our Invoice. Falls
            back to invoice.stripe_payment_intent_id if 'id' is
            missing (many tests omit it).
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

    with transaction.atomic():
        billed_items = list(invoice.stripe_round_line_items.all())
        if not billed_items:
            billed_items = invoice.stripe_scope_line_items
        intent_id = payment_intent.get('id') or invoice.stripe_payment_intent_id

        settlement, created = InvoiceSettlement.objects.get_or_create(
            invoice=invoice,
            rail=InvoiceSettlement.Rail.CARD,
            stripe_payment_intent_id=intent_id,
            defaults={
                "amount_usd": sum(
                    (item.amount for item in billed_items), Decimal(0)
                ),
                "settled_at": timezone.now(),
            },
        )
        if created:
            settlement.line_items.set(billed_items)

        if invoice.stripe_settled_at is None:
            invoice.stripe_settled_at = timezone.now()
        invoice.stripe_intent_status = 'succeeded'
        invoice.stripe_round_expires_at = None
        invoice.stripe_round_line_items.clear()
        invoice._prefetched_objects_cache = {}
        invoice.status = resolve_settled_status(invoice)
        invoice.save(
            update_fields=[
                "status", "stripe_settled_at", "stripe_intent_status",
                "stripe_round_expires_at",
            ]
        )


def handle_payment_intent_state_change(
    payment_intent: dict, connected_account_id: str | None = None
) -> None:
    """Syncs an invoice's card round to a non-`succeeded` PaymentIntent
    event: `requires_action`, `processing`, `payment_failed`, or
    `canceled`.

    Mirrors `handle_payment_intent_succeeded`'s invoice lookup and
    ownership check, plus one extra guard: the event's `id` must match
    the invoice's *current* intent, so a superseded intent's late
    `canceled` can't clobber a live round started since.

    Args:
        payment_intent: The Stripe PaymentIntent event payload.
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
    if payment_intent.get('id') != invoice.stripe_payment_intent_id:
        return
    _sync_card_intent_state(
        invoice, payment_intent,
        clear_round=payment_intent.get('status') == 'canceled',
    )


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


def refresh_payment_state(invoice: Invoice) -> Invoice:
    """Polls any in-flight payment round so a freeze check sees current
    state, not a stale page load.

    Closes the window where a renter's payment has already landed
    on-chain or on Stripe but the landlord's page hasn't noticed yet --
    without this, a landlord could edit a line item a payment is
    actually already covering. Called by every landlord mutation that
    touches a line item before it evaluates `frozen_line_item_ids`.

    Args:
        invoice: The invoice to refresh.

    Returns:
        The refreshed invoice.
    """
    if invoice.btc_txid:
        invoice = check_btc_payment(invoice)
    elif (
        invoice.btc_amount_sats
        and invoice.btc_watch_expires_at is not None
        and timezone.now() > invoice.btc_watch_expires_at
    ):
        invoice = _reconcile_lapsed_watch(invoice, timezone.now())

    return refresh_card_payment_state(invoice)


def refresh_card_payment_state(invoice: Invoice) -> Invoice:
    """Polls Stripe for an in-flight card round's current status.

    Narrow and card-only, unlike `refresh_payment_state`: it never
    touches the BTC side or calls `_reconcile_lapsed_watch`. That's
    what lets it double as the read-path self-heal in
    `InvoiceViewSet.retrieve` (`billing/views.py`), which must not
    trigger a BTC watch reconciliation -- that belongs to the renter
    explicitly restarting a watch, not to a landlord (or renter)
    merely opening a page.

    Args:
        invoice: The invoice to refresh. No-op if there's no
            in-flight card round.

    Returns:
        The refreshed invoice.
    """
    if (
        not invoice.stripe_payment_intent_id
        or invoice.stripe_intent_status in _TERMINAL_INTENT_STATUSES
    ):
        return invoice
    landlord = invoice.billing_period.landlord
    try:
        intent = stripe.PaymentIntent.retrieve(
            invoice.stripe_payment_intent_id,
            stripe_account=landlord.stripe_account_id,
        )
    except stripe.StripeError:
        logger.warning(
            "Stripe retrieve failed refreshing invoice %s",
            invoice.id,
            exc_info=True,
        )
        return invoice
    if intent.status == 'succeeded':
        handle_payment_intent_succeeded(
            intent.to_dict(), connected_account_id=landlord.stripe_account_id,
        )
        invoice.refresh_from_db()
    elif intent.status != invoice.stripe_intent_status:
        _sync_card_intent_state(invoice, intent.to_dict())
    return invoice


# PaymentIntent statuses Stripe will actually let us cancel a Cash App
# Pay intent from. `processing` is excluded -- Cash App Pay doesn't
# support cancelling a push payment already in flight.
_CANCELABLE_INTENT_STATUSES = frozenset(
    {'requires_payment_method', 'requires_confirmation', 'requires_action'}
)


def cancel_card_payment_attempt(invoice: Invoice) -> Invoice:
    """Calls off the renter's in-flight Cash App attempt at their own
    request.

    Retrieves the intent fresh before cancelling so a payment that
    actually succeeded moments ago settles inline instead of surfacing
    a confusing Stripe error, and so a payment that has moved to
    `processing` is reported as uncancellable rather than attempted.

    Args:
        invoice: The invoice whose card round should be cancelled.

    Returns:
        The refreshed invoice, with the round cleared.

    Raises:
        CardCancelNotAllowedError: There's nothing to cancel, the
            round already succeeded, is `processing`, or Stripe
            refuses the cancel outright (e.g. a race where the renter
            approved between our retrieve and our cancel).
    """
    if not invoice.stripe_payment_intent_id:
        raise CardCancelNotAllowedError('There is no payment to cancel.')
    landlord = invoice.billing_period.landlord
    intent = stripe.PaymentIntent.retrieve(
        invoice.stripe_payment_intent_id,
        stripe_account=landlord.stripe_account_id,
    )
    if intent.status == 'succeeded':
        handle_payment_intent_succeeded(
            intent.to_dict(), connected_account_id=landlord.stripe_account_id,
        )
        raise CardCancelNotAllowedError(
            'This payment already went through and can\'t be cancelled.'
        )
    if intent.status not in _CANCELABLE_INTENT_STATUSES:
        _sync_card_intent_state(invoice, intent.to_dict())
        raise CardCancelNotAllowedError(
            'This payment is already going through and can\'t be'
            ' called off.'
        )
    try:
        intent = stripe.PaymentIntent.cancel(
            invoice.stripe_payment_intent_id,
            stripe_account=landlord.stripe_account_id,
        )
    except stripe.InvalidRequestError as exc:
        raise CardCancelNotAllowedError(
            'This payment could not be cancelled.'
        ) from exc
    _sync_card_intent_state(invoice, intent.to_dict(), clear_round=True)
    return invoice


def set_line_item_payment_lock(
    invoice: Invoice, line_item_id: int, lock: str
) -> Invoice:
    """Sets (or clears, via '') a line item's payment-method lock.

    The one and only way a rail may be taken off a charge -- an
    explicit landlord action. Locking to 'card' also drops the item
    from `invoice.btc_line_items`, since leaving it there would show
    the item as BTC-assigned while no rail is actually free to bill it
    in BTC. Locking to 'btc' is the mirror: it adds the item to
    `invoice.btc_line_items`, since locking a charge to BTC-only
    implies BTC should quote it.

    Args:
        invoice: The invoice the line item belongs to.
        line_item_id: The line item to lock.
        lock: '' (either rail), 'btc', or 'card'.

    Returns:
        The updated invoice.

    Raises:
        BtcLineItemError: If the line item doesn't belong to this
            invoice.
        PaymentLockError: If the item is frozen, or 'btc' is requested
            with no BTC address attached.
    """
    invoice = refresh_payment_state(invoice)
    line_item = invoice.line_items.filter(id=line_item_id).first()
    if line_item is None:
        raise BtcLineItemError(
            f"Line item {line_item_id} isn't part of this invoice."
        )
    if line_item.id in invoice.frozen_line_item_ids:
        raise PaymentLockError(
            f"Line item {line_item_id} is already settled or has a "
            "payment in flight and can no longer be re-locked."
        )
    if lock == InvoiceLineItem.Lock.BTC and not invoice.btc_address:
        raise PaymentLockError(
            "Attach a BTC address before locking a charge to BTC."
        )
    line_item.payment_lock = lock
    line_item.save(update_fields=["payment_lock"])
    if lock == InvoiceLineItem.Lock.CARD:
        invoice.btc_line_items.remove(line_item)
    elif lock == InvoiceLineItem.Lock.BTC:
        invoice.btc_line_items.add(line_item)
    return invoice


def attach_btc_payment(
    invoice: Invoice, address: str, line_item_ids: list[int] | None = None
) -> Invoice:
    """Attaches a BTC address to an invoice as a payment option.

    The amount the renter must send is no longer fixed here — it's
    generated and rate-locked from the current market price at the
    moment the renter actually starts paying (`initiate_btc_watch`),
    not chosen by the landlord up front.

    Optionally scopes BTC to a subset of the line items, so a landlord
    can take (say) gas in BTC and leave rent on card, or take both in
    BTC. Scoping to every line item is allowed too. This assignment is
    binding -- an empty scope means no BTC quote at all -- but it
    never by itself removes the card leg's ability to bill an item;
    only an explicit `payment_lock` does that.

    A line item already paid, or with a payment in flight on either
    rail, can't have its BTC scope touched -- see
    `Invoice.frozen_line_item_ids`. The one exception is a BTC round
    that came up short: those items fall back to open so the landlord
    can legitimately re-scope or re-address them.

    Args:
        invoice: The invoice to attach a BTC address to.
        address: The landlord's BTC address to display to the renter.
            A blank address detaches BTC entirely, which also clears
            any line items marked as BTC-billed.
        line_item_ids: The line items BTC should cover, or None/empty
            for none marked yet. Passing None clears any existing
            scope.

    Returns:
        The updated invoice.

    Raises:
        InvoiceLockedError: If the invoice is fully paid or void.
        BtcNotEnabledError: If the landlord hasn't enabled BTC
            payments.
        BtcLineItemError: If a line item doesn't belong to this
            invoice, if the requested change would touch a frozen
            item, or if detaching would strip a paid/locked item's
            only payment option.
    """
    invoice = refresh_payment_state(invoice)

    if invoice.status in (Invoice.Status.PAID, Invoice.Status.VOID):
        raise InvoiceLockedError(
            f"Invoice {invoice.id} is {invoice.status} and can no longer "
            "be edited."
        )
    landlord = invoice.billing_period.landlord
    if not landlord.btc_payments_enabled:
        raise BtcNotEnabledError(
            "Landlord hasn't enabled BTC payments yet."
        )

    item_ids = list(line_item_ids or [])
    if item_ids:
        # Scoped to the invoice's own line items, so a landlord can't
        # point BTC at a charge on someone else's invoice.
        owned_ids = set(
            invoice.line_items.filter(id__in=item_ids).values_list(
                "id", flat=True
            )
        )
        stray_ids = [id_ for id_ in item_ids if id_ not in owned_ids]
        if stray_ids:
            raise BtcLineItemError(
                f"Line item {stray_ids[0]} isn't part of this invoice."
            )
        card_locked_ids = set(
            invoice.line_items.filter(
                id__in=item_ids, payment_lock=InvoiceLineItem.Lock.CARD
            ).values_list("id", flat=True)
        )
        if card_locked_ids:
            raise BtcLineItemError(
                f"Line item {sorted(card_locked_ids)[0]} is locked to "
                "card only and can't be scoped to BTC."
            )

    if address:
        # A charge locked to BTC-only has no card fallback, so dropping
        # it from scope while the address stays attached would strand
        # it with no rail able to bill it -- mirrors the address='0'
        # detach guard below, but for a single item leaving scope.
        btc_locked_ids = set(
            invoice.line_items.filter(
                payment_lock=InvoiceLineItem.Lock.BTC
            ).values_list("id", flat=True)
        )
        unscoped_locked_ids = btc_locked_ids - set(item_ids)
        if unscoped_locked_ids:
            raise BtcLineItemError(
                f"Line item {sorted(unscoped_locked_ids)[0]} is locked "
                "to BTC only and can't be unassigned from BTC scope."
            )

    current_ids = set(
        invoice.btc_line_items.values_list("id", flat=True)
    )
    requested_ids = set(item_ids) if address else set()
    touched = current_ids ^ requested_ids
    frozen_touched = touched & invoice.frozen_line_item_ids
    if frozen_touched:
        raise BtcLineItemError(
            f"Line item {sorted(frozen_touched)[0]} is already settled "
            "or has a payment in flight; its BTC scope can't change "
            "until that resolves."
        )

    # A blank address detaches BTC outright, so nothing can be left
    # marked as BTC-billed against a payment option that's gone. But a
    # settled BTC payment can never be un-happened, and an item locked
    # to BTC would be stranded with no rail able to pay it.
    if not address:
        has_btc_settlement = invoice.settlements.filter(
            rail=InvoiceSettlement.Rail.BTC
        ).exists()
        btc_locked = invoice.line_items.filter(
            payment_lock=InvoiceLineItem.Lock.BTC
        ).exists()
        if has_btc_settlement or btc_locked:
            raise BtcLineItemError(
                "BTC can't be detached: a payment has already settled "
                "in BTC, or a charge is locked to BTC only."
            )
        item_ids = []

    invoice.btc_address = address
    invoice.save(update_fields=["btc_address"])
    invoice.btc_line_items.set(item_ids)
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
    """The USD still owed via BTC: the BTC portion, or whatever's left
    after a prior underpayment was credited toward it.

    Keys off `remainder_owed_usd` rather than status, so a split
    invoice whose card leg settled first (PARTIAL, no remainder) still
    quotes its full BTC portion rather than an empty one.
    """
    if invoice.remainder_owed_usd is not None:
        return invoice.remainder_owed_usd
    return invoice.btc_portion_usd


def _notify_landlord_discrepancy(
    invoice: Invoice, *, kind: str, quoted_usd: Decimal, received_usd: Decimal
) -> None:
    """Emails the landlord that a BTC payment didn't land on-quote.

    Reuses the plain-text `send_mail` pattern from
    `LeaseRentRevision._notify_renter` (`billing/models.py`) rather
    than adding templating for a rare event. Wrapped so a dead SMTP
    host (the default `EMAIL_BACKEND` is the console backend) can
    never lose an already-settled/credited payment -- callers must
    gate on the unset->set transition themselves so this fires once
    per discrepancy, not once per 60s poll.

    Args:
        invoice: The invoice the discrepancy was just recorded on.
        kind: 'overpaid' or 'underpaid'.
        quoted_usd: What the renter was quoted.
        received_usd: What actually arrived.
    """
    renter = invoice.billing_period.renter
    landlord = invoice.billing_period.landlord
    difference = abs(received_usd - quoted_usd)
    txid = invoice.btc_txid or invoice.btc_credited_txid
    try:
        send_mail(
            subject=f'BTC {kind} payment on invoice #{invoice.id}',
            message=(
                f'{renter.email} paid ${received_usd} in BTC toward '
                f'invoice #{invoice.id}, quoted at ${quoted_usd} '
                f'(${difference} {kind}).\nTransaction: {txid}'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[landlord.email],
        )
    except Exception:
        logger.warning(
            "Failed to email landlord about BTC %s on invoice %s",
            kind,
            invoice.id,
            exc_info=True,
        )


def _fetch_address_txs(
    address: str, *, mempool_only: bool = False
) -> list[dict] | None:
    """Fetches an address's transactions from mempool.space.

    `mempool_only` selects `/txs/mempool` (unconfirmed only) over
    `/txs` (up to 50 mempool + the first 25 confirmed, newest first).
    The live 60s poll uses `mempool_only=True` so historical confirmed
    txs are never even received -- the address-reuse cross-match bug
    this guards against is enforced by the API response shape itself,
    not by our own filtering. `_reconcile_lapsed_watch` deliberately
    looks backwards at a window that already closed, so it keeps using
    the full `/txs` endpoint.

    Returns:
        The parsed tx list, or None if the request failed (logged).
    """
    base_url = settings.MEMPOOL_API_BASE_URL
    path = "txs/mempool" if mempool_only else "txs"
    try:
        response = requests.get(
            f"{base_url}/address/{address}/{path}", timeout=5
        )
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


def _watch_started_at(invoice: Invoice) -> datetime:
    """The moment the invoice's current (or just-lapsed) watch window
    began.

    Derived rather than stored as its own field, since
    `initiate_btc_watch` already sets `btc_watch_expires_at = start +
    BTC_WATCH_WINDOW`. Valid on the lapsed path too, since
    `_reconcile_lapsed_watch` runs before that field is cleared.
    """
    return invoice.btc_watch_expires_at - BTC_WATCH_WINDOW


def _first_seen_at(txids: list[str]) -> dict[str, int]:
    """Maps unconfirmed txids to when mempool.space first observed them.

    The only way to time-bound an unconfirmed tx -- it carries no
    `block_time`. A request failure is swallowed (logged); callers
    treat a missing entry as "not in window," failing closed rather
    than letting an unbounded tx through.

    Args:
        txids: The txids to look up.

    Returns:
        txid -> first-seen epoch seconds. Missing/unmined/unknown
        entries are simply absent rather than mapped to 0.
    """
    base_url = settings.MEMPOOL_API_BASE_URL
    try:
        response = requests.get(
            f"{base_url}/v1/transaction-times",
            params=[("txId[]", txid) for txid in txids],
            timeout=5,
        )
        response.raise_for_status()
        times = response.json()
    except requests.RequestException:
        logger.warning("mempool.space transaction-times request failed")
        return {}
    return dict(zip(txids, times))


def _first_seen_for_candidates(
    txs: list[dict], address: str
) -> dict[str, int]:
    """First-seen timestamps for the unconfirmed txs worth time-checking.

    Skips the `_first_seen_at` request entirely when nothing paid the
    address anything at all -- the common "no payment yet" poll -- and
    again for any tx that's already confirmed, since those carry their
    own `block_time` and never need this lookup.
    """
    unconfirmed_txids = [
        tx["txid"]
        for tx in txs
        if _paid_sats(tx, address) > 0
        and not tx.get("status", {}).get("confirmed", False)
    ]
    if not unconfirmed_txids:
        return {}
    return _first_seen_at(unconfirmed_txids)


def _is_in_window(
    tx: dict, started_at: datetime, first_seen: dict[str, int]
) -> bool:
    """Whether `tx` could belong to the watch window starting at
    `started_at`.

    Confirmed txs are checked against their block time; unconfirmed
    ones carry no `block_time` key at all, so they're checked against
    when mempool.space first observed them instead -- never the other
    way around.

    Args:
        tx: A transaction from mempool.space.
        started_at: The earliest moment a tx may belong to this watch.
        first_seen: txid -> first-seen epoch seconds, from
            `_first_seen_at`. A tx missing from this map (lookup
            failed, or mined/unknown) fails closed as not in window.
    """
    tx_status = tx.get("status", {})
    if tx_status.get("confirmed", False):
        return tx_status.get("block_time", 0) >= started_at.timestamp()
    return first_seen.get(tx["txid"], 0) >= started_at.timestamp()


def _find_matching_output(
    txs: list[dict],
    address: str,
    amount_sats: int,
    started_at: datetime,
    first_seen: dict[str, int],
) -> dict | None:
    """Finds the first in-window tx paying `address` exactly `amount_sats`.

    Exact rather than `>=` so a reused address's unrelated history
    can't cross-match a rate-locked quote the way `20,997 >= 10,192`
    once did; time-bounded so nothing that predates the renter
    starting this watch can match at all, regardless of amount.
    """
    for tx in txs:
        if _paid_sats(tx, address) != amount_sats:
            continue
        if _is_in_window(tx, started_at, first_seen):
            return tx
    return None


def _find_largest_output(
    txs: list[dict],
    address: str,
    started_at: datetime,
    first_seen: dict[str, int],
) -> dict | None:
    """Finds the in-window tx paying `address` the most, if anything did.

    Used once no exact match is found, so the caller can classify the
    result as an overpayment (settle, flag the excess) or a shortfall
    (credit toward the invoice) instead of discarding a close-but-not-
    exact payment outright.
    """
    best: dict | None = None
    best_sats = 0
    for tx in txs:
        if not _is_in_window(tx, started_at, first_seen):
            continue
        paid_sats = _paid_sats(tx, address)
        if paid_sats > 0 and paid_sats > best_sats:
            best_sats = paid_sats
            best = {
                "txid": tx["txid"],
                "paid_sats": paid_sats,
                "confirmed": tx.get("status", {}).get("confirmed", False),
            }
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
    remainder (`Invoice.Status.UNDERPAID`) rather than silently
    replaced.
    The credited tx is excluded from all future matching (see
    `_excluded_txids`) so it can't also satisfy the smaller remainder
    quote generated next.

    Args:
        invoice: The invoice whose watch window just lapsed.
        now: The current time (passed in so callers share one clock
            reading across this reconciliation).

    Returns:
        The updated invoice. If a full, overpaid, or grace-period
        match was found, its status is now PENDING/PAID/PARTIAL.
        Otherwise, unchanged (no on-chain payment at all) or
        UNDERPAID (a shortfall was credited).
    """
    if not invoice.btc_amount_sats:
        return invoice

    txs = _fetch_address_txs(invoice.btc_address)
    if txs is None:
        return invoice
    excluded = _excluded_txids(invoice)
    txs = [t for t in txs if t.get("txid") not in excluded]

    started_at = _watch_started_at(invoice)
    first_seen = _first_seen_for_candidates(txs, invoice.btc_address)
    amount_sats = invoice.btc_amount_sats

    if now <= invoice.btc_watch_expires_at + BTC_GRACE_PERIOD:
        exact = _find_matching_output(
            txs, invoice.btc_address, amount_sats, started_at, first_seen
        )
        if exact is not None:
            invoice.btc_txid = exact["txid"]
            _settle_btc_leg(
                invoice, exact.get("status", {}).get("confirmed", False)
            )
            return invoice

    best = _find_largest_output(
        txs, invoice.btc_address, started_at, first_seen
    )
    if best is None:
        return invoice

    if best["paid_sats"] > amount_sats:
        invoice.btc_txid = best["txid"]
        _settle_btc_leg(
            invoice, best["confirmed"], paid_sats=best["paid_sats"]
        )
        return invoice

    price = get_btc_usd_price()
    if price is None:
        return invoice

    credited_usd = _sats_to_usd(best["paid_sats"], price)
    usd_owed = _invoice_usd_owed(invoice)
    invoice.status = Invoice.Status.UNDERPAID
    invoice.remainder_owed_usd = max(usd_owed - credited_usd, Decimal("0"))
    invoice.btc_credited_txid = best["txid"]
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
    quoted_usd = _sats_to_usd(amount_sats, price)
    _notify_landlord_discrepancy(
        invoice,
        kind="underpaid",
        quoted_usd=quoted_usd,
        received_usd=credited_usd,
    )
    return invoice


def initiate_btc_watch(invoice: Invoice, pay_full: bool = False) -> Invoice:
    """Starts (or restarts) the 15-minute window for an initial BTC tx.

    Called when the renter opens the "Pay with BTC" panel. A no-op if
    the current quote is still live. Restarting (the prior window has
    lapsed) first reconciles that lapsed window (see
    `_reconcile_lapsed_watch`) before generating a fresh amount from
    the current market price — against the invoice's BTC portion, or
    against whatever remainder is still owed if a prior underpayment
    left the invoice UNDERPAID. The BTC-owed check (rather than a
    settled-at check) is what lets a second BTC round quote the
    invoice's remaining unpaid items once the first round has settled
    -- the renter simply reopens the panel and restarts the watch.

    DRAFT counts as payable here: nothing in the product promotes an
    invoice out of DRAFT, renters see drafts on their dashboard, and
    the Stripe path bills them without checking status. Excluding DRAFT
    would leave BTC as the one method that silently refuses every
    normally-generated invoice.

    Args:
        invoice: The invoice being watched. Must be DRAFT, SENT,
            PARTIAL or UNDERPAID, with a BTC address already attached
            and something still owed via BTC.
        pay_full: Quote `btc_full_owed_usd` instead of the BTC-scoped
            amount, letting the renter pay everything still
            BTC-payable in one round regardless of the landlord's BTC
            expectation -- mirrors `create_payment_intent_for_invoice`
            on the card side.

    Returns:
        The updated invoice. If reconciling a lapsed window resolved
        it (PENDING/PAID) or logged a new shortfall (UNDERPAID with no
        price data available), no new quote is generated.
    """
    if invoice.status not in (
        Invoice.Status.DRAFT,
        Invoice.Status.SENT,
        Invoice.Status.PARTIAL,
        Invoice.Status.UNDERPAID,
    ):
        return invoice
    if invoice.btc_txid:
        return invoice
    usd_owed = invoice.btc_full_owed_usd if pay_full else _invoice_usd_owed(
        invoice
    )
    if usd_owed <= 0:
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
        usd_owed = (
            invoice.btc_full_owed_usd if pay_full else _invoice_usd_owed(invoice)
        )
        if usd_owed <= 0:
            return invoice

    price = get_btc_usd_price()
    if price is None:
        return invoice

    invoice.btc_amount_sats = _usd_to_sats(usd_owed, price)
    invoice.btc_watch_expires_at = now + BTC_WATCH_WINDOW
    invoice.save(update_fields=["btc_amount_sats", "btc_watch_expires_at"])
    billed_items = (
        invoice.btc_full_line_items if pay_full else invoice.btc_scope_line_items
    )
    invoice.btc_round_line_items.set(billed_items)
    return invoice


def cancel_btc_watch(invoice: Invoice) -> Invoice:
    """Calls off the renter's live BTC quote at their own request.

    Clears the quote outright rather than reconciling it -- nothing
    was received, so there's no shortfall to log, and leaving
    `btc_watch_expires_at` as `None` correctly routes a later
    `initiate_btc_watch` down its no-prior-window path. Any credit
    from an earlier settled round (`remainder_owed_usd`) is untouched.

    Args:
        invoice: The invoice whose live quote should be cancelled.

    Returns:
        The updated invoice, with the round cleared.

    Raises:
        BtcWatchCancelError: A tx has already been seen for this
            watch; a broadcast payment can't be cancelled.
    """
    if invoice.btc_txid:
        raise BtcWatchCancelError(
            "A payment has already been seen for this quote and can't"
            " be cancelled."
        )
    invoice.btc_amount_sats = None
    invoice.btc_watch_expires_at = None
    invoice.save(update_fields=["btc_amount_sats", "btc_watch_expires_at"])
    invoice.btc_round_line_items.clear()
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
            restarting, not here). A second BTC round likewise
            requires the renter to restart a watch after the first
            settles, since settling clears `btc_txid`.

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
            # The full tx, not just /status: re-deriving paid_sats on
            # every poll (not only the first match) is what lets an
            # already-flagged overpayment survive the still-PARTIAL
            # split-invoice case, where this branch is re-entered every
            # 60s until the card leg lands too.
            response = requests.get(
                f"{base_url}/tx/{invoice.btc_txid}", timeout=5
            )
            response.raise_for_status()
            tx = response.json()
            if tx.get("status", {}).get("confirmed", False):
                paid_sats = _paid_sats(tx, invoice.btc_address)
                _settle_btc_leg(invoice, True, paid_sats=paid_sats)
            return invoice

        txs = _fetch_address_txs(invoice.btc_address, mempool_only=True)
        if txs is None:
            return invoice
        excluded = _excluded_txids(invoice)
        txs = [t for t in txs if t.get("txid") not in excluded]
        started_at = _watch_started_at(invoice)
        first_seen = _first_seen_for_candidates(txs, invoice.btc_address)
        match = _find_matching_output(
            txs,
            invoice.btc_address,
            invoice.btc_amount_sats,
            started_at,
            first_seen,
        )
        paid_sats = None
        if match is None:
            best = _find_largest_output(
                txs, invoice.btc_address, started_at, first_seen
            )
            if best is not None and best["paid_sats"] > invoice.btc_amount_sats:
                match = {
                    "txid": best["txid"],
                    "status": {"confirmed": best["confirmed"]},
                }
                paid_sats = best["paid_sats"]
    except requests.RequestException:
        logger.warning(
            "mempool.space request failed for invoice %s", invoice.id
        )
        return invoice

    if match is None:
        return invoice

    invoice.btc_txid = match["txid"]
    _settle_btc_leg(
        invoice,
        match.get("status", {}).get("confirmed", False),
        paid_sats=paid_sats,
    )
    return invoice
