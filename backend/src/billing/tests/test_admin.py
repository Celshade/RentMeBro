from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib import admin

from billing.admin import LeaseAdmin
from billing.models import Lease
from billing.tests.factories import LeaseFactory, LeaseRentRevisionFactory

pytestmark = pytest.mark.django_db


class TestLeaseAdmin:
    def _admin(self) -> LeaseAdmin:
        return LeaseAdmin(Lease, admin.site)

    def test_current_rent_returns_active_monthly_rent(self):
        lease = LeaseFactory(monthly_rent=Decimal('1000.00'))
        assert self._admin().current_rent(lease) == Decimal('1000.00')

    def test_pending_revision_returns_dash_when_none_scheduled(self):
        lease = LeaseFactory()
        assert self._admin().pending_revision(lease) == '—'

    def test_pending_revision_formats_scheduled_change(self):
        lease = LeaseFactory()
        LeaseRentRevisionFactory(
            lease=lease,
            new_monthly_rent=Decimal('1200.00'),
            effective_date=date.today() + timedelta(days=30),
        )
        expected = (
            f'$1200.00 eff. {(date.today() + timedelta(days=30)).isoformat()}'
        )
        assert self._admin().pending_revision(lease) == expected
