from decimal import Decimal

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from billing.tests.factories import InvoiceFactory
from payments.models import InvoiceSettlement


class InvoiceSettlementFactory(DjangoModelFactory):
    class Meta:
        model = InvoiceSettlement

    invoice = factory.SubFactory(InvoiceFactory)
    rail = InvoiceSettlement.Rail.BTC
    amount_usd = Decimal('100.00')
    settled_at = factory.LazyFunction(timezone.now)
