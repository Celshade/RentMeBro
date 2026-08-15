from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
import requests
import stripe
from django.core.cache import cache
from django.utils import timezone

from accounts.tests.factories import LandlordFactory
from billing.models import Invoice, InvoiceLineItem
from billing.services import InvoiceLockedError
from billing.tests.factories import (
    BillingPeriodFactory,
    InvoiceFactory,
    InvoiceLineItemFactory,
)
from payments.services import (
    BTC_PRICE_CACHE_KEY,
    BtcLineItemError,
    BtcNotEnabledError,
    BtcWatchCancelError,
    CARD_ROUND_WINDOW,
    CardCancelNotAllowedError,
    InvalidManualRailError,
    InvoiceAlreadyPaidError,
    LandlordNotOnboardedError,
    ManualSettlementError,
    NothingLeftToChargeError,
    _card_round_expiry,
    _sats_to_usd,
    _usd_to_sats,
    attach_btc_payment,
    cancel_btc_watch,
    cancel_card_payment_attempt,
    check_btc_payment,
    create_payment_intent_for_invoice,
    enable_btc_payments,
    get_btc_usd_price,
    handle_account_updated,
    handle_payment_intent_state_change,
    handle_payment_intent_succeeded,
    initiate_btc_watch,
    mark_line_item_paid_manually,
    refresh_card_payment_state,
    resolve_settled_status,
    start_connect_onboarding,
)

pytestmark = pytest.mark.django_db


def _onboarded_invoice(**kwargs) -> Invoice:
    landlord = LandlordFactory(
        stripe_account_id='acct_landlord', stripe_charges_enabled=True
    )
    billing_period = BillingPeriodFactory(landlord=landlord)
    return InvoiceFactory(billing_period=billing_period, **kwargs)


class TestCreatePaymentIntentForInvoice:
    def test_creates_new_intent_and_persists_id(self, mocker):
        invoice = _onboarded_invoice()
        InvoiceLineItemFactory(invoice=invoice, amount=Decimal('123.45'))
        fake_intent = MagicMock(
            id='pi_new123', client_secret='secret',
            status='requires_payment_method',
        )
        fake_intent.to_dict.return_value = {
            'status': 'requires_payment_method'
        }
        mock_create = mocker.patch(
            'payments.services.stripe.PaymentIntent.create',
            return_value=fake_intent,
        )
        mock_retrieve = mocker.patch(
            'payments.services.stripe.PaymentIntent.retrieve'
        )

        result = create_payment_intent_for_invoice(invoice)

        assert result is fake_intent
        mock_create.assert_called_once_with(
            amount=12345,
            currency='usd',
            payment_method_types=['cashapp'],
            metadata={'invoice_id': str(invoice.id)},
            stripe_account='acct_landlord',
            idempotency_key=f'invoice-{invoice.id}-intent',
        )
        mock_retrieve.assert_not_called()
        invoice.refresh_from_db()
        assert invoice.stripe_payment_intent_id == 'pi_new123'

    def test_charges_only_the_card_portion_of_a_split_invoice(self, mocker):
        """Billing the full total alongside a line-item-scoped BTC
        address would charge the BTC-covered line item twice.
        """
        invoice = _onboarded_invoice()
        InvoiceLineItemFactory(invoice=invoice, amount=Decimal('1000.00'))
        gas = InvoiceLineItemFactory(
            invoice=invoice,
            amount=Decimal('200.00'),
            kind=InvoiceLineItem.Kind.GAS,
        )
        invoice.btc_line_items.set([gas])
        fake_intent = MagicMock(
            id='pi_split', client_secret='secret',
            status='requires_payment_method',
        )
        fake_intent.to_dict.return_value = {
            'status': 'requires_payment_method'
        }
        mock_create = mocker.patch(
            'payments.services.stripe.PaymentIntent.create',
            return_value=fake_intent,
        )

        create_payment_intent_for_invoice(invoice)

        # $1000 of rent, not the $1200 invoice total.
        assert mock_create.call_args.kwargs['amount'] == 100000

    def test_bills_the_full_total_when_btc_covers_every_charge(
        self, mocker
    ):
        """Marking every charge as BTC-billed doesn't take the card
        leg off the table -- either rail can still settle the
        invoice on its own.
        """
        invoice = _onboarded_invoice()
        only_item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal('500.00')
        )
        invoice.btc_line_items.set([only_item])
        fake_intent = MagicMock(
            id='pi_full', client_secret='secret',
            status='requires_payment_method',
        )
        fake_intent.to_dict.return_value = {
            'status': 'requires_payment_method'
        }
        mock_create = mocker.patch(
            'payments.services.stripe.PaymentIntent.create',
            return_value=fake_intent,
        )

        create_payment_intent_for_invoice(invoice)

        assert mock_create.call_args.kwargs['amount'] == 50000

    def test_reuses_existing_intent(self, mocker):
        invoice = _onboarded_invoice(stripe_payment_intent_id='pi_existing')
        # 'processing' is real money in flight, so the reprice branch
        # (which would otherwise call the unmocked .modify) never runs.
        fake_intent = MagicMock(id='pi_existing', status='processing')
        fake_intent.to_dict.return_value = {'status': 'processing'}
        mock_retrieve = mocker.patch(
            'payments.services.stripe.PaymentIntent.retrieve',
            return_value=fake_intent,
        )
        mock_create = mocker.patch(
            'payments.services.stripe.PaymentIntent.create'
        )

        result = create_payment_intent_for_invoice(invoice)

        assert result is fake_intent
        mock_retrieve.assert_called_once_with(
            'pi_existing', stripe_account='acct_landlord'
        )
        mock_create.assert_not_called()

    def test_creates_fresh_intent_when_existing_is_canceled(self, mocker):
        invoice = _onboarded_invoice(stripe_payment_intent_id='pi_stale')
        InvoiceLineItemFactory(invoice=invoice, amount=Decimal('50.00'))
        stale_intent = MagicMock(id='pi_stale', status='canceled')
        fresh_intent = MagicMock(
            id='pi_fresh123', client_secret='secret',
            status='requires_payment_method',
        )
        fresh_intent.to_dict.return_value = {
            'status': 'requires_payment_method'
        }
        mocker.patch(
            'payments.services.stripe.PaymentIntent.retrieve',
            return_value=stale_intent,
        )
        mock_create = mocker.patch(
            'payments.services.stripe.PaymentIntent.create',
            return_value=fresh_intent,
        )

        result = create_payment_intent_for_invoice(invoice)

        assert result is fresh_intent
        mock_create.assert_called_once_with(
            amount=5000,
            currency='usd',
            payment_method_types=['cashapp'],
            metadata={'invoice_id': str(invoice.id)},
            stripe_account='acct_landlord',
            idempotency_key=(
                f'invoice-{invoice.id}-intent-retry-pi_stale'
            ),
        )
        invoice.refresh_from_db()
        assert invoice.stripe_payment_intent_id == 'pi_fresh123'

    def test_raises_and_reconciles_when_existing_already_succeeded(
        self, mocker
    ):
        invoice = _onboarded_invoice(
            stripe_payment_intent_id='pi_done',
            status=Invoice.Status.SENT,
        )
        succeeded_intent = MagicMock(id='pi_done', status='succeeded')
        succeeded_intent.to_dict.return_value = {
            'metadata': {'invoice_id': str(invoice.id)}
        }
        mocker.patch(
            'payments.services.stripe.PaymentIntent.retrieve',
            return_value=succeeded_intent,
        )
        mock_create = mocker.patch(
            'payments.services.stripe.PaymentIntent.create'
        )

        with pytest.raises(InvoiceAlreadyPaidError):
            create_payment_intent_for_invoice(invoice)

        mock_create.assert_not_called()
        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.PAID

    def test_raises_if_landlord_not_onboarded(self, mocker):
        invoice = InvoiceFactory()  # default LandlordFactory: not onboarded
        mock_create = mocker.patch(
            'payments.services.stripe.PaymentIntent.create'
        )

        with pytest.raises(LandlordNotOnboardedError):
            create_payment_intent_for_invoice(invoice)

        mock_create.assert_not_called()


