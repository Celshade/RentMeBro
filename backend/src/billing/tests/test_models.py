from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.db import IntegrityError
from django.utils import timezone

from billing.models import Invoice
from billing.tests.factories import (
    BillingPeriodFactory,
    DrivenDayLogFactory,
    GasPriceEntryFactory,
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
            monthly_rent=Decimal("1234.00"),
            term_months=12,
            start_date=date(2024, 1, 1),
        )
        text = lease.default_terms_text
        assert "1234.00" in text
        assert "12 months" in text
        assert "2024-01-01" in text

    def test_current_monthly_rent_with_no_revisions(self):
        lease = LeaseFactory(monthly_rent=Decimal("1000.00"))
        assert lease.current_monthly_rent == Decimal("1000.00")

    def test_current_monthly_rent_with_past_effective_revision(self):
        lease = LeaseFactory(monthly_rent=Decimal("1000.00"))
        LeaseRentRevisionFactory(
            lease=lease,
            new_monthly_rent=Decimal("1100.00"),
            effective_date=timezone.now().date() - timedelta(days=1),
        )
        assert lease.current_monthly_rent == Decimal("1100.00")

    def test_current_monthly_rent_ignores_future_revision(self):
        lease = LeaseFactory(monthly_rent=Decimal("1000.00"))
        LeaseRentRevisionFactory(
            lease=lease,
            new_monthly_rent=Decimal("1200.00"),
            effective_date=timezone.now().date() + timedelta(days=30),
        )
        assert lease.current_monthly_rent == Decimal("1000.00")

    def test_current_monthly_rent_uses_most_recent_effective_revision(self):
        lease = LeaseFactory(monthly_rent=Decimal("1000.00"))
        today = timezone.now().date()
        LeaseRentRevisionFactory(
            lease=lease,
            new_monthly_rent=Decimal("1100.00"),
            effective_date=today - timedelta(days=60),
        )
        LeaseRentRevisionFactory(
            lease=lease,
            new_monthly_rent=Decimal("1200.00"),
            effective_date=today - timedelta(days=10),
        )
        assert lease.current_monthly_rent == Decimal("1200.00")

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
            new_monthly_rent=Decimal("1200.00"),
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

    def test_rent_for_month_with_no_revisions_uses_base_rent(self):
        lease = LeaseFactory(monthly_rent=Decimal("1000.00"))
        assert lease.rent_for_month(2024, 6) == Decimal("1000.00")

    def test_rent_for_month_revision_effective_on_the_1st_applies(self):
        lease = LeaseFactory(monthly_rent=Decimal("1000.00"))
        LeaseRentRevisionFactory(
            lease=lease,
            new_monthly_rent=Decimal("1100.00"),
            effective_date=date(2024, 6, 1),
        )
        assert lease.rent_for_month(2024, 6) == Decimal("1100.00")

    def test_rent_for_month_revision_effective_before_month_applies(self):
        lease = LeaseFactory(monthly_rent=Decimal("1000.00"))
        LeaseRentRevisionFactory(
            lease=lease,
            new_monthly_rent=Decimal("1100.00"),
            effective_date=date(2024, 5, 15),
        )
        assert lease.rent_for_month(2024, 6) == Decimal("1100.00")

    def test_rent_for_month_revision_effective_after_month_ignored(self):
        lease = LeaseFactory(monthly_rent=Decimal("1000.00"))
        LeaseRentRevisionFactory(
            lease=lease,
            new_monthly_rent=Decimal("1100.00"),
            effective_date=date(2024, 6, 2),
        )
        assert lease.rent_for_month(2024, 6) == Decimal("1000.00")

    def test_rent_for_month_uses_most_recent_qualifying_revision(self):
        lease = LeaseFactory(monthly_rent=Decimal("1000.00"))
        LeaseRentRevisionFactory(
            lease=lease,
            new_monthly_rent=Decimal("1100.00"),
            effective_date=date(2024, 1, 1),
        )
        LeaseRentRevisionFactory(
            lease=lease,
            new_monthly_rent=Decimal("1200.00"),
            effective_date=date(2024, 5, 1),
        )
        assert lease.rent_for_month(2024, 6) == Decimal("1200.00")

    def test_rent_for_month_is_independent_of_todays_date(self):
        """A back-dated or future-dated invoice bills the rent that was
        actually in force for the billed month, not whatever is in
        effect today.
        """
        lease = LeaseFactory(monthly_rent=Decimal("1000.00"))
        LeaseRentRevisionFactory(
            lease=lease,
            new_monthly_rent=Decimal("1200.00"),
            effective_date=timezone.now().date() - timedelta(days=1),
        )
        past_year = timezone.now().date().year - 2
        assert lease.rent_for_month(past_year, 1) == Decimal("1000.00")

    def test_str_includes_landlord_and_renter(self):
        lease = LeaseFactory()
        assert str(lease) == f"Lease({lease.landlord} -> {lease.renter})"


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

        revision.new_monthly_rent = Decimal("1500.00")
        revision.save(update_fields=["new_monthly_rent"])

        assert len(mail.outbox) == 0

    def test_str_includes_lease_amount_and_date(self):
        revision = LeaseRentRevisionFactory(
            new_monthly_rent=Decimal("1200.00"),
            effective_date=date(2024, 6, 1),
        )
        assert str(revision) == (
            f"LeaseRentRevision(lease={revision.lease_id}, "
            f"$1200.00, 2024-06-01)"
        )


