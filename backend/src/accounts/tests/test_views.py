import re

import pytest
from django.core import mail
from django.urls import reverse

from accounts.models import MagicLinkToken, User
from accounts.tests.factories import MagicLinkTokenFactory, UserFactory

pytestmark = pytest.mark.django_db

REQUEST_URL = reverse('magic-link-request')
VERIFY_URL = reverse('magic-link-verify')


class TestMagicLinkRequestView:
    def test_known_email_sends_email_and_returns_204(self, api_client):
        user = UserFactory(email='known@example.com', role=User.Role.RENTER)

        response = api_client.post(
            REQUEST_URL, {'email': user.email, 'role': user.role}
        )

        assert response.status_code == 204
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [user.email]
        assert MagicLinkToken.objects.filter(user=user).exists()

    def test_unknown_email_still_returns_204_no_email_no_token(
        self, api_client
    ):
        response = api_client.post(
            REQUEST_URL,
            {'email': 'nobody@example.com', 'role': User.Role.RENTER},
        )

        assert response.status_code == 204
        assert len(mail.outbox) == 0
        assert MagicLinkToken.objects.count() == 0

    def test_mismatched_role_returns_204_but_no_email(self, api_client):
        user = UserFactory(email='known2@example.com', role=User.Role.RENTER)

        response = api_client.post(
            REQUEST_URL, {'email': user.email, 'role': User.Role.LANDLORD}
        )

        assert response.status_code == 204
        assert len(mail.outbox) == 0

    def test_invalid_payload_returns_400(self, api_client):
        response = api_client.post(
            REQUEST_URL, {'email': 'not-an-email', 'role': 'renter'}
        )
        assert response.status_code == 400

    def test_missing_role_returns_400(self, api_client):
        response = api_client.post(REQUEST_URL, {'email': 'a@example.com'})
        assert response.status_code == 400

    def test_throttled_after_rate_exceeded(self, api_client, monkeypatch):
        # ScopedRateThrottle.THROTTLE_RATES is captured from settings at
        # import time (a class attribute, not read fresh per-request), so
        # @override_settings alone doesn't affect it -- patch the class
        # attribute directly instead.
        from rest_framework.throttling import ScopedRateThrottle

        monkeypatch.setitem(
            ScopedRateThrottle.THROTTLE_RATES, 'magic_link_request', '1/hour'
        )
        user = UserFactory(email='throttle@example.com', role=User.Role.RENTER)
        payload = {'email': user.email, 'role': user.role}

        first = api_client.post(REQUEST_URL, payload)
        second = api_client.post(REQUEST_URL, payload)

        assert first.status_code == 204
        assert second.status_code == 429


class TestMagicLinkVerifyView:
    def test_valid_token_returns_jwt_pair_and_marks_used(self, api_client):
        token = MagicLinkTokenFactory()

        response = api_client.post(VERIFY_URL, {'token': token.token})

        assert response.status_code == 200
        assert 'access' in response.data
        assert 'refresh' in response.data
        assert response.data['user']['email'] == token.user.email
        token.refresh_from_db()
        assert token.used_at is not None

    def test_token_cannot_be_reused(self, api_client):
        token = MagicLinkTokenFactory()
        api_client.post(VERIFY_URL, {'token': token.token})

        second = api_client.post(VERIFY_URL, {'token': token.token})

        assert second.status_code == 400

    def test_expired_token_returns_400_and_is_untouched(self, api_client):
        from datetime import timedelta

        from django.utils import timezone

        token = MagicLinkTokenFactory(
            expires_at=timezone.now() - timedelta(minutes=1)
        )

        response = api_client.post(VERIFY_URL, {'token': token.token})

        assert response.status_code == 400
        token.refresh_from_db()
        assert token.used_at is None

    def test_unknown_token_returns_400(self, api_client):
        response = api_client.post(VERIFY_URL, {'token': 'does-not-exist'})
        assert response.status_code == 400


class TestMagicLinkFullRoundTrip:
    def test_request_then_verify_yields_working_access_token(
        self, api_client
    ):
        user = UserFactory(email='roundtrip@example.com', role=User.Role.LANDLORD)

        api_client.post(REQUEST_URL, {'email': user.email, 'role': user.role})
        assert len(mail.outbox) == 1

        match = re.search(r'token=([\w-]+)', mail.outbox[0].body)
        assert match is not None
        token_value = match.group(1)

        verify_response = api_client.post(VERIFY_URL, {'token': token_value})
        assert verify_response.status_code == 200
        access = verify_response.data['access']

        api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        leases_response = api_client.get(reverse('lease-list'))
        assert leases_response.status_code == 200