class TestCardRoundExpiry:
    def test_reads_the_nested_qr_code_expiry(self):
        now = timezone.now()
        future = now + timedelta(minutes=10)
        payment_intent = {
            'next_action': {
                'cashapp_handle_redirect_or_display_qr_code': {
                    'qr_code': {'expires_at': int(future.timestamp())}
                }
            }
        }

        expiry = _card_round_expiry(payment_intent, now)

        assert abs((expiry - future).total_seconds()) < 1

    def test_falls_back_when_next_action_is_missing(self):
        now = timezone.now()
        assert _card_round_expiry({}, now) == now + CARD_ROUND_WINDOW

    def test_falls_back_when_cashapp_key_is_missing(self):
        now = timezone.now()
        payment_intent = {'next_action': {}}

        expiry = _card_round_expiry(payment_intent, now)

        assert expiry == now + CARD_ROUND_WINDOW

    def test_falls_back_when_qr_code_is_missing(self):
        now = timezone.now()
        payment_intent = {
            'next_action': {
                'cashapp_handle_redirect_or_display_qr_code': {}
            }
        }

        expiry = _card_round_expiry(payment_intent, now)

        assert expiry == now + CARD_ROUND_WINDOW

    def test_falls_back_when_expires_at_is_not_an_int(self):
        now = timezone.now()
        payment_intent = {
            'next_action': {
                'cashapp_handle_redirect_or_display_qr_code': {
                    'qr_code': {'expires_at': 'soon'}
                }
            }
        }

        expiry = _card_round_expiry(payment_intent, now)

        assert expiry == now + CARD_ROUND_WINDOW

    def test_falls_back_when_expiry_is_already_past(self):
        """Returning the fallback (not the stale timestamp) gives
        natural backoff -- at most one Stripe call per window.
        """
        now = timezone.now()
        past = now - timedelta(minutes=5)
        payment_intent = {
            'next_action': {
                'cashapp_handle_redirect_or_display_qr_code': {
                    'qr_code': {'expires_at': int(past.timestamp())}
                }
            }
        }

        expiry = _card_round_expiry(payment_intent, now)

        assert expiry == now + CARD_ROUND_WINDOW


class TestRefreshCardPaymentState:
    def test_requires_action_with_qr_expiry_writes_both_fields(
        self, mocker
    ):
        invoice = _onboarded_invoice(
            stripe_payment_intent_id='pi_1',
            stripe_intent_status='requires_payment_method',
        )
        future = timezone.now() + timedelta(minutes=12)
        fake_intent = MagicMock(id='pi_1', status='requires_action')
        fake_intent.to_dict.return_value = {
            'status': 'requires_action',
            'next_action': {
                'cashapp_handle_redirect_or_display_qr_code': {
                    'qr_code': {'expires_at': int(future.timestamp())}
                }
            },
        }
        mocker.patch(
            'payments.services.stripe.PaymentIntent.retrieve',
            return_value=fake_intent,
        )

        result = refresh_card_payment_state(invoice)

        assert result.stripe_intent_status == 'requires_action'
        assert abs(
            (result.stripe_round_expires_at - future).total_seconds()
        ) < 1

    def test_requires_payment_method_nulls_the_expiry(self, mocker):
        invoice = _onboarded_invoice(
            stripe_payment_intent_id='pi_1',
            stripe_intent_status='requires_action',
            stripe_round_expires_at=(
                timezone.now() + timedelta(minutes=5)
            ),
        )
        fake_intent = MagicMock(
            id='pi_1', status='requires_payment_method'
        )
        fake_intent.to_dict.return_value = {
            'status': 'requires_payment_method'
        }
        mocker.patch(
            'payments.services.stripe.PaymentIntent.retrieve',
            return_value=fake_intent,
        )

        result = refresh_card_payment_state(invoice)

        assert result.stripe_intent_status == 'requires_payment_method'
        assert result.stripe_round_expires_at is None

    def test_stripe_error_leaves_the_invoice_untouched(self, mocker):
        invoice = _onboarded_invoice(
            stripe_payment_intent_id='pi_1',
            stripe_intent_status='requires_action',
            stripe_round_expires_at=(
                timezone.now() + timedelta(minutes=5)
            ),
        )
        original_expires_at = invoice.stripe_round_expires_at
        mocker.patch(
            'payments.services.stripe.PaymentIntent.retrieve',
            side_effect=stripe.StripeError('boom'),
        )

        result = refresh_card_payment_state(invoice)

        assert result.stripe_intent_status == 'requires_action'
        assert result.stripe_round_expires_at == original_expires_at
        invoice.refresh_from_db()
        assert invoice.stripe_intent_status == 'requires_action'

    def test_noop_with_no_intent_id(self):
        invoice = _onboarded_invoice(stripe_payment_intent_id='')
        assert refresh_card_payment_state(invoice) is invoice

    def test_noop_for_terminal_status(self, mocker):
        invoice = _onboarded_invoice(
            stripe_payment_intent_id='pi_1',
            stripe_intent_status='succeeded',
        )
        mock_retrieve = mocker.patch(
            'payments.services.stripe.PaymentIntent.retrieve'
        )

        refresh_card_payment_state(invoice)

        mock_retrieve.assert_not_called()


class TestCancelCardPaymentAttempt:
    def test_happy_path_cancels_and_unfreezes(self, mocker):
        invoice = _onboarded_invoice(
            stripe_payment_intent_id='pi_1',
            stripe_intent_status='requires_action',
            stripe_round_expires_at=(
                timezone.now() + timedelta(minutes=5)
            ),
        )
        item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal('100.00')
        )
        invoice.stripe_round_line_items.set([item])
        retrieved_intent = MagicMock(
            id='pi_1', status='requires_action'
        )
        mocker.patch(
            'payments.services.stripe.PaymentIntent.retrieve',
            return_value=retrieved_intent,
        )
        canceled_intent = MagicMock(id='pi_1', status='canceled')
        canceled_intent.to_dict.return_value = {'status': 'canceled'}
        mock_cancel = mocker.patch(
            'payments.services.stripe.PaymentIntent.cancel',
            return_value=canceled_intent,
        )

        result = cancel_card_payment_attempt(invoice)

        mock_cancel.assert_called_once_with(
            'pi_1', stripe_account='acct_landlord'
        )
        assert result.stripe_intent_status == 'canceled'
        assert list(result.stripe_round_line_items.all()) == []
        assert item.id not in result.frozen_line_item_ids

    def test_processing_raises_and_never_calls_cancel(self, mocker):
        invoice = _onboarded_invoice(
            stripe_payment_intent_id='pi_1',
            stripe_intent_status='processing',
        )
        retrieved_intent = MagicMock(id='pi_1', status='processing')
        retrieved_intent.to_dict.return_value = {'status': 'processing'}
        mocker.patch(
            'payments.services.stripe.PaymentIntent.retrieve',
            return_value=retrieved_intent,
        )
        mock_cancel = mocker.patch(
            'payments.services.stripe.PaymentIntent.cancel'
        )

        with pytest.raises(CardCancelNotAllowedError):
            cancel_card_payment_attempt(invoice)

        mock_cancel.assert_not_called()

    def test_retrieve_returns_succeeded_settles_inline_and_raises(
        self, mocker
    ):
        invoice = _onboarded_invoice(
            stripe_payment_intent_id='pi_1',
            stripe_intent_status='processing',
            status=Invoice.Status.SENT,
        )
        succeeded_intent = MagicMock(id='pi_1', status='succeeded')
        succeeded_intent.to_dict.return_value = {
            'metadata': {'invoice_id': str(invoice.id)}
        }
        mocker.patch(
            'payments.services.stripe.PaymentIntent.retrieve',
            return_value=succeeded_intent,
        )
        mock_cancel = mocker.patch(
            'payments.services.stripe.PaymentIntent.cancel'
        )

        with pytest.raises(CardCancelNotAllowedError):
            cancel_card_payment_attempt(invoice)

        mock_cancel.assert_not_called()
        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.PAID

    def test_invalid_request_error_maps_to_cancel_not_allowed(
        self, mocker
    ):
        invoice = _onboarded_invoice(
            stripe_payment_intent_id='pi_1',
            stripe_intent_status='requires_action',
        )
        retrieved_intent = MagicMock(
            id='pi_1', status='requires_action'
        )
        mocker.patch(
            'payments.services.stripe.PaymentIntent.retrieve',
            return_value=retrieved_intent,
        )
        mocker.patch(
            'payments.services.stripe.PaymentIntent.cancel',
            side_effect=stripe.InvalidRequestError('raced', None),
        )

        with pytest.raises(CardCancelNotAllowedError):
            cancel_card_payment_attempt(invoice)

    def test_raises_with_no_intent_id(self):
        invoice = _onboarded_invoice(stripe_payment_intent_id='')

        with pytest.raises(CardCancelNotAllowedError):
            cancel_card_payment_attempt(invoice)


