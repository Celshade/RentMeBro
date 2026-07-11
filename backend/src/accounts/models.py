import secrets
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """Custom user with a landlord/renter role.

    Set as AUTH_USER_MODEL from project init so it's safe to extend
    later without a disruptive user-model swap.
    """

    class Role(models.TextChoices):
        LANDLORD = 'landlord', 'Landlord'
        RENTER = 'renter', 'Renter'

    role = models.CharField(max_length=16, choices=Role.choices)


def _generate_token() -> str:
    return secrets.token_urlsafe(32)


def _default_expiry() -> datetime:
    return timezone.now() + timedelta(minutes=15)


class MagicLinkToken(models.Model):
    """A single-use, time-limited login token emailed to a user."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='magic_link_tokens',
    )
    token = models.CharField(
        max_length=64, unique=True, default=_generate_token
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_default_expiry)
    used_at = models.DateTimeField(null=True, blank=True)

    def is_valid(self) -> bool:
        return self.used_at is None and timezone.now() < self.expires_at
