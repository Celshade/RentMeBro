from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from accounts.tests.factories import LandlordFactory
from billing.models import Invoice
from billing.tests.factories import (
    BillingPeriodFactory,
    InvoiceFactory,
    InvoiceLineItemFactory,
)
from payments.services import (
    LandlordNotOnboardedError,
    create_payment_intent_for_invoice,
    handle_account_updated,
    handle_payment_intent_succeeded,
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
