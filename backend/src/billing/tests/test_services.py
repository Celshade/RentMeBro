from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.utils import timezone

from accounts.tests.factories import LandlordFactory, UserFactory
from billing import services
from billing.models import BillingPeriod, DrivenDayLog, Invoice, InvoiceLineItem
from billing.tests.factories import (
    BillingPeriodFactory,
    DrivenDayLogFactory,
    GasPriceEntryFactory,
    InvoiceFactory,
    InvoiceLineItemFactory,
    LeaseFactory,
    MileageProfileFactory,
)
from payments.tests.factories import InvoiceSettlementFactory

pytestmark = pytest.mark.django_db


# --- get_active_lease -------------------------------------------------

class TestGetActiveLease:
    def test_returns_active_lease(self):
        lease = LeaseFactory(active=True)
        result = services.get_active_lease(lease.landlord, lease.renter)
        assert result == lease

    def test_raises_when_no_lease(self):
        landlord, renter = LandlordFactory(), UserFactory()
        with pytest.raises(services.BillingConfigError):
            services.get_active_lease(landlord, renter)

    def test_ignores_inactive_lease(self):
        landlord, renter = LandlordFactory(), UserFactory()
        LeaseFactory(landlord=landlord, renter=renter, active=False)
        with pytest.raises(services.BillingConfigError):
            services.get_active_lease(landlord, renter)

    def test_returns_latest_start_date_when_multiple_active(self):
        landlord, renter = LandlordFactory(), UserFactory()
        LeaseFactory(
            landlord=landlord, renter=renter, start_date=date(2023, 1, 1)
        )
        newer = LeaseFactory(
            landlord=landlord, renter=renter, start_date=date(2024, 1, 1)
        )
        result = services.get_active_lease(landlord, renter)
        assert result == newer


# --- get_mileage_profile_for_date / get_gas_price_for_date ------------

class TestGetMileageProfileForDate:
    def test_returns_profile_effective_on_boundary_date(self):
        landlord, renter = LandlordFactory(), UserFactory()
        profile = MileageProfileFactory(
            landlord=landlord, renter=renter, effective_from=date(2024, 6, 1)
        )
        result = services.get_mileage_profile_for_date(
            landlord, renter, date(2024, 6, 1)
        )
        assert result == profile

    def test_raises_for_date_before_any_profile(self):
        landlord, renter = LandlordFactory(), UserFactory()
        MileageProfileFactory(
            landlord=landlord, renter=renter, effective_from=date(2024, 6, 1)
        )
        with pytest.raises(services.BillingConfigError):
            services.get_mileage_profile_for_date(
                landlord, renter, date(2024, 5, 31)
            )

    def test_returns_most_recent_profile_before_date(self):
        landlord, renter = LandlordFactory(), UserFactory()
        MileageProfileFactory(
            landlord=landlord,
            renter=renter,
            effective_from=date(2024, 1, 1),
            one_way_miles=Decimal('5.00'),
        )
        newer = MileageProfileFactory(
            landlord=landlord,
            renter=renter,
            effective_from=date(2024, 6, 1),
            one_way_miles=Decimal('10.00'),
        )
        result = services.get_mileage_profile_for_date(
            landlord, renter, date(2024, 7, 1)
        )
        assert result == newer


class TestGetGasPriceForDate:
    def test_returns_entry_within_open_ended_range(self):
        landlord, renter = LandlordFactory(), UserFactory()
        entry = GasPriceEntryFactory(
            landlord=landlord,
            renter=renter,
            effective_from=date(2024, 1, 1),
            effective_to=None,
        )
        result = services.get_gas_price_for_date(
            landlord, renter, date(2024, 12, 31)
        )
        assert result == entry

    def test_returns_entry_within_closed_range_on_boundary(self):
        landlord, renter = LandlordFactory(), UserFactory()
        entry = GasPriceEntryFactory(
            landlord=landlord,
            renter=renter,
            effective_from=date(2024, 1, 1),
            effective_to=date(2024, 1, 31),
        )
        result = services.get_gas_price_for_date(
            landlord, renter, date(2024, 1, 31)
        )
        assert result == entry

    def test_raises_after_closed_range_ends(self):
        landlord, renter = LandlordFactory(), UserFactory()
        GasPriceEntryFactory(
            landlord=landlord,
            renter=renter,
            effective_from=date(2024, 1, 1),
            effective_to=date(2024, 1, 31),
        )
        with pytest.raises(services.BillingConfigError):
            services.get_gas_price_for_date(landlord, renter, date(2024, 2, 1))

    def test_raises_when_no_entry_at_all(self):
        landlord, renter = LandlordFactory(), UserFactory()
        with pytest.raises(services.BillingConfigError):
            services.get_gas_price_for_date(landlord, renter, date(2024, 1, 1))


