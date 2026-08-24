from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from accounts.models import MagicLinkToken
from accounts.tests.factories import MagicLinkTokenFactory

pytestmark = pytest.mark.django_db


class TestPruneMagicLinks:
    def test_deletes_used_and_expired_tokens_only(self):
        used = MagicLinkTokenFactory(used_at=timezone.now())
        expired = MagicLinkTokenFactory(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        live = MagicLinkTokenFactory()

        out = StringIO()
        call_command("prune_magic_links", stdout=out)

        remaining = set(MagicLinkToken.objects.values_list("pk", flat=True))
        assert remaining == {live.pk}
        assert used.pk not in remaining
        assert expired.pk not in remaining
        assert "Deleted 2" in out.getvalue()
