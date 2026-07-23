from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.db import IntegrityError
from django.utils import timezone

from billing.models import Invoice
from billing.tests.factories import (
    DrivenDayLogFactory,
    InvoiceFactory,
    InvoiceLineItemFactory,
    LeaseFactory,
    LeaseRentRevisionFactory,
    MileageProfileFactory,
)

pytestmark = pytest.mark.django_db


class TestLease:
    def test_default_terms_text_includes_key_facts(self):
        lease = LeaseFactory(
            monthly_rent=Decimal('1234.00'),
            term_months=12,
            start_date=date(2024, 1, 1),
        )
        text = lease.default_terms_text
        assert '1234.00' in text
        assert '12 months' in text
        assert '2024-01-01' in text

    def test_current_monthly_rent_with_no_revisions(self):
        lease = LeaseFactory(monthly_rent=Decimal('1000.00'))
        assert lease.current_monthly_rent == Decimal('1000.00')

    def test_current_monthly_rent_with_past_effective_revision(self):
        lease = LeaseFactory(monthly_rent=Decimal('1000.00'))
        LeaseRentRevisionFactory(
            lease=lease,
            new_monthly_rent=Decimal('1100.00'),
            effective_date=timezone.now().date() - timedelta(days=1),
        )
        assert lease.current_monthly_rent == Decimal('1100.00')

    def test_current_monthly_rent_ignores_future_revision(self):
        lease = LeaseFactory(monthly_rent=Decimal('1000.00'))
        LeaseRentRevisionFactory(
            lease=lease,
            new_monthly_rent=Decimal('1200.00'),
            effective_date=timezone.now().date() + timedelta(days=30),
        )
        assert lease.current_monthly_rent == Decimal('1000.00')

    def test_current_monthly_rent_uses_most_recent_effective_revision(self):
        lease = LeaseFactory(monthly_rent=Decimal('1000.00'))
        today = timezone.now().date()
        LeaseRentRevisionFactory(
            lease=lease,
            new_monthly_rent=Decimal('1100.00'),
            effective_date=today - timedelta(days=60),
        )
        LeaseRentRevisionFactory(
            lease=lease,
            new_monthly_rent=Decimal('1200.00'),
            effective_date=today - timedelta(days=10),
        )
        assert lease.current_monthly_rent == Decimal('1200.00')

    def test_pending_rent_revision_is_none_with_no_revisions(self):
        lease = LeaseFactory()
        assert lease.pending_rent_revision is None

    def test_pending_rent_revision_ignores_past_effective_revision(self):
        lease = LeaseFactory()
        LeaseRentRevisionFactory(
            lease=lease,
            effective_date=timezone.now().date() - timedelta(days=1),
        )
        assert lease.pending_rent_revision is None

    def test_pending_rent_revision_returns_future_revision(self):
        lease = LeaseFactory()
        revision = LeaseRentRevisionFactory(
            lease=lease,
            new_monthly_rent=Decimal('1200.00'),
            effective_date=timezone.now().date() + timedelta(days=30),
        )
        assert lease.pending_rent_revision == revision

    def test_pending_rent_revision_returns_soonest_of_multiple_future(self):
        lease = LeaseFactory()
        sooner = LeaseRentRevisionFactory(
            lease=lease,
            effective_date=timezone.now().date() + timedelta(days=30),
        )
        LeaseRentRevisionFactory(
            lease=lease,
            effective_date=timezone.now().date() + timedelta(days=60),
        )
        assert lease.pending_rent_revision == sooner


class TestLeaseRentRevision:
    def test_creating_sends_exactly_one_email_to_renter(self):
        lease = LeaseFactory()
        mail.outbox.clear()

        LeaseRentRevisionFactory(lease=lease)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [lease.renter.email]

    def test_updating_does_not_resend_email(self):
        revision = LeaseRentRevisionFactory()
        mail.outbox.clear()

        revision.new_monthly_rent = Decimal('1500.00')
        revision.save(update_fields=['new_monthly_rent'])

        assert len(mail.outbox) == 0


class TestMileageProfile:
    def test_full_day_miles_is_four_times_one_way(self):
        profile = MileageProfileFactory(one_way_miles=Decimal('10.00'))
        assert profile.full_day_miles == Decimal('40.00')


class TestInvoice:
    def test_total_sums_line_items(self):
        invoice = InvoiceFactory()
        InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal('1000.00'), kind='rent'
        )
        InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal('50.25'), kind='gas'
        )
        assert invoice.total == Decimal('1050.25')

    def test_total_is_zero_with_no_line_items(self):
        invoice = InvoiceFactory()
        assert invoice.total == Decimal('0')

    def test_is_late_false_for_paid_invoice_even_if_past_due(self):
        invoice = InvoiceFactory(
            status=Invoice.Status.PAID,
            due_date=timezone.now().date() - timedelta(days=5),
        )
        assert invoice.is_late is False

    def test_is_late_false_for_void_invoice_even_if_past_due(self):
        invoice = InvoiceFactory(
            status=Invoice.Status.VOID,
            due_date=timezone.now().date() - timedelta(days=5),
        )
        assert invoice.is_late is False

    def test_is_late_true_for_draft_invoice_past_due(self):
        invoice = InvoiceFactory(
            status=Invoice.Status.DRAFT,
            due_date=timezone.now().date() - timedelta(days=1),
        )
        assert invoice.is_late is True

    def test_is_late_false_for_draft_invoice_not_yet_due(self):
        invoice = InvoiceFactory(
            status=Invoice.Status.DRAFT,
            due_date=timezone.now().date() + timedelta(days=1),
        )
        assert invoice.is_late is False


class TestDrivenDayLog:
    def test_unique_together_landlord_renter_date(self):
        log = DrivenDayLogFactory()
        with pytest.raises(IntegrityError):
            DrivenDayLogFactory(
                landlord=log.landlord, renter=log.renter, date=log.date
            )