class TestHandlePaymentIntentStateChange:
    def test_canceled_clears_the_round_line_items(self):
        invoice = _onboarded_invoice(
            stripe_payment_intent_id='pi_1',
            stripe_intent_status='requires_action',
        )
        item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal('100.00')
        )
        invoice.stripe_round_line_items.set([item])

        handle_payment_intent_state_change(
            {
                'id': 'pi_1',
                'status': 'canceled',
                'metadata': {'invoice_id': str(invoice.id)},
            },
            connected_account_id='acct_landlord',
        )

        invoice.refresh_from_db()
        assert invoice.stripe_intent_status == 'canceled'
        assert list(invoice.stripe_round_line_items.all()) == []

    def test_payment_failed_keeps_the_round_line_items(self):
        """A failed-but-reusable intent is re-priced in place by the
        next /pay/ call -- clearing the snapshot here would let a
        later success settle against a scope re-derived after the
        landlord already re-scoped.
        """
        invoice = _onboarded_invoice(
            stripe_payment_intent_id='pi_1',
            stripe_intent_status='requires_action',
        )
        item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal('100.00')
        )
        invoice.stripe_round_line_items.set([item])

        handle_payment_intent_state_change(
            {
                'id': 'pi_1',
                'status': 'payment_failed',
                'metadata': {'invoice_id': str(invoice.id)},
            },
            connected_account_id='acct_landlord',
        )

        invoice.refresh_from_db()
        assert invoice.stripe_intent_status == 'payment_failed'
        assert {
            i.id for i in invoice.stripe_round_line_items.all()
        } == {item.id}

    def test_wrong_connected_account_is_noop(self):
        invoice = _onboarded_invoice(
            stripe_payment_intent_id='pi_1',
            stripe_intent_status='requires_action',
        )

        handle_payment_intent_state_change(
            {
                'id': 'pi_1',
                'status': 'canceled',
                'metadata': {'invoice_id': str(invoice.id)},
            },
            connected_account_id='acct_someone_else',
        )

        invoice.refresh_from_db()
        assert invoice.stripe_intent_status == 'requires_action'

    def test_superseded_intent_id_is_noop(self):
        invoice = _onboarded_invoice(
            stripe_payment_intent_id='pi_current',
            stripe_intent_status='requires_action',
        )

        handle_payment_intent_state_change(
            {
                'id': 'pi_old',
                'status': 'canceled',
                'metadata': {'invoice_id': str(invoice.id)},
            },
            connected_account_id='acct_landlord',
        )

        invoice.refresh_from_db()
        assert invoice.stripe_intent_status == 'requires_action'


class TestCancelBtcWatch:
    def test_happy_path_clears_the_quote(self):
        invoice = _btc_enabled_invoice(status=Invoice.Status.SENT)
        item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal('200.00')
        )
        invoice.btc_amount_sats = 400000
        invoice.btc_watch_expires_at = (
            timezone.now() + timedelta(minutes=10)
        )
        invoice.remainder_owed_usd = Decimal('5.00')
        invoice.save(
            update_fields=[
                'btc_amount_sats', 'btc_watch_expires_at',
                'remainder_owed_usd',
            ]
        )
        invoice.btc_round_line_items.set([item])

        result = cancel_btc_watch(invoice)

        assert result.btc_amount_sats is None
        assert result.btc_watch_expires_at is None
        assert list(result.btc_round_line_items.all()) == []
        assert result.remainder_owed_usd == Decimal('5.00')

    def test_raises_when_a_tx_has_already_been_seen(self):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT, btc_txid='tx1'
        )

        with pytest.raises(BtcWatchCancelError):
            cancel_btc_watch(invoice)


class TestHandlePaymentIntentSucceeded:
    def test_marks_matching_invoice_paid_when_account_matches(self):
        invoice = _onboarded_invoice(status=Invoice.Status.SENT)

        handle_payment_intent_succeeded(
            {'metadata': {'invoice_id': str(invoice.id)}},
            connected_account_id='acct_landlord',
        )

        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.PAID

    def test_mismatched_connected_account_is_noop(self):
        """A landlord can't mark another landlord's invoice paid by
        forging metadata on a PaymentIntent created on their own
        (Standard, self-owned) connected account.
        """
        invoice = _onboarded_invoice(status=Invoice.Status.SENT)

        handle_payment_intent_succeeded(
            {'metadata': {'invoice_id': str(invoice.id)}},
            connected_account_id='acct_someone_else',
        )

        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.SENT

    def test_missing_metadata_is_noop(self):
        invoice = _onboarded_invoice(status=Invoice.Status.SENT)

        handle_payment_intent_succeeded(
            {}, connected_account_id='acct_landlord'
        )

        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.SENT

    def test_empty_invoice_id_is_noop(self):
        invoice = _onboarded_invoice(status=Invoice.Status.SENT)

        handle_payment_intent_succeeded(
            {'metadata': {'invoice_id': ''}},
            connected_account_id='acct_landlord',
        )

        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.SENT

    def test_nonexistent_invoice_id_is_noop_no_error(self):
        handle_payment_intent_succeeded(
            {'metadata': {'invoice_id': '999999'}},
            connected_account_id='acct_landlord',
        )
        # No exception raised; nothing to assert against.


class TestStartConnectOnboarding:
    def test_creates_account_when_missing_and_returns_link_url(self, mocker):
        landlord = LandlordFactory(stripe_account_id='')
        mock_account_create = mocker.patch(
            'payments.services.stripe.Account.create',
            return_value=MagicMock(id='acct_new123'),
        )
        mock_link_create = mocker.patch(
            'payments.services.stripe.AccountLink.create',
            return_value=MagicMock(url='https://connect.stripe.com/setup/x'),
        )

        url = start_connect_onboarding(landlord)

        assert url == 'https://connect.stripe.com/setup/x'
        mock_account_create.assert_called_once_with(type='standard')
        landlord.refresh_from_db()
        assert landlord.stripe_account_id == 'acct_new123'
        mock_link_create.assert_called_once()
        assert (
            mock_link_create.call_args.kwargs['account'] == 'acct_new123'
        )

    def test_reuses_existing_account(self, mocker):
        landlord = LandlordFactory(stripe_account_id='acct_existing')
        mock_account_create = mocker.patch(
            'payments.services.stripe.Account.create'
        )
        mocker.patch(
            'payments.services.stripe.AccountLink.create',
            return_value=MagicMock(url='https://connect.stripe.com/setup/y'),
        )

        url = start_connect_onboarding(landlord)

        assert url == 'https://connect.stripe.com/setup/y'
        mock_account_create.assert_not_called()


class TestHandleAccountUpdated:
    def test_syncs_charges_enabled_true(self):
        landlord = LandlordFactory(
            stripe_account_id='acct_1', stripe_charges_enabled=False
        )

        handle_account_updated({'id': 'acct_1', 'charges_enabled': True})

        landlord.refresh_from_db()
        assert landlord.stripe_charges_enabled is True

    def test_syncs_charges_enabled_false(self):
        landlord = LandlordFactory(
            stripe_account_id='acct_1', stripe_charges_enabled=True
        )

        handle_account_updated({'id': 'acct_1', 'charges_enabled': False})

        landlord.refresh_from_db()
        assert landlord.stripe_charges_enabled is False

    def test_unknown_account_id_is_noop(self):
        handle_account_updated(
            {'id': 'acct_unknown', 'charges_enabled': True}
        )
        # No exception raised; nothing to assert against.


class TestEnableBtcPayments:
    def test_enables_and_stamps_timestamp(self):
        landlord = LandlordFactory(btc_payments_enabled=False)

        enable_btc_payments(landlord)

        landlord.refresh_from_db()
        assert landlord.btc_payments_enabled is True
        assert landlord.btc_terms_accepted_at is not None


def _btc_enabled_invoice(**kwargs) -> Invoice:
    landlord = LandlordFactory(btc_payments_enabled=True)
    billing_period = BillingPeriodFactory(landlord=landlord)
    return InvoiceFactory(billing_period=billing_period, **kwargs)


