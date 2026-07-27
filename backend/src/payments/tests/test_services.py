from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from billing.models import Invoice
from billing.tests.factories import InvoiceFactory, InvoiceLineItemFactory
from payments.services import (
    create_payment_intent_for_invoice,
    handle_payment_intent_succeeded,
)

pytestmark = pytest.mark.django_db


class TestCreatePaymentIntentForInvoice:
    def test_creates_new_intent_and_persists_id(self, mocker):
        invoice = InvoiceFactory()
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
        )
        mock_retrieve.assert_not_called()
        invoice.refresh_from_db()
        assert invoice.stripe_payment_intent_id == 'pi_new123'

    def test_reuses_existing_intent(self, mocker):
        invoice = InvoiceFactory(stripe_payment_intent_id='pi_existing')
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
        mock_retrieve.assert_called_once_with('pi_existing')
        mock_create.assert_not_called()


class TestHandlePaymentIntentSucceeded:
    def test_marks_matching_invoice_paid(self):
        invoice = InvoiceFactory(status=Invoice.Status.SENT)

        handle_payment_intent_succeeded(
            {'metadata': {'invoice_id': str(invoice.id)}}
        )

        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.PAID

    def test_missing_metadata_is_noop(self):
        invoice = InvoiceFactory(status=Invoice.Status.SENT)

        handle_payment_intent_succeeded({})

        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.SENT

    def test_empty_invoice_id_is_noop(self):
        invoice = InvoiceFactory(status=Invoice.Status.SENT)

        handle_payment_intent_succeeded({'metadata': {'invoice_id': ''}})

        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.SENT

    def test_nonexistent_invoice_id_is_noop_no_error(self):
        handle_payment_intent_succeeded({'metadata': {'invoice_id': '999999'}})
        # No exception raised; nothing to assert against.
