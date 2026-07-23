import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from accounts.models import User
from accounts.tests.factories import LandlordFactory, UserFactory
from billing.permissions import IsLandlord

pytestmark = pytest.mark.django_db


class TestIsLandlord:
    def _request_for(self, user, rf):
        request = rf.get('/')
        request.user = user
        return request

    def test_true_for_landlord(self, rf: RequestFactory):
        landlord = LandlordFactory()
        request = self._request_for(landlord, rf)
        assert IsLandlord().has_permission(request, None) is True

    def test_false_for_renter(self, rf: RequestFactory):
        renter = UserFactory(role=User.Role.RENTER)
        request = self._request_for(renter, rf)
        assert IsLandlord().has_permission(request, None) is False

    def test_false_for_anonymous(self, rf: RequestFactory):
        request = self._request_for(AnonymousUser(), rf)
        assert IsLandlord().has_permission(request, None) is False