def _two_line_item_invoice(**kwargs) -> tuple[Invoice, InvoiceLineItem]:
    """A $1000 rent + $200 gas invoice, returned with its gas line item.

    Gas is the charge these tests scope BTC to, leaving $1000 of rent
    for the card leg.
    """
    invoice = _btc_enabled_invoice(**kwargs)
    InvoiceLineItemFactory(
        invoice=invoice,
        amount=Decimal("1000.00"),
        kind=InvoiceLineItem.Kind.RENT,
    )
    gas = InvoiceLineItemFactory(
        invoice=invoice,
        amount=Decimal("200.00"),
        kind=InvoiceLineItem.Kind.GAS,
    )
    return invoice, gas


def _mock_mempool_requests(
    mocker,
    *,
    address_txs: list[dict] | None = None,
    first_seen: dict[str, int] | None = None,
    tx_detail: dict | None = None,
):
    """Routes `payments.services.requests.get` by mempool.space endpoint.

    Real code hits three differently-shaped endpoints (an address's
    txs, `/v1/transaction-times`, and a single tx by txid), so a
    single blanket `return_value` mock can't serve all of them the way
    it could before the time-bound match landed.
    """
    first_seen = first_seen or {}

    def fake_get(url, *args, **kwargs):
        response = MagicMock()
        if "transaction-times" in url:
            txids = [v for _, v in kwargs.get("params", [])]
            response.json.return_value = [
                first_seen.get(txid, 0) for txid in txids
            ]
        elif "/tx/" in url:
            response.json.return_value = tx_detail
        else:
            response.json.return_value = address_txs or []
        return response

    return mocker.patch(
        "payments.services.requests.get", side_effect=fake_get
    )


class TestAttachBtcPayment:
    def test_attaches_address(self):
        invoice = _btc_enabled_invoice(status=Invoice.Status.SENT)

        result = attach_btc_payment(invoice, "bc1qexample")

        assert result.btc_address == "bc1qexample"
        invoice.refresh_from_db()
        assert invoice.btc_address == "bc1qexample"

    def test_raises_if_landlord_not_enabled(self):
        invoice = InvoiceFactory(status=Invoice.Status.SENT)

        with pytest.raises(BtcNotEnabledError):
            attach_btc_payment(invoice, "bc1qexample")

    @pytest.mark.parametrize(
        "locked_status",
        [Invoice.Status.PAID, Invoice.Status.VOID],
    )
    def test_raises_for_locked_invoice(self, locked_status):
        invoice = _btc_enabled_invoice(status=locked_status)

        with pytest.raises(InvoiceLockedError):
            attach_btc_payment(invoice, "bc1qexample")

    @pytest.mark.parametrize(
        "open_status",
        [
            Invoice.Status.PENDING,
            Invoice.Status.PARTIAL,
            Invoice.Status.UNDERPAID,
        ],
    )
    def test_allows_reassignment_while_in_progress(self, open_status):
        """PARTIAL/UNDERPAID no longer lock the whole invoice -- only a
        settled/void invoice or a frozen line item does.
        """
        invoice = _btc_enabled_invoice(status=open_status)

        result = attach_btc_payment(invoice, "bc1qexample")

        assert result.btc_address == "bc1qexample"

    def test_scopes_btc_to_a_line_item(self):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)

        result = attach_btc_payment(
            invoice, "bc1qexample", line_item_ids=[gas.id]
        )

        assert list(result.btc_line_items.all()) == [gas]
        assert result.btc_portion_usd == Decimal("200.00")
        assert result.stripe_portion_usd == Decimal("1000.00")
        assert result.is_split_payment is True

    def test_scopes_btc_to_every_line_item(self):
        """Assigning both charges is allowed: they aren't exclusive.

        Covering everything is a whole-invoice BTC payment rather
        than a split one, but the card leg still stands ready to
        bill the full total if the renter pays that way instead.
        """
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        rent = invoice.line_items.get(kind=InvoiceLineItem.Kind.RENT)

        result = attach_btc_payment(
            invoice, "bc1qexample", line_item_ids=[gas.id, rent.id]
        )

        assert set(result.btc_line_items.all()) == {gas, rent}
        assert result.btc_portion_usd == Decimal("1200.00")
        assert result.stripe_portion_usd == Decimal("1200.00")
        assert result.is_split_payment is False

    def test_unassigned_scope_quotes_nothing(self):
        """Assignment is binding: attaching an address alone, with no
        line items assigned, must not imply the whole invoice.
        """
        invoice, _ = _two_line_item_invoice(status=Invoice.Status.SENT)

        result = attach_btc_payment(invoice, "bc1qexample")

        assert result.btc_line_items.exists() is False
        assert result.btc_scope_line_items == []
        assert result.btc_portion_usd == Decimal("0.00")
        assert result.is_split_payment is False

    def test_assigning_every_item_covers_the_whole_invoice(self):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        rent = invoice.line_items.get(kind=InvoiceLineItem.Kind.RENT)

        result = attach_btc_payment(
            invoice, "bc1qexample", [rent.id, gas.id]
        )

        assert result.btc_portion_usd == Decimal("1200.00")
        assert result.is_split_payment is False

    def test_reattaching_without_a_line_item_clears_the_scope(self):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        attach_btc_payment(invoice, "bc1qexample", line_item_ids=[gas.id])

        result = attach_btc_payment(invoice, "bc1qexample")

        assert result.btc_line_items.exists() is False

    def test_raises_for_a_line_item_on_another_invoice(self):
        """Scoping is filtered to the invoice's own line items, so a
        landlord can't point BTC at someone else's charge.
        """
        invoice, _ = _two_line_item_invoice(status=Invoice.Status.SENT)
        other_line_item = InvoiceLineItemFactory()

        with pytest.raises(BtcLineItemError):
            attach_btc_payment(
                invoice, "bc1qexample", line_item_ids=[other_line_item.id]
            )

    def test_scopes_btc_to_an_invoice_with_only_one_charge(self):
        """Scoping BTC to an invoice's only line item is just marking
        the whole invoice as BTC-billed -- allowed, not an error.
        """
        invoice = _btc_enabled_invoice(status=Invoice.Status.SENT)
        only_item = InvoiceLineItemFactory(invoice=invoice)

        result = attach_btc_payment(
            invoice, "bc1qexample", line_item_ids=[only_item.id]
        )

        assert list(result.btc_line_items.all()) == [only_item]
        assert result.stripe_portion_usd == only_item.amount
        assert result.is_split_payment is False