# --- compute_gas_cost_for_log -------------------------------------------

class TestComputeGasCostForLog:
    def test_day_off_costs_nothing_even_without_config(self):
        log = DrivenDayLogFactory(kind=DrivenDayLog.Kind.DAY_OFF)
        assert services.compute_gas_cost_for_log(log) == Decimal('0.00')

    def test_other_ride_costs_nothing_even_without_config(self):
        log = DrivenDayLogFactory(kind=DrivenDayLog.Kind.OTHER_RIDE)
        assert services.compute_gas_cost_for_log(log) == Decimal('0.00')

    def test_driven_full_day_computes_expected_cost(self):
        landlord, renter = LandlordFactory(), UserFactory()
        MileageProfileFactory(
            landlord=landlord,
            renter=renter,
            one_way_miles=Decimal('10.00'),
            mpg=Decimal('25.00'),
            effective_from=date(2024, 1, 1),
        )
        GasPriceEntryFactory(
            landlord=landlord,
            renter=renter,
            price_per_gallon=Decimal('3.500'),
            effective_from=date(2024, 1, 1),
        )
        log = DrivenDayLogFactory(
            landlord=landlord,
            renter=renter,
            date=date(2024, 6, 3),
            kind=DrivenDayLog.Kind.DRIVEN,
            day_fraction=Decimal('1.00'),
        )
        # 1 * (10*4) miles = 40 miles / 25 mpg = 1.6 gal * $3.50 = $5.60
        assert services.compute_gas_cost_for_log(log) == Decimal('5.60')

    def test_driven_fractional_day_computes_expected_cost(self):
        landlord, renter = LandlordFactory(), UserFactory()
        MileageProfileFactory(
            landlord=landlord,
            renter=renter,
            one_way_miles=Decimal('10.00'),
            mpg=Decimal('25.00'),
            effective_from=date(2024, 1, 1),
        )
        GasPriceEntryFactory(
            landlord=landlord,
            renter=renter,
            price_per_gallon=Decimal('3.500'),
            effective_from=date(2024, 1, 1),
        )
        log = DrivenDayLogFactory(
            landlord=landlord,
            renter=renter,
            date=date(2024, 6, 3),
            kind=DrivenDayLog.Kind.DRIVEN,
            day_fraction=Decimal('0.50'),
        )
        # 0.5 * 40 miles = 20 miles / 25 mpg = 0.8 gal * $3.50 = $2.80
        assert services.compute_gas_cost_for_log(log) == Decimal('2.80')

    def test_driven_without_mileage_profile_raises(self):
        landlord, renter = LandlordFactory(), UserFactory()
        GasPriceEntryFactory(
            landlord=landlord, renter=renter, effective_from=date(2024, 1, 1)
        )
        log = DrivenDayLogFactory(
            landlord=landlord, renter=renter, kind=DrivenDayLog.Kind.DRIVEN
        )
        with pytest.raises(services.BillingConfigError):
            services.compute_gas_cost_for_log(log)


# --- compute_period_gas_total -------------------------------------------

class TestComputePeriodGasTotal:
    def test_sums_driven_days_and_ignores_others(self):
        landlord, renter = LandlordFactory(), UserFactory()
        MileageProfileFactory(
            landlord=landlord,
            renter=renter,
            one_way_miles=Decimal('10.00'),
            mpg=Decimal('25.00'),
            effective_from=date(2024, 1, 1),
        )
        GasPriceEntryFactory(
            landlord=landlord,
            renter=renter,
            price_per_gallon=Decimal('3.500'),
            effective_from=date(2024, 1, 1),
        )
        DrivenDayLogFactory(
            landlord=landlord,
            renter=renter,
            date=date(2024, 6, 3),
            kind=DrivenDayLog.Kind.DRIVEN,
            day_fraction=Decimal('1.00'),
        )
        DrivenDayLogFactory(
            landlord=landlord,
            renter=renter,
            date=date(2024, 6, 4),
            kind=DrivenDayLog.Kind.DAY_OFF,
            day_fraction=Decimal('0'),
        )
        # Outside the target month -- must not be counted.
        DrivenDayLogFactory(
            landlord=landlord,
            renter=renter,
            date=date(2024, 7, 1),
            kind=DrivenDayLog.Kind.DRIVEN,
            day_fraction=Decimal('1.00'),
        )
        total = services.compute_period_gas_total(landlord, renter, 2024, 6)
        assert total == Decimal('5.60')

    def test_empty_period_returns_zero(self):
        landlord, renter = LandlordFactory(), UserFactory()
        assert services.compute_period_gas_total(
            landlord, renter, 2024, 6
        ) == Decimal('0.00')


