from datetime import date
from decimal import Decimal

import factory
from factory.django import DjangoModelFactory

from accounts.tests.factories import LandlordFactory, UserFactory
from billing.models import (
    BillingPeriod,
    DrivenDayLog,
    GasPriceEntry,
    Invoice,
    InvoiceLineItem,
    Lease,
    LeaseRentRevision,
    MileageProfile,
)


class LeaseFactory(DjangoModelFactory):
    class Meta:
        model = Lease

    landlord = factory.SubFactory(LandlordFactory)
    renter = factory.SubFactory(UserFactory)
    monthly_rent = Decimal("1000.00")
    start_date = date(2024, 1, 1)
    active = True
    lease_type = Lease.LeaseType.DEFAULT
    term_months = 12


class LeaseRentRevisionFactory(DjangoModelFactory):
    class Meta:
        model = LeaseRentRevision

    # NOTE: saving a revision sends an email to lease.renter -- every
    # test using this factory produces that side effect (harmless with
    # the locmem backend django's test runner forces).
    lease = factory.SubFactory(LeaseFactory)
    new_monthly_rent = Decimal("1100.00")
    effective_date = date(2024, 6, 1)


class MileageProfileFactory(DjangoModelFactory):
    class Meta:
        model = MileageProfile

    landlord = factory.SubFactory(LandlordFactory)
    renter = factory.SubFactory(UserFactory)
    one_way_miles = Decimal("10.00")
    mpg = Decimal("25.00")
    effective_from = date(2024, 1, 1)


class GasPriceEntryFactory(DjangoModelFactory):
    class Meta:
        model = GasPriceEntry

    landlord = factory.SubFactory(LandlordFactory)
    renter = factory.SubFactory(UserFactory)
    price_per_gallon = Decimal("3.500")
    effective_from = date(2024, 1, 1)
    effective_to = None


class DrivenDayLogFactory(DjangoModelFactory):
    class Meta:
        model = DrivenDayLog

    landlord = factory.SubFactory(LandlordFactory)
    renter = factory.SubFactory(UserFactory)
    date = date(2024, 6, 3)
    kind = DrivenDayLog.Kind.DRIVEN
    day_fraction = Decimal("1.00")


class BillingPeriodFactory(DjangoModelFactory):
    class Meta:
        model = BillingPeriod

    landlord = factory.SubFactory(LandlordFactory)
    renter = factory.SubFactory(UserFactory)
    year = 2024
    month = 6


class InvoiceFactory(DjangoModelFactory):
    class Meta:
        model = Invoice

    # Deliberately no auto-created Lease here: many tests build an
    # invoice against a landlord/renter pair with no Lease at all
    # (e.g. gas-only invoices), so leave lease creation to the test.
    billing_period = factory.SubFactory(BillingPeriodFactory)
    kind = Invoice.Kind.COMBINED
    status = Invoice.Status.DRAFT
    due_date = date(2024, 7, 5)


class InvoiceLineItemFactory(DjangoModelFactory):
    class Meta:
        model = InvoiceLineItem

    invoice = factory.SubFactory(InvoiceFactory)
    description = "Rent for 2024-06"
    amount = Decimal("1000.00")
    kind = InvoiceLineItem.Kind.RENT