class TestSplitPaymentSettlement:
    """A split invoice reaches PAID only once both legs land."""

    def _split_invoice(self) -> Invoice:
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        return attach_btc_payment(
            invoice, "bc1qexample", line_item_ids=[gas.id]
        )

    def test_btc_leg_alone_leaves_invoice_partial(self, mocker):
        invoice = self._split_invoice()
        mocker.patch(
            "payments.services._fetch_address_txs",
            return_value=[{"txid": "abc", "status": {"confirmed": True}}],
        )
        mocker.patch(
            "payments.services._find_matching_output",
            return_value={"txid": "abc", "status": {"confirmed": True}},
        )
        invoice.btc_watch_expires_at = timezone.now() + timedelta(minutes=5)

        result = check_btc_payment(invoice)

        assert result.status == Invoice.Status.PARTIAL
        assert result.btc_settled_at is not None
        assert result.stripe_settled_at is None

    def test_card_leg_alone_leaves_invoice_partial(self):
        invoice = self._split_invoice()
        landlord = invoice.billing_period.landlord

        handle_payment_intent_succeeded(
            {"metadata": {"invoice_id": str(invoice.id)}},
            connected_account_id=landlord.stripe_account_id,
        )

        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.PARTIAL
        assert invoice.stripe_settled_at is not None

    def test_both_legs_settle_the_invoice(self, mocker):
        invoice = self._split_invoice()
        invoice.btc_watch_expires_at = timezone.now() + timedelta(minutes=5)
        mocker.patch(
            "payments.services._fetch_address_txs",
            return_value=[{"txid": "abc", "status": {"confirmed": True}}],
        )
        mocker.patch(
            "payments.services._find_matching_output",
            return_value={"txid": "abc", "status": {"confirmed": True}},
        )
        invoice = check_btc_payment(invoice)
        assert invoice.status == Invoice.Status.PARTIAL
        landlord = invoice.billing_period.landlord

        handle_payment_intent_succeeded(
            {"metadata": {"invoice_id": str(invoice.id)}},
            connected_account_id=landlord.stripe_account_id,
        )

        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.PAID

    def test_unsplit_invoice_still_settles_on_one_leg(self):
        """The card leg covering the whole invoice means PAID outright,
        which is how every pre-split invoice behaves.
        """
        invoice = _btc_enabled_invoice(status=Invoice.Status.SENT)
        InvoiceLineItemFactory(invoice=invoice)
        landlord = invoice.billing_period.landlord

        handle_payment_intent_succeeded(
            {"metadata": {"invoice_id": str(invoice.id)}},
            connected_account_id=landlord.stripe_account_id,
        )

        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.PAID

    def test_underpaying_a_split_invoice_outranks_partial(self):
        """Both statuses apply when a renter underpays one leg of a
        split invoice, and status holds only one value -- being short
        needs chasing, so it wins over a merely-missing second leg.
        """
        invoice = self._split_invoice()
        invoice.stripe_settled_at = timezone.now()
        invoice.remainder_owed_usd = Decimal("40.00")
        invoice.save(
            update_fields=["stripe_settled_at", "remainder_owed_usd"]
        )

        assert resolve_settled_status(invoice) == Invoice.Status.UNDERPAID

    def test_settling_the_btc_leg_clears_a_prior_shortfall(self, mocker):
        """The tx topping up a shortfall settles the leg, so a stale
        remainder mustn't drag the invoice back to UNDERPAID.
        """
        invoice = self._split_invoice()
        landlord = invoice.billing_period.landlord
        handle_payment_intent_succeeded(
            {"metadata": {"invoice_id": str(invoice.id)}},
            connected_account_id=landlord.stripe_account_id,
        )
        invoice.refresh_from_db()
        invoice.remainder_owed_usd = Decimal("40.00")
        invoice.save(update_fields=["remainder_owed_usd"])
        invoice.btc_watch_expires_at = timezone.now() + timedelta(minutes=5)
        mocker.patch(
            "payments.services._fetch_address_txs",
            return_value=[{"txid": "abc", "status": {"confirmed": True}}],
        )
        mocker.patch(
            "payments.services._find_matching_output",
            return_value={"txid": "abc", "status": {"confirmed": True}},
        )

        result = check_btc_payment(invoice)

        assert result.remainder_owed_usd is None
        assert result.status == Invoice.Status.PAID

    def test_watch_quotes_only_the_btc_portion(self, mocker):
        invoice = self._split_invoice()
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )

        result = initiate_btc_watch(invoice)

        # $200 of gas @ $50k/BTC, not the $1200 invoice total.
        assert result.btc_amount_sats == 400000

    def test_second_round_quotes_remaining_items_after_first_settles(
        self, mocker
    ):
        """The BTC-scoped gas item settling doesn't leave the next quote
        empty -- it correctly rolls forward to whatever's still unpaid,
        which is what makes a second BTC round representable at all.
        """
        invoice = self._split_invoice()
        invoice.btc_watch_expires_at = timezone.now() + timedelta(minutes=5)
        mocker.patch(
            "payments.services._fetch_address_txs",
            return_value=[{"txid": "abc", "status": {"confirmed": True}}],
        )
        mocker.patch(
            "payments.services._find_matching_output",
            return_value={"txid": "abc", "status": {"confirmed": True}},
        )
        invoice = check_btc_payment(invoice)
        assert invoice.status == Invoice.Status.PARTIAL
        assert invoice.btc_txid == ""

        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )
        result = initiate_btc_watch(invoice)

        # $1000 of rent remaining, not zero and not the $1200 total.
        assert result.btc_amount_sats == 2000000
        assert result.btc_watch_expires_at is not None


class TestInitiateBtcWatch:
    def test_raises_if_no_btc_address(self):
        invoice = _btc_enabled_invoice(status=Invoice.Status.SENT)
        InvoiceLineItemFactory(invoice=invoice, amount=Decimal("100.00"))

        with pytest.raises(BtcNotEnabledError):
            initiate_btc_watch(invoice)

    def test_raises_if_no_btc_address_even_with_pay_full(self):
        invoice = _btc_enabled_invoice(status=Invoice.Status.SENT)
        InvoiceLineItemFactory(invoice=invoice, amount=Decimal("100.00"))

        with pytest.raises(BtcNotEnabledError):
            initiate_btc_watch(invoice, pay_full=True)

    def test_starts_watch_window_and_generates_amount_for_sent_invoice(
        self, mocker
    ):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT, btc_address="bc1qexample"
        )
        item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("100.00")
        )
        invoice.btc_line_items.set([item])
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )

        result = initiate_btc_watch(invoice)

        assert result.btc_watch_expires_at is not None
        assert result.btc_watch_expires_at > timezone.now()
        assert result.btc_amount_sats == 200000  # $100 @ $50k/BTC

    def test_generates_amount_from_remainder_for_underpaid_invoice(
        self, mocker
    ):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.UNDERPAID,
            btc_address="bc1qexample",
            remainder_owed_usd=Decimal("25.00"),
        )
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )

        result = initiate_btc_watch(invoice)

        assert result.btc_amount_sats == 50000  # $25 @ $50k/BTC

    def test_noop_if_nothing_assigned(self, mocker):
        """An address with no line items assigned quotes $0, so
        opening the BTC panel must not start a watch.
        """
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT, btc_address="bc1qexample"
        )
        InvoiceLineItemFactory(invoice=invoice, amount=Decimal("100.00"))
        get_price = mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )

        result = initiate_btc_watch(invoice)

        assert result.btc_watch_expires_at is None
        assert result.btc_amount_sats is None
        get_price.assert_not_called()

    def test_noop_if_no_price_available(self, mocker):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT, btc_address="bc1qexample"
        )
        InvoiceLineItemFactory(invoice=invoice, amount=Decimal("100.00"))
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=None
        )

        result = initiate_btc_watch(invoice)

        assert result.btc_watch_expires_at is None
        assert result.btc_amount_sats is None

    def test_starts_watch_for_draft_invoice(self, mocker):
        """Nothing promotes an invoice out of DRAFT, so refusing to
        watch one would block BTC on every generated invoice while
        Stripe kept billing them.
        """
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.DRAFT, btc_address="bc1qexample"
        )
        item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("100.00")
        )
        invoice.btc_line_items.set([item])
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )

        result = initiate_btc_watch(invoice)

        assert result.btc_watch_expires_at is not None
        assert result.btc_amount_sats == 200000  # $100 @ $50k/BTC

    def test_pay_full_quotes_everything_when_nothing_assigned(self, mocker):
        """With no BTC assignment, `btc_scope_line_items` is empty and
        the plain watch is a no-op -- `pay_full` must still quote the
        item, since it ignores the landlord's scope entirely.
        """
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT, btc_address="bc1qexample"
        )
        item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("100.00")
        )
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )

        result = initiate_btc_watch(invoice, pay_full=True)

        assert result.btc_watch_expires_at is not None
        assert result.btc_amount_sats == 200000  # $100 @ $50k/BTC
        assert list(result.btc_round_line_items.all()) == [item]

    def test_pay_full_quotes_more_than_the_assigned_scope(self, mocker):
        """A landlord who only assigned one item still lets the renter
        opt in to covering everything BTC-payable in one round.
        """
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT, btc_address="bc1qexample"
        )
        assigned = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("100.00")
        )
        other = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("50.00")
        )
        invoice.btc_line_items.set([assigned])
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )

        result = initiate_btc_watch(invoice, pay_full=True)

        # $150 total, not the $100 assigned scope.
        assert result.btc_amount_sats == 300000
        assert set(result.btc_round_line_items.all()) == {assigned, other}

    @pytest.mark.parametrize(
        "status",
        [Invoice.Status.PENDING, Invoice.Status.PAID, Invoice.Status.VOID],
    )
    def test_noop_if_invoice_is_not_payable(self, status):
        invoice = _btc_enabled_invoice(
            status=status, btc_address="bc1qexample"
        )

        result = initiate_btc_watch(invoice)

        assert result.btc_watch_expires_at is None

    def test_noop_if_tx_already_seen(self):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT,
            btc_address="bc1qexample",
            btc_txid="deadbeef",
        )

        result = initiate_btc_watch(invoice)

        assert result.btc_watch_expires_at is None

    def test_noop_if_current_quote_still_live(self, mocker):
        expires_at = timezone.now() + timedelta(minutes=10)
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
            btc_watch_expires_at=expires_at,
        )
        get_price = mocker.patch("payments.services.get_btc_usd_price")

        result = initiate_btc_watch(invoice)

        assert result.btc_watch_expires_at == expires_at
        assert result.btc_amount_sats == 100000
        get_price.assert_not_called()

    def test_restart_after_lapse_generates_fresh_quote(self, mocker):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
            btc_watch_expires_at=timezone.now()
            - timedelta(minutes=10),
        )
        item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("100.00")
        )
        invoice.btc_line_items.set([item])
        response = MagicMock()
        response.json.return_value = []
        mocker.patch(
            "payments.services.requests.get", return_value=response
        )
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=40000
        )

        result = initiate_btc_watch(invoice)

        assert result.btc_amount_sats == 250000  # $100 @ $40k/BTC
        assert result.btc_watch_expires_at > timezone.now()

    def test_restart_within_grace_honors_prior_amount(self, mocker):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
            btc_watch_expires_at=timezone.now()
            - timedelta(minutes=2),
        )
        item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("40.00")
        )
        invoice.btc_line_items.set([item])
        _mock_mempool_requests(
            mocker,
            address_txs=[
                {
                    "txid": "late-tx",
                    "vout": [
                        {
                            "scriptpubkey_address": "bc1qexample",
                            "value": 100000,
                        }
                    ],
                    "status": {"confirmed": False},
                }
            ],
            first_seen={"late-tx": int(timezone.now().timestamp())},
        )

        result = initiate_btc_watch(invoice)

        assert result.status == Invoice.Status.PENDING
        assert result.btc_txid == "late-tx"

    def test_restart_past_grace_logs_underpayment_as_underpaid(self, mocker):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
            btc_watch_expires_at=timezone.now()
            - timedelta(minutes=10),
        )
        item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("100.00")
        )
        invoice.btc_line_items.set([item])
        _mock_mempool_requests(
            mocker,
            address_txs=[
                {
                    "txid": "short-tx",
                    "vout": [
                        {
                            "scriptpubkey_address": "bc1qexample",
                            "value": 60000,
                        }
                    ],
                    "status": {"confirmed": False},
                }
            ],
            first_seen={"short-tx": int(timezone.now().timestamp())},
        )
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )

        result = initiate_btc_watch(invoice)

        assert result.status == Invoice.Status.UNDERPAID
        assert result.btc_credited_txid == "short-tx"
        assert result.btc_credited_usd == Decimal("30.00")  # 0.0006 @ $50k
        assert result.remainder_owed_usd == Decimal("70.00")
        # Immediately re-quoted against the new, smaller remainder.
        assert result.btc_amount_sats == 140000  # $70 @ $50k/BTC
        assert result.btc_watch_expires_at > timezone.now()

    def test_restart_excludes_already_credited_txid_from_matching(
        self, mocker
    ):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.UNDERPAID,
            btc_address="bc1qexample",
            btc_amount_sats=140000,
            btc_watch_expires_at=timezone.now()
            - timedelta(minutes=10),
            btc_credited_txid="short-tx",
            btc_credited_usd=Decimal("30.00"),
            remainder_owed_usd=Decimal("70.00"),
        )
        response = MagicMock()
        response.json.return_value = [
            {
                "txid": "short-tx",
                "vout": [
                    {
                        "scriptpubkey_address": "bc1qexample",
                        "value": 60000,
                    }
                ],
                "status": {"confirmed": False},
            }
        ]
        mocker.patch(
            "payments.services.requests.get", return_value=response
        )
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )

        result = initiate_btc_watch(invoice)

        # The already-credited tx must not be reused to satisfy (or
        # shrink) the remainder a second time.
        assert result.status == Invoice.Status.UNDERPAID
        assert result.remainder_owed_usd == Decimal("70.00")
        assert result.btc_amount_sats == 140000