class TestMileageProfile:
    def test_full_day_miles_is_four_times_one_way(self):
        profile = MileageProfileFactory(one_way_miles=Decimal("10.00"))
        assert profile.full_day_miles == Decimal("40.00")

    def test_str_includes_landlord_renter_and_date(self):
        profile = MileageProfileFactory(effective_from=date(2024, 1, 1))
        assert str(profile) == (
            f"MileageProfile(landlord={profile.landlord_id}, "
            f"renter={profile.renter_id}, from=2024-01-01)"
        )


class TestGasPriceEntry:
    def test_str_includes_landlord_renter_price_and_date(self):
        entry = GasPriceEntryFactory(
            price_per_gallon=Decimal("3.50"),
            effective_from=date(2024, 1, 1),
        )
        assert str(entry) == (
            f"GasPriceEntry(landlord={entry.landlord_id}, "
            f"renter={entry.renter_id}, $3.50, from=2024-01-01)"
        )


class TestBillingPeriod:
    def test_str_includes_landlord_renter_and_period(self):
        period = BillingPeriodFactory(year=2024, month=6)
        assert str(period) == (
            f"BillingPeriod(landlord={period.landlord_id}, "
            f"renter={period.renter_id}, 2024-06)"
        )


class TestInvoice:
    def test_total_sums_line_items(self):
        invoice = InvoiceFactory()
        InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("1000.00"), kind="rent"
        )
        InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("50.25"), kind="gas"
        )
        assert invoice.total == Decimal("1050.25")

    def test_total_is_zero_with_no_line_items(self):
        invoice = InvoiceFactory()
        assert invoice.total == Decimal("0")

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

    def test_is_late_false_for_draft_invoice_past_due(self):
        """A draft was never sent, so it can't be late yet (#27)."""
        invoice = InvoiceFactory(
            status=Invoice.Status.DRAFT,
            due_date=timezone.now().date() - timedelta(days=1),
        )
        assert invoice.is_late is False

    def test_is_late_true_for_sent_invoice_past_due(self):
        invoice = InvoiceFactory(
            status=Invoice.Status.SENT,
            due_date=timezone.now().date() - timedelta(days=1),
        )
        assert invoice.is_late is True

    def test_is_late_false_for_draft_invoice_not_yet_due(self):
        invoice = InvoiceFactory(
            status=Invoice.Status.DRAFT,
            due_date=timezone.now().date() + timedelta(days=1),
        )
        assert invoice.is_late is False

    def test_str_includes_billing_period_and_kind(self):
        invoice = InvoiceFactory(kind=Invoice.Kind.RENT_ONLY)
        assert str(invoice) == (
            f"Invoice({invoice.billing_period}, rent_only)"
        )

    def test_credited_shortfall_nets_out_of_single_item_totals(self):
        """A credited shortfall on a single-item invoice must net out
        of every rail's payoff figure, not just `btc_owed_usd` (#53).
        """
        invoice = InvoiceFactory(
            remainder_owed_usd=Decimal("70.00"),
            btc_credited_txid="short-tx",
            btc_credited_usd=Decimal("30.00"),
        )
        item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("100.00")
        )
        invoice.btc_line_items.set([item])
        invoice.btc_round_line_items.set([item])

        assert invoice.btc_owed_usd == Decimal("70.00")
        assert invoice.stripe_portion_usd == Decimal("70.00")
        assert invoice.card_full_owed_usd == Decimal("70.00")
        assert invoice.btc_full_owed_usd == Decimal("70.00")

    def test_credited_shortfall_on_gas_leaves_rent_leg_unnetted(self):
        """The subset rule: a credit against gas must never net against
        a card leg quoting rent alone (#53).
        """
        invoice = InvoiceFactory(
            remainder_owed_usd=Decimal("20.00"),
            btc_credited_txid="short-tx",
            btc_credited_usd=Decimal("30.00"),
        )
        rent = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("1000.00"), kind="rent"
        )
        gas = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("50.00"), kind="gas"
        )
        invoice.btc_line_items.set([gas])
        invoice.btc_round_line_items.set([gas])

        # The card leg bills rent alone -- the credit was against gas,
        # so it must not be subtracted here.
        assert invoice.stripe_portion_usd == Decimal("1000.00")
        # "Pay it all instead" totals cover every item, so they do
        # include the gas item the credit actually applies to.
        assert invoice.card_full_owed_usd == Decimal("1020.00")
        assert invoice.btc_full_owed_usd == Decimal("1020.00")

    def test_no_credit_leaves_totals_unchanged(self):
        invoice = InvoiceFactory()
        item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("100.00")
        )
        invoice.btc_line_items.set([item])

        assert invoice.stripe_portion_usd == Decimal("100.00")
        assert invoice.card_full_owed_usd == Decimal("100.00")
        assert invoice.btc_full_owed_usd == Decimal("100.00")

    def test_cleared_credit_leaves_totals_unchanged(self):
        """A settled/cleared credit (remainder None) must not double as
        a leftover netting signal -- guards against double-netting
        after `_settle_btc_leg` clears these fields.
        """
        invoice = InvoiceFactory(
            remainder_owed_usd=None,
            btc_credited_txid="",
            btc_credited_usd=None,
        )
        item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("100.00")
        )
        invoice.btc_line_items.set([item])

        assert invoice.stripe_portion_usd == Decimal("100.00")
        assert invoice.card_full_owed_usd == Decimal("100.00")
        assert invoice.btc_full_owed_usd == Decimal("100.00")

    def test_credit_exceeding_item_total_floors_at_zero(self):
        invoice = InvoiceFactory(
            remainder_owed_usd=Decimal("0.00"),
            btc_credited_txid="short-tx",
            btc_credited_usd=Decimal("999.00"),
        )
        item = InvoiceLineItemFactory(
            invoice=invoice, amount=Decimal("100.00")
        )
        invoice.btc_line_items.set([item])
        invoice.btc_round_line_items.set([item])

        assert invoice.stripe_portion_usd == Decimal("0")
        assert invoice.card_full_owed_usd == Decimal("0")
        assert invoice.btc_full_owed_usd == Decimal("0")


