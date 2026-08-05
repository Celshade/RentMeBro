from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
import requests
from django.core.cache import cache
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
    BTC_PRICE_CACHE_KEY,
    BtcNotEnabledError,
    InvoiceAlreadyPaidError,
    LandlordNotOnboardedError,
    _sats_to_usd,
    _usd_to_sats,
    attach_btc_payment,
    check_btc_payment,
    create_payment_intent_for_invoice,
    enable_btc_payments,
    get_btc_usd_price,
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
        [
            Invoice.Status.PENDING,
            Invoice.Status.PARTIAL,
            Invoice.Status.PAID,
            Invoice.Status.VOID,
        ],
    )
    def test_raises_for_locked_invoice(self, locked_status):
        invoice = _btc_enabled_invoice(status=locked_status)

        with pytest.raises(InvoiceLockedError):
            attach_btc_payment(invoice, "bc1qexample")


class TestInitiateBtcWatch:
    def test_starts_watch_window_and_generates_amount_for_sent_invoice(
        self, mocker
    ):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT, btc_address="bc1qexample"
        )
        InvoiceLineItemFactory(invoice=invoice, amount=Decimal("100.00"))
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )

        result = initiate_btc_watch(invoice)

        assert result.btc_watch_expires_at is not None
        assert result.btc_watch_expires_at > timezone.now()
        assert result.btc_amount_sats == 200000  # $100 @ $50k/BTC

    def test_generates_amount_from_remainder_for_partial_invoice(
        self, mocker
    ):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.PARTIAL,
            btc_address="bc1qexample",
            remainder_owed_usd=Decimal("25.00"),
        )
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )

        result = initiate_btc_watch(invoice)

        assert result.btc_amount_sats == 50000  # $25 @ $50k/BTC

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
        InvoiceLineItemFactory(invoice=invoice, amount=Decimal("100.00"))
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )

        result = initiate_btc_watch(invoice)

        assert result.btc_watch_expires_at is not None
        assert result.btc_amount_sats == 200000  # $100 @ $50k/BTC

    @pytest.mark.parametrize(
        "status",
        [Invoice.Status.PENDING, Invoice.Status.PAID, Invoice.Status.VOID],
    )
    def test_noop_if_invoice_is_not_payable(self, status):
        invoice = _btc_enabled_invoice(status=status)

        result = initiate_btc_watch(invoice)

        assert result.btc_watch_expires_at is None

    def test_noop_if_tx_already_seen(self):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT, btc_txid="deadbeef"
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
        InvoiceLineItemFactory(invoice=invoice, amount=Decimal("100.00"))
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
        response = MagicMock()
        response.json.return_value = [
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
        ]
        mocker.patch(
            "payments.services.requests.get", return_value=response
        )

        result = initiate_btc_watch(invoice)

        assert result.status == Invoice.Status.PENDING
        assert result.btc_txid == "late-tx"

    def test_restart_past_grace_logs_underpayment_as_partial(self, mocker):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.SENT,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
            btc_watch_expires_at=timezone.now()
            - timedelta(minutes=10),
        )
        InvoiceLineItemFactory(invoice=invoice, amount=Decimal("100.00"))
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

        assert result.status == Invoice.Status.PARTIAL
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
            status=Invoice.Status.PARTIAL,
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
        assert result.status == Invoice.Status.PARTIAL
        assert result.remainder_owed_usd == Decimal("70.00")
        assert result.btc_amount_sats == 140000


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

    def test_excludes_already_credited_txid_from_matching(self, mocker):
        invoice = _btc_enabled_invoice(
            status=Invoice.Status.PARTIAL,
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
        assert result.status == Invoice.Status.PARTIAL
        assert result.btc_txid == ""


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
