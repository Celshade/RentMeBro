import pytest
from rest_framework.test import APIClient

from accounts.tests.factories import UserFactory
from billing.tests.factories import BillingPeriodFactory, InvoiceFactory


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def renter(db):
    return UserFactory()


@pytest.fixture
def landlord(db):
    from accounts.tests.factories import LandlordFactory

    return LandlordFactory()


@pytest.fixture
def invoice(db, landlord, renter):
    billing_period = BillingPeriodFactory(landlord=landlord, renter=renter)
    return InvoiceFactory(billing_period=billing_period)
