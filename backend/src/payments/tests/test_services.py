from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
import requests
from django.utils import timezone

from accounts.tests.factories import LandlordFactory
from billing.models import Invoice
from billing.services import InvoiceLockedError
from billing.tests.factories import (
    BillingPeriodFactory,
    InvoiceFactory,
    InvoiceLineItemFactory,
)
from payments.services import (
    BtcNotEnabledError,
    InvoiceAlreadyPaidError,
    LandlordNotOnboardedError,
    attach_btc_payment,
    check_btc_payment,
    create_payment_intent_for_invoice,
    enable_btc_payments,
    handle_account_updated,
    handle_payment_intent_succeeded,
    initiate_btc_watch,
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
        fake_intent = MagicMock(id='pi_new123', client_secret='secret')
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

    def test_reuses_existing_intent(self, mocker):
        invoice = _onboarded_invoice(stripe_payment_intent_id='pi_existing')
        fake_intent = MagicMock(id='pi_existing')
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
        fresh_intent = MagicMock(id='pi_fresh123', client_secret='secret')
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


class TestAttachBtcPayment:
    def test_attaches_address_and_amount(self):
        invoice = _btc_enabled_invoice(status=Invoice.Status.SENT)

        result = attach_btc_payment(invoice, "bc1qexample", 100000)

        assert result.btc_address == "bc1qexample"
        assert result.btc_amount_sats == 100000
        invoice.refresh_from_db()
        assert invoice.btc_address == "bc1qexample"
        assert invoice.btc_amount_sats == 100000

    def test_raises_if_landlord_not_enabled(self):
        invoice = InvoiceFactory(status=Invoice.Status.SENT)

        with pytest.raises(BtcNotEnabledError):
            attach_btc_payment(invoice, "bc1qexample", 100000)

    @pytest.mark.parametrize(
        "locked_status",
        [Invoice.Status.PENDING, Invoice.Status.PAID, Invoice.Status.VOID],
    )
    def test_raises_for_locked_invoice(self, locked_status):
        invoice = _btc_enabled_invoice(status=locked_status)

        with pytest.raises(InvoiceLockedError):
            attach_btc_payment(invoice, "bc1qexample", 100000)


class TestInitiateBtcWatch:
    def test_starts_watch_window_for_sent_invoice(self):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
        )

        result = initiate_btc_watch(invoice)

        assert result.btc_watch_expires_at is not None
        assert result.btc_watch_expires_at > timezone.now()

    def test_noop_if_not_sent(self):
        invoice = _btc_enabled_invoice(status=Invoice.Status.DRAFT)

        result = initiate_btc_watch(invoice)

        assert result.btc_watch_expires_at is None

    def test_noop_if_tx_already_seen(self):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT, btc_txid="deadbeef"
        )

        result = initiate_btc_watch(invoice)

        assert result.btc_watch_expires_at is None


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
        response = MagicMock()
        response.json.return_value = [
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
        ]
        mocker.patch(
            "payments.services.requests.get", return_value=response
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
        response = MagicMock()
        response.json.return_value = [
            {
                "txid": "tx1",
                "vout": [
                    {
                        "scriptpubkey_address": "bc1qexample",
                        "value": 100000,
                    }
                ],
                "status": {"confirmed": True},
            }
        ]
        mocker.patch(
            "payments.services.requests.get", return_value=response
        )

        result = check_btc_payment(invoice)

        assert result.status == Invoice.Status.PAID
        assert result.btc_txid == "tx1"

    def test_confirms_via_known_txid(self, mocker):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.PENDING,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
            btc_txid="tx1",
            btc_watch_expires_at=timezone.now() + timedelta(minutes=10),
        )
        response = MagicMock()
        response.json.return_value = {"confirmed": True}
        mocker.patch(
            "payments.services.requests.get", return_value=response
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