class TestMarkLineItemPaidManually:
    def test_marks_item_paid_and_resolves_partial(self):
        invoice = _onboarded_invoice()
        rent = InvoiceLineItemFactory(invoice=invoice, amount=Decimal("100"))
        InvoiceLineItemFactory(invoice=invoice, amount=Decimal("50"))

        result = mark_line_item_paid_manually(invoice, rent.id, "cash")

        assert result.status == Invoice.Status.PARTIAL
        assert rent.id in result.paid_line_item_ids
        settlement = result.settlements.get()
        assert settlement.rail == "cash"
        assert settlement.amount_usd == Decimal("100")
        assert list(settlement.line_items.all()) == [rent]

    def test_marks_last_unpaid_item_paid_and_resolves_paid(self):
        invoice = _onboarded_invoice()
        rent = InvoiceLineItemFactory(invoice=invoice, amount=Decimal("100"))

        result = mark_line_item_paid_manually(
            invoice, rent.id, "check", note="Check #1042"
        )

        assert result.status == Invoice.Status.PAID
        assert result.settlements.get().note == "Check #1042"

    def test_other_rail_is_accepted(self):
        invoice = _onboarded_invoice()
        item = InvoiceLineItemFactory(invoice=invoice, amount=Decimal("10"))

        result = mark_line_item_paid_manually(invoice, item.id, "other")

        assert result.settlements.get().rail == "other"

    def test_rejects_a_non_manual_rail(self):
        invoice = _onboarded_invoice()
        item = InvoiceLineItemFactory(invoice=invoice, amount=Decimal("10"))

        with pytest.raises(InvalidManualRailError):
            mark_line_item_paid_manually(invoice, item.id, "btc")

    def test_rejects_a_line_item_from_another_invoice(self):
        invoice = _onboarded_invoice()
        other_item = InvoiceLineItemFactory(amount=Decimal("10"))

        with pytest.raises(BtcLineItemError):
            mark_line_item_paid_manually(invoice, other_item.id, "cash")

    def test_rejects_an_already_paid_item(self):
        invoice = _onboarded_invoice()
        item = InvoiceLineItemFactory(invoice=invoice, amount=Decimal("10"))
        mark_line_item_paid_manually(invoice, item.id, "cash")

        with pytest.raises(ManualSettlementError):
            mark_line_item_paid_manually(invoice, item.id, "cash")

    def test_rejects_an_item_with_a_payment_in_flight(self):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT, btc_address="bc1qexample"
        )
        item = InvoiceLineItemFactory(invoice=invoice, amount=Decimal("10"))
        invoice.btc_line_items.set([item])
        invoice.btc_watch_expires_at = timezone.now() + timedelta(minutes=5)
        invoice.btc_amount_sats = 20000
        invoice.save()
        invoice.btc_round_line_items.set([item])

        with pytest.raises(ManualSettlementError):
            mark_line_item_paid_manually(invoice, item.id, "cash")

    def test_a_bare_lock_with_no_round_in_flight_does_not_block(self):
        invoice = _onboarded_invoice()
        item = InvoiceLineItemFactory(invoice=invoice, amount=Decimal("10"))
        item.payment_lock = InvoiceLineItem.Lock.BTC
        item.save()

        result = mark_line_item_paid_manually(invoice, item.id, "cash")

        assert item.id in result.paid_line_item_ids