# --- compute_period_weekly_breakdown -------------------------------------

class TestComputePeriodWeeklyBreakdown:
    def test_groups_logs_into_sunday_start_weeks(self):
        landlord, renter = LandlordFactory(), UserFactory()
        MileageProfileFactory(
            landlord=landlord,
            renter=renter,
            one_way_miles=Decimal('10.00'),
            mpg=Decimal('25.00'),
            effective_from=date(2024, 1, 1),
        )
        GasPriceEntryFactory(
            landlord=landlord,
            renter=renter,
            price_per_gallon=Decimal('3.500'),
            effective_from=date(2024, 1, 1),
        )
        # 2024-06-01 is a Saturday; 2024-06-02 is a Sunday (new week).
        DrivenDayLogFactory(
            landlord=landlord,
            renter=renter,
            date=date(2024, 6, 1),
            kind=DrivenDayLog.Kind.DRIVEN,
        )
        DrivenDayLogFactory(
            landlord=landlord,
            renter=renter,
            date=date(2024, 6, 2),
            kind=DrivenDayLog.Kind.DRIVEN,
        )

        weeks = services.compute_period_weekly_breakdown(
            landlord, renter, 2024, 6
        )

        assert len(weeks) == 2
        assert weeks[0]['week_start'] == date(2024, 5, 26)
        assert len(weeks[0]['days']) == 1
        assert weeks[1]['week_start'] == date(2024, 6, 2)
        assert len(weeks[1]['days']) == 1

    def test_week_price_per_gallon_none_when_no_driven_day(self):
        landlord, renter = LandlordFactory(), UserFactory()
        DrivenDayLogFactory(
            landlord=landlord,
            renter=renter,
            date=date(2024, 6, 3),
            kind=DrivenDayLog.Kind.DAY_OFF,
            day_fraction=Decimal('0'),
        )
        weeks = services.compute_period_weekly_breakdown(
            landlord, renter, 2024, 6
        )
        assert weeks[0]['price_per_gallon'] is None
        assert weeks[0]['total_gas_cost'] == Decimal('0.00')


# --- compute_period_preview ----------------------------------------------

class TestComputePeriodPreview:
    def test_combines_rent_and_gas(self):
        lease = LeaseFactory(monthly_rent=Decimal('1000.00'))
        preview = services.compute_period_preview(
            lease.landlord, lease.renter, 2024, 6
        )
        assert preview == {'rent': Decimal('1000.00'), 'gas': Decimal('0.00')}

    def test_raises_without_active_lease(self):
        landlord, renter = LandlordFactory(), UserFactory()
        with pytest.raises(services.BillingConfigError):
            services.compute_period_preview(landlord, renter, 2024, 6)


# --- default_invoice_due_date ---------------------------------------------

class TestDefaultInvoiceDueDate:
    def test_mid_year_rolls_to_next_month(self):
        assert services.default_invoice_due_date(2024, 6) == date(2024, 7, 5)

    def test_december_rolls_to_next_january(self):
        assert services.default_invoice_due_date(2024, 12) == date(2025, 1, 5)


# --- generate_invoice -------------------------------------------------

