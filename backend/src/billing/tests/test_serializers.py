"""InvoiceSerializer's BTC-leg data contract: the three per-leg scope
arrays and `btc_owed_usd` that `PaymentLegSummary` renders from.
"""

from decimal import Decimal

import pytest

from billing.models import Invoice, InvoiceLineItem
from billing.serializers import InvoiceSerializer
from billing.tests.factories import (
    BillingPeriodFactory,
    InvoiceFactory,
    InvoiceLineItemFactory,
)
from payments.services import _invoice_usd_owed

pytestmark = pytest.mark.django_db


def _two_line_item_invoice(**kwargs) -> tuple[Invoice, InvoiceLineItem]:
    """A $1000 rent + $200 gas invoice, returned with its gas item."""
    invoice = InvoiceFactory(billing_period=BillingPeriodFactory(), **kwargs)
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


class TestInvoiceSerializerScopeArrays:
    def test_nothing_assigned_leaves_btc_empty_and_card_full(self):
        invoice, _gas = _two_line_item_invoice()
        rent, gas = invoice.line_items.all()

        data = InvoiceSerializer(invoice).data

        assert data["btc_scope_line_items"] == []
        assert data["stripe_scope_line_items"] == sorted(
            [rent.id, gas.id]
        )
        assert data["card_full_line_items"] == sorted([rent.id, gas.id])
        assert data["btc_owed_usd"] == "0"

    def test_split_assignment_partitions_the_two_rails(self):
        invoice, gas = _two_line_item_invoice()
        rent = invoice.line_items.exclude(id=gas.id).get()
        invoice.btc_line_items.set([gas])

        data = InvoiceSerializer(invoice).data

        assert data["btc_scope_line_items"] == [gas.id]
        assert data["stripe_scope_line_items"] == [rent.id]
        assert data["card_full_line_items"] == sorted([rent.id, gas.id])
        assert Decimal(data["btc_owed_usd"]) == Decimal("200.00")

    def test_everything_assigned_still_bills_full_card(self):
        invoice, gas = _two_line_item_invoice()
        rent = invoice.line_items.exclude(id=gas.id).get()
        invoice.btc_line_items.set([rent, gas])

        data = InvoiceSerializer(invoice).data

        assert data["btc_scope_line_items"] == sorted([rent.id, gas.id])
        # Assigning every item still leaves the card leg able to bill
        # the whole invoice -- only an explicit lock takes it away.
        assert data["stripe_scope_line_items"] == sorted(
            [rent.id, gas.id]
        )
        assert Decimal(data["btc_owed_usd"]) == Decimal("1200.00")


class TestInvoiceSerializerBtcOwedUsd:
    def test_equals_remainder_when_underpaid(self):
        invoice, gas = _two_line_item_invoice()
        invoice.btc_line_items.set([gas])
        invoice.status = Invoice.Status.UNDERPAID
        invoice.remainder_owed_usd = Decimal("35.00")
        invoice.save(update_fields=["status", "remainder_owed_usd"])

        data = InvoiceSerializer(invoice).data

        assert Decimal(data["btc_owed_usd"]) == Decimal("35.00")

    @pytest.mark.parametrize(
        "scope,remainder",
        [
            (None, None),
            ("gas", None),
            ("both", None),
            ("gas", Decimal("35.00")),
        ],
    )
    def test_pinned_to_the_services_helper(self, scope, remainder):
        """The serializer duplicates `_invoice_usd_owed` rather than
        importing it -- pin the two together so they can't silently
        drift.
        """
        invoice, gas = _two_line_item_invoice()
        rent = invoice.line_items.exclude(id=gas.id).get()
        if scope == "gas":
            invoice.btc_line_items.set([gas])
        elif scope == "both":
            invoice.btc_line_items.set([rent, gas])
        if remainder is not None:
            invoice.remainder_owed_usd = remainder
            invoice.save(update_fields=["remainder_owed_usd"])

        data = InvoiceSerializer(invoice).data

        assert Decimal(data["btc_owed_usd"]) == _invoice_usd_owed(invoice)