class TestCheckBtcPayment:
    def test_noop_when_paid(self):
        invoice = _btc_enabled_invoice(status=Invoice.Status.PAID)

        result = check_btc_payment(invoice)

        assert result.status == Invoice.Status.PAID

    def test_noop_when_no_txid_and_watch_expired(self):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
            btc_watch_expires_at=timezone.now() - timedelta(minutes=1),
        )

        result = check_btc_payment(invoice)

        assert result.status == Invoice.Status.SENT

    def test_noop_when_no_txid_and_watch_never_started(self):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
        )

        result = check_btc_payment(invoice)

        assert result.status == Invoice.Status.SENT

    def test_unconfirmed_match_sets_pending(self, mocker):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
            btc_watch_expires_at=timezone.now() + timedelta(minutes=10),
        )
        _mock_mempool_requests(
            mocker,
            address_txs=[
                {
                    "txid": "tx1",
                    "vout": [
                        {
                            "scriptpubkey_address": "bc1qexample",
                            "value": 100000,
                        }
                    ],
                    "status": {"confirmed": False},
                }
            ],
            first_seen={"tx1": int(timezone.now().timestamp())},
        )

        result = check_btc_payment(invoice)

        assert result.status == Invoice.Status.PENDING
        assert result.btc_txid == "tx1"

    def test_confirmed_match_sets_paid(self, mocker):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
            btc_watch_expires_at=timezone.now() + timedelta(minutes=10),
        )
        _mock_mempool_requests(
            mocker,
            address_txs=[
                {
                    "txid": "tx1",
                    "vout": [
                        {
                            "scriptpubkey_address": "bc1qexample",
                            "value": 100000,
                        }
                    ],
                    "status": {
                        "confirmed": True,
                        "block_time": int(timezone.now().timestamp()),
                    },
                }
            ],
        )

        result = check_btc_payment(invoice)

        assert result.status == Invoice.Status.PAID
        # A confirmed round clears btc_txid -- the settled txid lives
        # on the InvoiceSettlement row instead.
        assert result.btc_txid == ""
        settlement = result.settlements.get()
        assert settlement.txid == "tx1"

    def test_confirms_via_known_txid(self, mocker):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.PENDING,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
            btc_txid="tx1",
            btc_watch_expires_at=timezone.now() + timedelta(minutes=10),
        )
        _mock_mempool_requests(
            mocker,
            tx_detail={
                "txid": "tx1",
                "vout": [
                    {
                        "scriptpubkey_address": "bc1qexample",
                        "value": 100000,
                    }
                ],
                "status": {"confirmed": True},
            },
        )

        result = check_btc_payment(invoice)

        assert result.status == Invoice.Status.PAID

    def test_no_match_is_noop(self, mocker):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
            btc_watch_expires_at=timezone.now() + timedelta(minutes=10),
        )
        response = MagicMock()
        response.json.return_value = []
        mocker.patch(
            "payments.services.requests.get", return_value=response
        )

        result = check_btc_payment(invoice)

        assert result.status == Invoice.Status.SENT
        assert result.btc_txid == ""

    def test_request_exception_is_swallowed(self, mocker):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
            btc_watch_expires_at=timezone.now() + timedelta(minutes=10),
        )
        mocker.patch(
            "payments.services.requests.get",
            side_effect=requests.RequestException("boom"),
        )

        result = check_btc_payment(invoice)

        assert result.status == Invoice.Status.SENT

    def test_excludes_already_credited_txid_from_matching(self, mocker):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.UNDERPAID,
            btc_address="bc1qexample",
            btc_amount_sats=140000,
            btc_watch_expires_at=timezone.now() + timedelta(minutes=10),
            btc_credited_txid="short-tx",
            btc_credited_usd=Decimal("30.00"),
            remainder_owed_usd=Decimal("70.00"),
        )
        response = MagicMock()
        response.json.return_value = [
            {
                "txid": "short-tx",
                "vout": [
                    {
                        "scriptpubkey_address": "bc1qexample",
                        "value": 140000,
                    }
                ],
                "status": {"confirmed": True},
            }
        ]
        mocker.patch(
            "payments.services.requests.get", return_value=response
        )

        result = check_btc_payment(invoice)

        # The already-credited tx can't satisfy the remainder a second
        # time even though its value covers it.
        assert result.status == Invoice.Status.UNDERPAID
        assert result.btc_txid == ""

    def test_confirmed_tx_before_window_is_rejected(self, mocker):
        """The invoice-3 regression: a reused address's 9-month-old
        confirmed tx must not match a live quote just because it paid
        enough -- it predates the renter starting this watch.
        """
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
            btc_watch_expires_at=timezone.now() + timedelta(minutes=5),
        )
        _mock_mempool_requests(
            mocker,
            address_txs=[
                {
                    "txid": "old-tx",
                    "vout": [
                        {
                            "scriptpubkey_address": "bc1qexample",
                            "value": 100000,
                        }
                    ],
                    "status": {
                        "confirmed": True,
                        "block_time": int(
                            (
                                timezone.now() - timedelta(days=270)
                            ).timestamp()
                        ),
                    },
                }
            ],
        )

        result = check_btc_payment(invoice)

        assert result.status == Invoice.Status.SENT
        assert result.btc_txid == ""

    def test_overquote_tx_before_window_is_rejected_on_both_counts(
        self, mocker
    ):
        """Proves the time bound and the amount rule are independent
        defenses: this tx would also fail an exact-amount check, but
        is rejected here purely for predating the watch.
        """
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
            btc_watch_expires_at=timezone.now() + timedelta(minutes=5),
        )
        _mock_mempool_requests(
            mocker,
            address_txs=[
                {
                    "txid": "old-big-tx",
                    "vout": [
                        {
                            "scriptpubkey_address": "bc1qexample",
                            "value": 500000,
                        }
                    ],
                    "status": {
                        "confirmed": True,
                        "block_time": int(
                            (
                                timezone.now() - timedelta(days=270)
                            ).timestamp()
                        ),
                    },
                }
            ],
        )

        result = check_btc_payment(invoice)

        assert result.status == Invoice.Status.SENT
        assert result.btc_txid == ""
        assert result.btc_overpaid_usd is None

    def test_first_seen_zero_rejects_unconfirmed_candidate(self, mocker):
        """`transaction-times` returns 0 for a mined/unknown tx, which
        must fail closed rather than being treated as in-window.
        """
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
            btc_watch_expires_at=timezone.now() + timedelta(minutes=10),
        )
        _mock_mempool_requests(
            mocker,
            address_txs=[
                {
                    "txid": "unknown-tx",
                    "vout": [
                        {
                            "scriptpubkey_address": "bc1qexample",
                            "value": 100000,
                        }
                    ],
                    "status": {"confirmed": False},
                }
            ],
            first_seen={},
        )

        result = check_btc_payment(invoice)

        assert result.status == Invoice.Status.SENT
        assert result.btc_txid == ""

    def test_overquote_in_window_tx_settles_as_overpayment(self, mocker):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
            btc_watch_expires_at=timezone.now() + timedelta(minutes=10),
        )
        item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("50.00")
        )
        invoice.btc_line_items.set([item])
        _mock_mempool_requests(
            mocker,
            address_txs=[
                {
                    "txid": "big-tx",
                    "vout": [
                        {
                            "scriptpubkey_address": "bc1qexample",
                            "value": 120000,
                        }
                    ],
                    "status": {
                        "confirmed": True,
                        "block_time": int(timezone.now().timestamp()),
                    },
                }
            ],
        )
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )

        result = check_btc_payment(invoice)

        assert result.status == Invoice.Status.PAID
        assert result.btc_txid == ""
        assert result.settlements.get().txid == "big-tx"
        assert result.btc_overpaid_usd == Decimal("10.00")

    def test_overquote_in_window_tx_on_split_invoice_stays_partial(
        self, mocker
    ):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        invoice = attach_btc_payment(
            invoice, "bc1qexample", line_item_ids=[gas.id]
        )
        invoice.btc_amount_sats = 400000  # $200 gas @ $50k/BTC
        invoice.btc_watch_expires_at = timezone.now() + timedelta(minutes=10)
        invoice.save(
            update_fields=["btc_amount_sats", "btc_watch_expires_at"]
        )
        _mock_mempool_requests(
            mocker,
            address_txs=[
                {
                    "txid": "big-tx",
                    "vout": [
                        {
                            "scriptpubkey_address": "bc1qexample",
                            "value": 420000,
                        }
                    ],
                    "status": {
                        "confirmed": True,
                        "block_time": int(timezone.now().timestamp()),
                    },
                }
            ],
        )
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )

        result = check_btc_payment(invoice)

        assert result.status == Invoice.Status.PARTIAL
        assert result.btc_overpaid_usd == Decimal("10.00")