class TestGenerateInvoice:
    def test_combined_creates_rent_and_gas_line_items(self):
        lease = LeaseFactory(monthly_rent=Decimal('1000.00'))
        invoice = services.generate_invoice(
            lease.landlord, lease.renter, 2024, 6, Invoice.Kind.COMBINED
        )
        kinds = sorted(
            invoice.line_items.values_list('kind', flat=True)
        )
        assert kinds == ['gas', 'rent']
        rent_item = invoice.line_items.get(kind=InvoiceLineItem.Kind.RENT)
        assert rent_item.amount == Decimal('1000.00')

    def test_rent_only_does_not_require_gas_config(self):
        lease = LeaseFactory(monthly_rent=Decimal('1000.00'))
        invoice = services.generate_invoice(
            lease.landlord, lease.renter, 2024, 6, Invoice.Kind.RENT_ONLY
        )
        assert invoice.line_items.count() == 1
        assert invoice.line_items.first().kind == InvoiceLineItem.Kind.RENT

    def test_gas_only_does_not_require_active_lease(self):
        landlord, renter = LandlordFactory(), UserFactory()
        invoice = services.generate_invoice(
            landlord, renter, 2024, 6, Invoice.Kind.GAS_ONLY
        )
        assert invoice.line_items.count() == 1
        assert invoice.line_items.first().kind == InvoiceLineItem.Kind.GAS

    def test_duplicate_kind_raises_and_rolls_back(self):
        lease = LeaseFactory(monthly_rent=Decimal('1000.00'))
        services.generate_invoice(
            lease.landlord, lease.renter, 2024, 6, Invoice.Kind.RENT_ONLY
        )
        line_item_count_before = InvoiceLineItem.objects.count()

        with pytest.raises(services.InvoiceAlreadyExistsError):
            with transaction.atomic():
                services.generate_invoice(
                    lease.landlord,
                    lease.renter,
                    2024,
                    6,
                    Invoice.Kind.RENT_ONLY,
                )

        assert Invoice.objects.count() == 1
        assert InvoiceLineItem.objects.count() == line_item_count_before

    def test_reuses_billing_period_across_kinds(self):
        lease = LeaseFactory(monthly_rent=Decimal('1000.00'))
        services.generate_invoice(
            lease.landlord, lease.renter, 2024, 6, Invoice.Kind.RENT_ONLY
        )
        services.generate_invoice(
            lease.landlord, lease.renter, 2024, 6, Invoice.Kind.GAS_ONLY
        )
        assert BillingPeriod.objects.filter(
            landlord=lease.landlord, renter=lease.renter, year=2024, month=6
        ).count() == 1

    def test_explicit_due_date_overrides_default(self):
        lease = LeaseFactory(monthly_rent=Decimal('1000.00'))
        invoice = services.generate_invoice(
            lease.landlord,
            lease.renter,
            2024,
            6,
            Invoice.Kind.RENT_ONLY,
            due_date=date(2024, 6, 20),
        )
        assert invoice.due_date == date(2024, 6, 20)


# --- recompute_invoice_gas -------------------------------------------

