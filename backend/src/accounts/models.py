import hashlib
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
        """Which side of a lease a user is on."""

        LANDLORD = "landlord", "Landlord"
        RENTER = "renter", "Renter"

    role = models.CharField(max_length=16, choices=Role.choices)
    stripe_account_id = models.CharField(max_length=255, blank=True)
    stripe_charges_enabled = models.BooleanField(default=False)
    btc_payments_enabled = models.BooleanField(default=False)
    btc_terms_accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["email", "role"], name="unique_email_role"
            ),
        ]


def _generate_token() -> str:
    """Kept for migration 0002, which references this as a field default."""
    return secrets.token_urlsafe(32)


def _default_expiry() -> datetime:
    return timezone.now() + timedelta(minutes=15)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


class MagicLinkToken(models.Model):
    """A single-use, time-limited login token emailed to a user.

    Only the SHA-256 hash of the token is stored, matching password
    storage practice: reading the database (a backup, a dump, an
    over-privileged query) doesn't hand out a usable login link.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="magic_link_tokens",
    )
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_default_expiry)
    used_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def issue(cls, user: User) -> tuple["MagicLinkToken", str]:
        """Creates a token for `user`, returning it with the raw value.

        The raw value is only ever available here, at creation time —
        it's what gets emailed, and it's never stored or logged.
        """
        raw_token = secrets.token_urlsafe(32)
        magic_link = cls.objects.create(
            user=user, token_hash=_hash_token(raw_token)
        )
        return magic_link, raw_token

    @classmethod
    def find_valid(cls, raw_token: str) -> "MagicLinkToken | None":
        """Looks up `raw_token` and returns it only if still usable."""
        magic_link = cls.objects.filter(
            token_hash=_hash_token(raw_token)
        ).first()
        if magic_link is not None and magic_link.is_valid():
            return magic_link
        return None

    def is_valid(self) -> bool:
        return self.used_at is None and timezone.now() < self.expires_at