class TestUnderpaymentRoundTrip:
    """Drives a real underpay -> re-quote -> top-up -> PAID cycle,
    rather than hand-setting `remainder_owed_usd` the way
    `test_settling_the_btc_leg_clears_a_prior_shortfall` does -- that
    shortcut is exactly what left this path uncovered.
    """

    def test_short_tx_credits_a_remainder_then_a_topup_settles_it(
        self, mocker
    ):
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        invoice = attach_btc_payment(
            invoice, "bc1qexample", line_item_ids=[gas.id]
        )
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )

        invoice = initiate_btc_watch(invoice)
        assert invoice.btc_amount_sats == 400000  # $200 gas @ $50k/BTC

        # Lapse the window with only a short tx on the address.
        invoice.btc_watch_expires_at = timezone.now() - timedelta(minutes=5)
        invoice.save(update_fields=["btc_watch_expires_at"])
        # A couple seconds' buffer keeps `block_time` (int-truncated)
        # from landing before this window's precise `started_at` when
        # both fall in the same wall-clock second.
        short_tx_time = int(
            (timezone.now() + timedelta(seconds=2)).timestamp()
        )
        _mock_mempool_requests(
            mocker,
            address_txs=[
                {
                    "txid": "short-tx",
                    "vout": [
                        {
                            "scriptpubkey_address": "bc1qexample",
                            "value": 300000,
                        }
                    ],
                    "status": {
                        "confirmed": True,
                        "block_time": short_tx_time,
                    },
                }
            ],
        )

        invoice = initiate_btc_watch(invoice)

        assert invoice.status == Invoice.Status.UNDERPAID
        assert invoice.remainder_owed_usd == Decimal("50.00")
        assert invoice.btc_credited_txid == "short-tx"
        assert invoice.btc_credited_usd == Decimal("150.00")

        # Re-quote off the remainder.
        invoice = initiate_btc_watch(invoice)
        assert invoice.btc_amount_sats == 100000  # $50 @ $50k/BTC

        # The old short tx is still on the address, sized to look like
        # an overpayment against the smaller remainder quote -- it
        # must stay excluded, or it would wrongly re-match here. A
        # couple seconds' buffer keeps `block_time` (int-truncated)
        # from landing before the new window's precise `started_at`
        # when both fall in the same wall-clock second.
        topup_time = int(
            (timezone.now() + timedelta(seconds=2)).timestamp()
        )
        _mock_mempool_requests(
            mocker,
            address_txs=[
                {
                    "txid": "short-tx",
                    "vout": [
                        {
                            "scriptpubkey_address": "bc1qexample",
                            "value": 300000,
                        }
                    ],
                    "status": {
                        "confirmed": True,
                        "block_time": topup_time,
                    },
                },
                {
                    "txid": "topup-tx",
                    "vout": [
                        {
                            "scriptpubkey_address": "bc1qexample",
                            "value": 100000,
                        }
                    ],
                    "status": {
                        "confirmed": True,
                        "block_time": topup_time,
                    },
                },
            ],
        )

        invoice = check_btc_payment(invoice)

        assert invoice.status == Invoice.Status.PARTIAL
        assert invoice.remainder_owed_usd is None
        settlement = invoice.settlements.get()
        assert settlement.txid == "topup-tx"
        assert gas in settlement.line_items.all()


class TestBtcDiscrepancyEmails:
    """Fix 5b: the landlord is emailed on either kind of discrepancy,
    exactly once, and a dead mail host must never lose a settled
    payment.
    """

    def test_overpayment_email_fires_once_per_settlement(
        self, mocker, mailoutbox
    ):
        """A confirmed round clears btc_txid, so it can no longer be
        re-polled the way an old, still-PARTIAL split invoice could --
        instead, a duplicate settle attempt for the same txid must
        collapse onto the one already-created row and send no second
        email.
        """
        invoice, gas = _two_line_item_invoice(status=Invoice.Status.SENT)
        invoice = attach_btc_payment(
            invoice, "bc1qexample", line_item_ids=[gas.id]
        )
        invoice.btc_amount_sats = 400000  # $200 gas @ $50k/BTC
        invoice.btc_txid = "big-tx"
        invoice.btc_watch_expires_at = timezone.now() + timedelta(minutes=10)
        invoice.save(
            update_fields=[
                "btc_amount_sats", "btc_txid", "btc_watch_expires_at"
            ]
        )
        _mock_mempool_requests(
            mocker,
            tx_detail={
                "txid": "big-tx",
                "vout": [
                    {
                        "scriptpubkey_address": "bc1qexample",
                        "value": 420000,
                    }
                ],
                "status": {"confirmed": True},
            },
        )
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )

        result = check_btc_payment(invoice)
        assert result.status == Invoice.Status.PARTIAL
        assert result.btc_overpaid_usd == Decimal("10.00")
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == [invoice.billing_period.landlord.email]
        assert result.settlements.count() == 1

        # A second _settle_btc_leg call for the same txid (e.g. a
        # concurrent poll racing the first) must collapse onto the
        # same row via get_or_create, not send a second email.
        from payments.services import _settle_btc_leg

        result.btc_txid = "big-tx"
        _settle_btc_leg(result, True, paid_sats=420000)
        assert len(mailoutbox) == 1
        assert result.settlements.count() == 1

    def test_underpayment_sends_exactly_one_landlord_email(
        self, mocker, mailoutbox
    ):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
            btc_watch_expires_at=timezone.now() - timedelta(minutes=10),
        )
        item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("50.00")
        )
        invoice.btc_line_items.set([item])
        _mock_mempool_requests(
            mocker,
            address_txs=[
                {
                    "txid": "short-tx",
                    "vout": [
                        {
                            "scriptpubkey_address": "bc1qexample",
                            "value": 60000,
                        }
                    ],
                    "status": {"confirmed": False},
                }
            ],
            first_seen={"short-tx": int(timezone.now().timestamp())},
        )
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )

        result = initiate_btc_watch(invoice)

        assert result.status == Invoice.Status.UNDERPAID
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == [invoice.billing_period.landlord.email]

    def test_send_mail_failure_does_not_break_settlement(self, mocker):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
            btc_txid="big-tx",
            btc_watch_expires_at=timezone.now() + timedelta(minutes=10),
        )
        item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("50.00")
        )
        invoice.btc_line_items.set([item])
        _mock_mempool_requests(
            mocker,
            tx_detail={
                "txid": "big-tx",
                "vout": [
                    {
                        "scriptpubkey_address": "bc1qexample",
                        "value": 120000,
                    }
                ],
                "status": {"confirmed": True},
            },
        )
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )
        mocker.patch(
            "payments.services.send_mail",
            side_effect=Exception("smtp down"),
        )

        result = check_btc_payment(invoice)

        assert result.status == Invoice.Status.PAID
        assert result.btc_overpaid_usd == Decimal("10.00")


class TestGetBtcUsdPrice:
    @pytest.fixture(autouse=True)
    def _clear_price_cache(self):
        cache.delete(BTC_PRICE_CACHE_KEY)
        yield
        cache.delete(BTC_PRICE_CACHE_KEY)

    def test_fetches_and_caches_price(self, mocker):
        response = MagicMock()
        response.json.return_value = {"USD": 65000}
        get = mocker.patch(
            "payments.services.requests.get", return_value=response
        )

        assert get_btc_usd_price() == 65000
        assert get_btc_usd_price() == 65000
        get.assert_called_once()

    def test_returns_none_on_request_exception(self, mocker):
        mocker.patch(
            "payments.services.requests.get",
            side_effect=requests.RequestException("boom"),
        )

        assert get_btc_usd_price() is None

    def test_returns_none_when_usd_missing(self, mocker):
        response = MagicMock()
        response.json.return_value = {}
        mocker.patch(
            "payments.services.requests.get", return_value=response
        )

        assert get_btc_usd_price() is None


class TestUsdSatsConversion:
    """Covers the arithmetic backing every auto-generated BTC amount:
    `initiate_btc_watch` and `_reconcile_lapsed_watch` both derive their
    sats/USD figures from these two helpers, so their rounding behavior
    is worth pinning down directly rather than only indirectly through
    higher-level tests."""

    @pytest.mark.parametrize(
        "usd,usd_per_btc,expected_sats",
        [
            (Decimal("100.00"), 50000, 200000),
            (Decimal("1.00"), 1, 100000000),
            (Decimal("0.01"), 65000, 15),  # rounds, doesn't truncate
            (Decimal("0.00"), 50000, 0),
        ],
    )
    def test_usd_to_sats(self, usd, usd_per_btc, expected_sats):
        assert _usd_to_sats(usd, usd_per_btc) == expected_sats

    def test_usd_to_sats_rounds_half_up(self):
        # 0.000000005 BTC == 0.5 sats at this price; ROUND_HALF_UP -> 1.
        assert _usd_to_sats(Decimal("0.0005"), 100000) == 1

    @pytest.mark.parametrize(
        "sats,usd_per_btc,expected_usd",
        [
            (200000, 50000, Decimal("100.00")),
            (100000000, 1, Decimal("1.00")),
            (1, 65000, Decimal("0.00")),
            (0, 50000, Decimal("0.00")),
        ],
    )
    def test_sats_to_usd(self, sats, usd_per_btc, expected_usd):
        assert _sats_to_usd(sats, usd_per_btc) == expected_usd

    def test_round_trip_is_stable_for_whole_cent_amounts(self):
        original = Decimal("42.50")
        usd_per_btc = 37000
        sats = _usd_to_sats(original, usd_per_btc)

        assert _sats_to_usd(sats, usd_per_btc) == original