class TestRecomputeInvoiceGas:
    def test_recomputes_gas_line_item_from_current_logs(self):
        landlord, renter = LandlordFactory(), UserFactory()
        MileageProfileFactory(
            landlord=landlord,
            renter=renter,
            one_way_miles=Decimal('10.00'),
            mpg=Decimal('25.00'),
            effective_from=date(2024, 1, 1),
        )
        GasPriceEntryFactory(
            landlord=landlord,
            renter=renter,
            price_per_gallon=Decimal('3.500'),
            effective_from=date(2024, 1, 1),
        )
        billing_period = BillingPeriodFactory(
            landlord=landlord, renter=renter, year=2024, month=6
        )
        invoice = InvoiceFactory(
            billing_period=billing_period, kind=Invoice.Kind.GAS_ONLY
        )
        InvoiceLineItemFactory(
            invoice=invoice, kind=InvoiceLineItem.Kind.GAS, amount=Decimal('0.00')
        )
        DrivenDayLogFactory(
            landlord=landlord,
            renter=renter,
            date=date(2024, 6, 3),
            kind=DrivenDayLog.Kind.DRIVEN,
        )

        updated = services.recompute_invoice_gas(invoice)

        gas_item = updated.line_items.get(kind=InvoiceLineItem.Kind.GAS)
        assert gas_item.amount == Decimal('5.60')

    def test_noop_when_no_gas_line_item(self):
        invoice = InvoiceFactory(kind=Invoice.Kind.RENT_ONLY)
        InvoiceLineItemFactory(
            invoice=invoice, kind=InvoiceLineItem.Kind.RENT
        )
        result = services.recompute_invoice_gas(invoice)
        assert result.line_items.count() == 1

    def test_raises_for_paid_invoice(self):
        invoice = InvoiceFactory(status=Invoice.Status.PAID)
        with pytest.raises(services.InvoiceLockedError):
            services.recompute_invoice_gas(invoice)

    def test_raises_for_void_invoice(self):
        invoice = InvoiceFactory(status=Invoice.Status.VOID)
        with pytest.raises(services.InvoiceLockedError):
            services.recompute_invoice_gas(invoice)

    def test_allows_pending_invoice_with_unfrozen_gas_item(self):
        invoice = InvoiceFactory(status=Invoice.Status.PENDING)
        InvoiceLineItemFactory(
            invoice=invoice, kind=InvoiceLineItem.Kind.GAS,
            amount=Decimal('0.00'),
        )
        result = services.recompute_invoice_gas(invoice)
        assert result.status == Invoice.Status.PENDING

    def test_raises_for_frozen_gas_item(self):
        """A PENDING/PARTIAL status no longer locks the whole invoice --
        only a frozen (paid or in-flight) gas item does.
        """
        invoice = InvoiceFactory(status=Invoice.Status.PARTIAL)
        gas_item = InvoiceLineItemFactory(
            invoice=invoice, kind=InvoiceLineItem.Kind.GAS,
            amount=Decimal('0.00'),
        )
        invoice.btc_address = 'bc1qexample'
        invoice.btc_amount_sats = 1000
        invoice.btc_watch_expires_at = timezone.now() + timedelta(minutes=5)
        invoice.save()
        invoice.btc_round_line_items.set([gas_item])

        with pytest.raises(services.InvoiceLockedError):
            services.recompute_invoice_gas(invoice)

    def test_clears_btc_fields_when_total_changes(self, mocker):
        mocker.patch(
            "payments.services.refresh_payment_state",
            side_effect=lambda invoice: invoice,
        )
        landlord, renter = LandlordFactory(), UserFactory()
        MileageProfileFactory(
            landlord=landlord,
            renter=renter,
            one_way_miles=Decimal("10.00"),
            mpg=Decimal("25.00"),
            effective_from=date(2024, 1, 1),
        )
        GasPriceEntryFactory(
            landlord=landlord,
            renter=renter,
            price_per_gallon=Decimal("3.500"),
            effective_from=date(2024, 1, 1),
        )
        billing_period = BillingPeriodFactory(
            landlord=landlord, renter=renter, year=2024, month=6
        )
        invoice = InvoiceFactory(
            billing_period=billing_period,
            kind=Invoice.Kind.GAS_ONLY,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
            btc_txid="deadbeef",
        )
        InvoiceLineItemFactory(
            invoice=invoice, kind=InvoiceLineItem.Kind.GAS,
            amount=Decimal("0.00"),
        )
        DrivenDayLogFactory(
            landlord=landlord,
            renter=renter,
            date=date(2024, 6, 3),
            kind=DrivenDayLog.Kind.DRIVEN,
        )

        updated = services.recompute_invoice_gas(invoice)

        assert updated.btc_address == ""
        assert updated.btc_amount_sats is None
        assert updated.btc_txid == ""

    def test_keeps_btc_fields_when_total_unchanged(self, mocker):
        mocker.patch(
            "payments.services.refresh_payment_state",
            side_effect=lambda invoice: invoice,
        )
        invoice = InvoiceFactory(
            kind=Invoice.Kind.GAS_ONLY,
            btc_address="bc1qexample",
            btc_amount_sats=100000,
            btc_txid="deadbeef",
        )
        InvoiceLineItemFactory(
            invoice=invoice, kind=InvoiceLineItem.Kind.GAS,
            amount=Decimal("0.00"),
        )

        updated = services.recompute_invoice_gas(invoice)

        assert updated.btc_address == "bc1qexample"
        assert updated.btc_amount_sats == 100000
        assert updated.btc_txid == "deadbeef"


# --- gas_period_is_locked / assert_gas_period_editable -----------------

