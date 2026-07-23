import pytest
from rest_framework.test import APIClient

from accounts.models import User
from accounts.tests.factories import LandlordFactory, UserFactory


@pytest.fixture
def landlord(db) -> User:
    return LandlordFactory()


@pytest.fixture
def renter(db) -> User:
    return UserFactory()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def landlord_client(api_client, landlord) -> APIClient:
    api_client.force_authenticate(user=landlord)
    return api_client


@pytest.fixture
def renter_client(api_client, renter) -> APIClient:
    api_client.force_authenticate(user=renter)
    return api_client