class TestCardRoundLiveness:
    def test_processing_is_live_even_an_hour_past_expiry(self):
        """Only Stripe may end a `processing` round -- expiry never
        resurrects it locally.
        """
        invoice = InvoiceFactory(
            stripe_intent_status="processing",
            stripe_round_expires_at=(
                timezone.now() - timedelta(hours=1)
            ),
        )
        assert invoice.card_round_is_live is True

    def test_requires_action_past_expiry_is_not_live(self):
        invoice = InvoiceFactory(
            stripe_intent_status="requires_action",
            stripe_round_expires_at=(
                timezone.now() - timedelta(minutes=1)
            ),
        )
        assert invoice.card_round_is_live is False

    def test_requires_action_future_expiry_is_live(self):
        invoice = InvoiceFactory(
            stripe_intent_status="requires_action",
            stripe_round_expires_at=(
                timezone.now() + timedelta(minutes=1)
            ),
        )
        assert invoice.card_round_is_live is True

    def test_requires_action_null_expiry_is_live(self):
        """A round the app hasn't polled yet must not unfreeze before
        the first poll learns a real expiry.
        """
        invoice = InvoiceFactory(
            stripe_intent_status="requires_action",
            stripe_round_expires_at=None,
        )
        assert invoice.card_round_is_live is True

    def test_requires_payment_method_future_expiry_is_not_live(self):
        """A stale expiry left over from a prior round must not
        resurrect a status that blocks nothing.
        """
        invoice = InvoiceFactory(
            stripe_intent_status="requires_payment_method",
            stripe_round_expires_at=(
                timezone.now() + timedelta(minutes=1)
            ),
        )
        assert invoice.card_round_is_live is False

    def test_stale_true_for_processing_past_expiry(self):
        invoice = InvoiceFactory(
            stripe_intent_status="processing",
            stripe_round_expires_at=(
                timezone.now() - timedelta(minutes=1)
            ),
        )
        assert invoice.card_round_is_stale is True

    def test_stale_true_for_requires_action_past_expiry(self):
        invoice = InvoiceFactory(
            stripe_intent_status="requires_action",
            stripe_round_expires_at=(
                timezone.now() - timedelta(minutes=1)
            ),
        )
        assert invoice.card_round_is_stale is True

    def test_stale_true_for_null_expiry(self):
        invoice = InvoiceFactory(
            stripe_intent_status="requires_action",
            stripe_round_expires_at=None,
        )
        assert invoice.card_round_is_stale is True

    def test_stale_false_while_live(self):
        invoice = InvoiceFactory(
            stripe_intent_status="processing",
            stripe_round_expires_at=(
                timezone.now() + timedelta(minutes=1)
            ),
        )
        assert invoice.card_round_is_stale is False

    def test_stale_false_for_terminal_status(self):
        invoice = InvoiceFactory(
            stripe_intent_status="succeeded",
            stripe_round_expires_at=None,
        )
        assert invoice.card_round_is_stale is False


class TestInvoiceLineItem:
    def test_str_includes_kind_and_amount(self):
        line_item = InvoiceLineItemFactory(
            kind="rent", amount=Decimal("1000.00")
        )
        assert str(line_item) == "InvoiceLineItem(rent, $1000.00)"


class TestDrivenDayLog:
    def test_unique_together_landlord_renter_date(self):
        log = DrivenDayLogFactory()
        with pytest.raises(IntegrityError):
            DrivenDayLogFactory(
                landlord=log.landlord, renter=log.renter, date=log.date
            )

    def test_str_includes_landlord_renter_date_kind_and_fraction(self):
        log = DrivenDayLogFactory(
            date=date(2024, 6, 5),
            kind="driven",
            day_fraction=Decimal("1.00"),
        )
        assert str(log) == (
            f"DrivenDayLog(landlord={log.landlord_id}, "
            f"renter={log.renter_id}, 2024-06-05, driven, 1.00)"
        )
