from typing import Any

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from accounts.models import MagicLinkToken


class Command(BaseCommand):
    """Deletes magic-link tokens that are no longer usable.

    Meant to run on a schedule (e.g. daily cron) alongside simplejwt's
    own `flushexpiredtokens`, which prunes the refresh-token blacklist.
    """

    help = "Delete used or expired MagicLinkToken rows."

    def handle(self, *args: Any, **options: Any) -> None:
        deleted, _ = MagicLinkToken.objects.filter(
            Q(used_at__isnull=False) | Q(expires_at__lt=timezone.now())
        ).delete()
        self.stdout.write(f"Deleted {deleted} magic-link token(s).")