class TestGasPeriodIsLocked:
    def test_no_billing_period_is_not_locked(self):
        landlord, renter = LandlordFactory(), UserFactory()
        assert services.gas_period_is_locked(
            landlord, renter, 2024, 6
        ) is False

    def test_unpaid_gas_item_is_not_locked(self):
        landlord, renter = LandlordFactory(), UserFactory()
        billing_period = BillingPeriodFactory(
            landlord=landlord, renter=renter, year=2024, month=6
        )
        invoice = InvoiceFactory(
            billing_period=billing_period, kind=Invoice.Kind.GAS_ONLY
        )
        InvoiceLineItemFactory(
            invoice=invoice, kind=InvoiceLineItem.Kind.GAS
        )

        assert services.gas_period_is_locked(
            landlord, renter, 2024, 6
        ) is False

    def test_settled_gas_item_is_locked(self):
        landlord, renter = LandlordFactory(), UserFactory()
        billing_period = BillingPeriodFactory(
            landlord=landlord, renter=renter, year=2024, month=6
        )
        invoice = InvoiceFactory(
            billing_period=billing_period, kind=Invoice.Kind.GAS_ONLY
        )
        gas_item = InvoiceLineItemFactory(
            invoice=invoice, kind=InvoiceLineItem.Kind.GAS
        )
        settlement = InvoiceSettlementFactory(invoice=invoice)
        settlement.line_items.set([gas_item])

        assert services.gas_period_is_locked(
            landlord, renter, 2024, 6
        ) is True

    def test_in_flight_btc_round_is_locked(self):
        landlord, renter = LandlordFactory(), UserFactory()
        billing_period = BillingPeriodFactory(
            landlord=landlord, renter=renter, year=2024, month=6
        )
        invoice = InvoiceFactory(
            billing_period=billing_period,
            kind=Invoice.Kind.GAS_ONLY,
            status=Invoice.Status.PARTIAL,
            btc_address="bc1qexample",
            btc_amount_sats=1000,
            btc_watch_expires_at=timezone.now() + timedelta(minutes=5),
        )
        gas_item = InvoiceLineItemFactory(
            invoice=invoice, kind=InvoiceLineItem.Kind.GAS
        )
        invoice.btc_round_line_items.set([gas_item])

        assert services.gas_period_is_locked(
            landlord, renter, 2024, 6
        ) is True

    def test_underpaid_fallback_is_not_locked(self):
        landlord, renter = LandlordFactory(), UserFactory()
        billing_period = BillingPeriodFactory(
            landlord=landlord, renter=renter, year=2024, month=6
        )
        invoice = InvoiceFactory(
            billing_period=billing_period,
            kind=Invoice.Kind.GAS_ONLY,
            status=Invoice.Status.UNDERPAID,
            btc_address="bc1qexample",
            btc_amount_sats=1000,
            btc_watch_expires_at=timezone.now() + timedelta(minutes=5),
            remainder_owed_usd=Decimal("5.00"),
        )
        gas_item = InvoiceLineItemFactory(
            invoice=invoice, kind=InvoiceLineItem.Kind.GAS
        )
        invoice.btc_round_line_items.set([gas_item])

        assert services.gas_period_is_locked(
            landlord, renter, 2024, 6
        ) is False

    def test_rent_only_invoice_is_not_locked(self):
        landlord, renter = LandlordFactory(), UserFactory()
        billing_period = BillingPeriodFactory(
            landlord=landlord, renter=renter, year=2024, month=6
        )
        InvoiceFactory(
            billing_period=billing_period, kind=Invoice.Kind.RENT_ONLY
        )

        assert services.gas_period_is_locked(
            landlord, renter, 2024, 6
        ) is False


class TestAssertGasPeriodEditable:
    def test_raises_for_locked_month(self):
        landlord, renter = LandlordFactory(), UserFactory()
        billing_period = BillingPeriodFactory(
            landlord=landlord, renter=renter, year=2024, month=6
        )
        invoice = InvoiceFactory(
            billing_period=billing_period, kind=Invoice.Kind.GAS_ONLY
        )
        gas_item = InvoiceLineItemFactory(
            invoice=invoice, kind=InvoiceLineItem.Kind.GAS
        )
        settlement = InvoiceSettlementFactory(invoice=invoice)
        settlement.line_items.set([gas_item])

        with pytest.raises(services.InvoiceLockedError):
            services.assert_gas_period_editable(
                landlord, renter, date(2024, 6, 15)
            )

    def test_does_not_raise_for_unlocked_month(self):
        landlord, renter = LandlordFactory(), UserFactory()
        services.assert_gas_period_editable(
            landlord, renter, date(2024, 6, 15)
        )
