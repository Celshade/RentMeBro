from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.utils import timezone

from accounts.models import MagicLinkToken, User
from accounts.tests.factories import MagicLinkTokenFactory, UserFactory

pytestmark = pytest.mark.django_db


class TestUser:
    def test_same_email_different_role_allowed(self):
        UserFactory(email="shared@example.com", role=User.Role.LANDLORD)
        UserFactory(email="shared@example.com", role=User.Role.RENTER)
        assert User.objects.filter(email="shared@example.com").count() == 2

    def test_same_email_same_role_rejected(self):
        UserFactory(
            username="a", email="dup@example.com", role=User.Role.RENTER
        )
        with pytest.raises(IntegrityError):
            UserFactory(
                username="b", email="dup@example.com", role=User.Role.RENTER
            )


class TestMagicLinkToken:
    def test_default_expiry_is_about_15_minutes_out(self):
        token = MagicLinkTokenFactory()
        delta = token.expires_at - token.created_at
        assert timedelta(minutes=14) < delta <= timedelta(minutes=15)

    def test_is_valid_when_fresh_and_unused(self):
        token = MagicLinkTokenFactory()
        assert token.is_valid() is True

    def test_is_valid_false_when_used(self):
        token = MagicLinkTokenFactory(used_at=timezone.now())
        assert token.is_valid() is False

    def test_is_valid_false_when_expired(self):
        token = MagicLinkTokenFactory(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        assert token.is_valid() is False

    def test_issue_generates_a_unique_hashed_token(self):
        magic_link, raw_token = MagicLinkToken.issue(UserFactory())
        assert magic_link.token_hash
        assert len(raw_token) > 20
        assert magic_link.token_hash != raw_token

    def test_find_valid_returns_none_for_unknown_token(self):
        assert MagicLinkToken.find_valid("does-not-exist") is None

    def test_find_valid_returns_the_token_for_a_matching_raw_value(self):
        magic_link, raw_token = MagicLinkToken.issue(UserFactory())
        assert MagicLinkToken.find_valid(raw_token) == magic_link
