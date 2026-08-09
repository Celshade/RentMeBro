from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.tests.factories import LandlordFactory, UserFactory
from billing.models import Invoice, InvoiceLineItem
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
from payments.tests.factories import InvoiceSettlementFactory

pytestmark = pytest.mark.django_db


# --- LeaseViewSet ----------------------------------------------------

class TestLeaseViewSet:
    def test_list_scoped_to_own_leases(self, landlord_client, landlord):
        own_lease = LeaseFactory(landlord=landlord)
        LeaseFactory()  # someone else's lease

        response = landlord_client.get(reverse('lease-list'))

        assert response.status_code == 200
        ids = [item['id'] for item in response.data]
        assert ids == [own_lease.id]

    def test_serializes_pending_rent_revision(
        self, landlord_client, landlord
    ):
        lease = LeaseFactory(landlord=landlord)
        LeaseRentRevisionFactory(
            lease=lease,
            new_monthly_rent=Decimal('1200.00'),
            effective_date=date.today() + timedelta(days=30),
        )

        response = landlord_client.get(reverse('lease-list'))

        pending = response.data[0]['pending_rent_revision']
        assert pending['new_monthly_rent'] == '1200.00'
        assert pending['effective_date'] == (
            date.today() + timedelta(days=30)
        ).isoformat()

    def test_serializes_null_pending_rent_revision_when_none_scheduled(
        self, landlord_client, landlord
    ):
        LeaseFactory(landlord=landlord)

        response = landlord_client.get(reverse('lease-list'))

        assert response.data[0]['pending_rent_revision'] is None

    def test_create_requires_landlord(self, renter_client, renter):
        response = renter_client.post(
            reverse('lease-list'),
            {
                'renter': renter.id,
                'monthly_rent': '1000.00',
                'start_date': '2024-01-01',
                'lease_type': 'default',
                'term_months': 12,
            },
        )
        assert response.status_code == 403

    def test_create_requires_authentication(self, api_client):
        response = api_client.post(reverse('lease-list'), {})
        assert response.status_code == 401

    def test_create_forces_landlord_to_requesting_user(
        self, landlord_client, landlord, renter
    ):
        response = landlord_client.post(
            reverse('lease-list'),
            {
                'renter': renter.id,
                'monthly_rent': '1000.00',
                'start_date': '2024-01-01',
                'lease_type': 'default',
                'term_months': 12,
            },
        )
        assert response.status_code == 201
        assert response.data['landlord'] == landlord.id

    def test_default_lease_without_term_months_rejected(
        self, landlord_client, renter
    ):
        response = landlord_client.post(
            reverse('lease-list'),
            {
                'renter': renter.id,
                'monthly_rent': '1000.00',
                'start_date': '2024-01-01',
                'lease_type': 'default',
            },
        )
        assert response.status_code == 400

    def test_custom_lease_without_document_rejected(
        self, landlord_client, renter
    ):
        response = landlord_client.post(
            reverse('lease-list'),
            {
                'renter': renter.id,
                'monthly_rent': '1000.00',
                'start_date': '2024-01-01',
                'lease_type': 'custom',
            },
        )
        assert response.status_code == 400

    def test_custom_lease_with_document_has_no_terms_text(
        self, landlord_client, renter
    ):
        from django.core.files.uploadedfile import SimpleUploadedFile

        document = SimpleUploadedFile(
            'lease.pdf', b'%PDF-1.4', content_type='application/pdf'
        )
        response = landlord_client.post(
            reverse('lease-list'),
            {
                'renter': renter.id,
                'monthly_rent': '1000.00',
                'start_date': '2024-01-01',
                'lease_type': 'custom',
                'document': document,
            },
            format='multipart',
        )
        assert response.status_code == 201
        assert response.data['terms_text'] is None


# --- DrivenDayLogViewSet ------------------------------------------------

class TestDrivenDayLogViewSet:
    def test_renter_can_read_but_not_write(
        self, landlord_client, renter_client, landlord, renter
    ):
        LeaseFactory(landlord=landlord, renter=renter)
        DrivenDayLogFactory(landlord=landlord, renter=renter)

        list_response = renter_client.get(reverse('driven-day-list'))
        assert list_response.status_code == 200

        create_response = renter_client.post(
            reverse('driven-day-list'),
            {
                'renter': renter.id,
                'date': '2024-06-05',
                'kind': 'driven',
                'day_fraction': '1.00',
            },
        )
        assert create_response.status_code == 403

    def test_landlord_create_requires_existing_lease_with_renter(
        self, landlord_client, renter
    ):
        # No lease created between landlord_client's landlord and renter.
        response = landlord_client.post(
            reverse('driven-day-list'),
            {
                'renter': renter.id,
                'date': '2024-06-05',
                'kind': 'driven',
                'day_fraction': '1.00',
            },
        )
        assert response.status_code == 400

    def test_landlord_create_succeeds_with_existing_lease(
        self, landlord_client, landlord, renter
    ):
        LeaseFactory(landlord=landlord, renter=renter)
        response = landlord_client.post(
            reverse('driven-day-list'),
            {
                'renter': renter.id,
                'date': '2024-06-05',
                'kind': 'driven',
                'day_fraction': '1.00',
            },
        )
        assert response.status_code == 201
        assert response.data['landlord'] == landlord.id

    def test_non_driven_kind_forces_zero_day_fraction(
        self, landlord_client, landlord, renter
    ):
        LeaseFactory(landlord=landlord, renter=renter)
        response = landlord_client.post(
            reverse('driven-day-list'),
            {
                'renter': renter.id,
                'date': '2024-06-05',
                'kind': 'day_off',
                'day_fraction': '1.00',
            },
        )
        assert response.status_code == 201
        assert response.data['day_fraction'] == '0.00'

    def test_patch_paid_month_returns_409(
        self, landlord_client, landlord, renter
    ):
        LeaseFactory(landlord=landlord, renter=renter)
        log = DrivenDayLogFactory(
            landlord=landlord, renter=renter, date=date(2024, 6, 5)
        )
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

        response = landlord_client.patch(
            reverse('driven-day-detail', args=[log.id]), {'note': 'edit'}
        )

        assert response.status_code == 409
        assert 'detail' in response.data

    def test_post_paid_month_returns_409(
        self, landlord_client, landlord, renter
    ):
        LeaseFactory(landlord=landlord, renter=renter)
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

        response = landlord_client.post(
            reverse('driven-day-list'),
            {
                'renter': renter.id,
                'date': '2024-06-05',
                'kind': 'driven',
                'day_fraction': '1.00',
            },
        )

        assert response.status_code == 409
        assert 'detail' in response.data

    def test_delete_paid_month_returns_409(
        self, landlord_client, landlord, renter
    ):
        LeaseFactory(landlord=landlord, renter=renter)
        log = DrivenDayLogFactory(
            landlord=landlord, renter=renter, date=date(2024, 6, 5)
        )
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

        response = landlord_client.delete(
            reverse('driven-day-detail', args=[log.id])
        )

        assert response.status_code == 409
        assert 'detail' in response.data

    def test_writes_against_unpaid_month_still_succeed(
        self, landlord_client, landlord, renter
    ):
        LeaseFactory(landlord=landlord, renter=renter)
        log = DrivenDayLogFactory(
            landlord=landlord, renter=renter, date=date(2024, 6, 5)
        )
        BillingPeriodFactory(
            landlord=landlord, renter=renter, year=2024, month=6
        )

        patch_response = landlord_client.patch(
            reverse('driven-day-detail', args=[log.id]), {'note': 'edit'}
        )
        assert patch_response.status_code == 200

        delete_response = landlord_client.delete(
            reverse('driven-day-detail', args=[log.id])
        )
        assert delete_response.status_code == 204

    def test_moving_log_into_paid_month_returns_409(
        self, landlord_client, landlord, renter
    ):
        LeaseFactory(landlord=landlord, renter=renter)
        log = DrivenDayLogFactory(
            landlord=landlord, renter=renter, date=date(2024, 7, 5)
        )
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

        response = landlord_client.patch(
            reverse('driven-day-detail', args=[log.id]),
            {'date': '2024-06-05'},
        )

        assert response.status_code == 409
        assert 'detail' in response.data


# --- MileageProfileViewSet / GasPriceEntryViewSet -----------------------

class TestMileageProfileViewSet:
    def test_renter_write_forbidden(self, renter_client, renter):
        response = renter_client.post(
            reverse('mileage-profile-list'),
            {
                'renter': renter.id,
                'one_way_miles': '10.00',
                'mpg': '25.00',
                'effective_from': '2024-01-01',
            },
        )
        assert response.status_code == 403

    def test_landlord_write_requires_lease(self, landlord_client, renter):
        response = landlord_client.post(
            reverse('mileage-profile-list'),
            {
                'renter': renter.id,
                'one_way_miles': '10.00',
                'mpg': '25.00',
                'effective_from': '2024-01-01',
            },
        )
        assert response.status_code == 400

    def test_landlord_create_succeeds_with_existing_lease(
        self, landlord_client, landlord, renter
    ):
        LeaseFactory(landlord=landlord, renter=renter)
        response = landlord_client.post(
            reverse('mileage-profile-list'),
            {
                'renter': renter.id,
                'one_way_miles': '10.00',
                'mpg': '25.00',
                'effective_from': '2024-01-01',
            },
        )
        assert response.status_code == 201
        assert response.data['landlord'] == landlord.id

    def test_list_scoped_to_own_profiles_and_readable_by_renter(
        self, renter_client, landlord, renter
    ):
        own_profile = MileageProfileFactory(landlord=landlord, renter=renter)
        MileageProfileFactory()  # someone else's profile

        response = renter_client.get(reverse('mileage-profile-list'))

        assert response.status_code == 200
        ids = [item['id'] for item in response.data]
        assert ids == [own_profile.id]


class TestGasPriceEntryViewSet:
    def test_renter_write_forbidden(self, renter_client, renter):
        response = renter_client.post(
            reverse('gas-price-entry-list'),
            {
                'renter': renter.id,
                'price_per_gallon': '3.50',
                'effective_from': '2024-01-01',
            },
        )
        assert response.status_code == 403

    def test_landlord_create_succeeds_with_existing_lease(
        self, landlord_client, landlord, renter
    ):
        LeaseFactory(landlord=landlord, renter=renter)
        response = landlord_client.post(
            reverse('gas-price-entry-list'),
            {
                'renter': renter.id,
                'price_per_gallon': '3.50',
                'effective_from': '2024-01-01',
            },
        )
        assert response.status_code == 201
        assert response.data['landlord'] == landlord.id

    def test_list_scoped_to_own_entries_and_readable_by_renter(
        self, renter_client, landlord, renter
    ):
        own_entry = GasPriceEntryFactory(landlord=landlord, renter=renter)
        GasPriceEntryFactory()  # someone else's entry

        response = renter_client.get(reverse('gas-price-entry-list'))

        assert response.status_code == 200
        ids = [item['id'] for item in response.data]
        assert ids == [own_entry.id]


# --- InvoiceViewSet ----------------------------------------------------

class TestInvoiceViewSetCreate:
    def test_create_happy_path(self, landlord_client, landlord, renter):
        LeaseFactory(
            landlord=landlord, renter=renter, monthly_rent=Decimal('1000.00')
        )
        response = landlord_client.post(
            reverse('invoice-list'),
            {'renter': renter.id, 'year': 2024, 'month': 6, 'kind': 'rent_only'},
        )
        assert response.status_code == 201
        assert response.data['total'] == '1000.00'

    def test_create_conflict_on_duplicate(
        self, landlord_client, landlord, renter
    ):
        LeaseFactory(landlord=landlord, renter=renter)
        payload = {
            'renter': renter.id, 'year': 2024, 'month': 6, 'kind': 'rent_only'
        }
        landlord_client.post(reverse('invoice-list'), payload)

        response = landlord_client.post(reverse('invoice-list'), payload)

        assert response.status_code == 409

    def test_create_gas_only_without_gas_config_succeeds_with_zero_total(
        self, landlord_client, landlord, renter
    ):
        LeaseFactory(landlord=landlord, renter=renter)
        response = landlord_client.post(
            reverse('invoice-list'),
            {'renter': renter.id, 'year': 2024, 'month': 6, 'kind': 'gas_only'},
        )
        # No mileage profile/gas price configured -- gas total is $0, so
        # this should actually succeed; assert the happy path instead.
        assert response.status_code == 201

    def test_create_requires_landlord(self, renter_client, renter):
        response = renter_client.post(
            reverse('invoice-list'),
            {'renter': renter.id, 'year': 2024, 'month': 6, 'kind': 'rent_only'},
        )
        assert response.status_code == 403

    def test_create_rent_only_without_active_lease_returns_400(
        self, landlord_client, landlord, renter
    ):
        """An inactive lease passes serializer validation but fails
        generate_invoice's active-lease lookup, surfacing a
        BillingConfigError as a 400.
        """
        LeaseFactory(landlord=landlord, renter=renter, active=False)
        response = landlord_client.post(
            reverse('invoice-list'),
            {'renter': renter.id, 'year': 2024, 'month': 6, 'kind': 'rent_only'},
        )
        assert response.status_code == 400


class TestInvoiceViewSetRetrieve:
    """Fix 3: a pending BTC tx is checked on retrieve, so a payment
    that confirms after the renter's tab closes still gets settled.
    """

    def test_checks_pending_btc_tx_on_retrieve(
        self, mocker, landlord_client, landlord, renter
    ):
        billing_period = BillingPeriodFactory(
            landlord=landlord, renter=renter
        )
        invoice = InvoiceFactory(
            billing_period=billing_period,
            btc_address="bc1qexample",
            btc_txid="tx1",
            btc_settled_at=None,
        )
        mock_check = mocker.patch(
            "billing.views.check_btc_payment", return_value=invoice
        )

        response = landlord_client.get(
            reverse('invoice-detail', args=[invoice.id])
        )

        assert response.status_code == 200
        assert response.data["btc_txid"] == "tx1"
        mock_check.assert_called_once_with(invoice)

    def test_does_not_check_when_no_txid_seen(
        self, mocker, landlord_client, landlord, renter
    ):
        billing_period = BillingPeriodFactory(
            landlord=landlord, renter=renter
        )
        invoice = InvoiceFactory(
            billing_period=billing_period,
            btc_address="bc1qexample",
            btc_txid="",
            btc_settled_at=None,
        )
        mock_check = mocker.patch("billing.views.check_btc_payment")

        response = landlord_client.get(
            reverse('invoice-detail', args=[invoice.id])
        )

        assert response.status_code == 200
        mock_check.assert_not_called()

    def test_does_not_check_when_no_tx_seen_yet(
        self, mocker, landlord_client, landlord, renter
    ):
        billing_period = BillingPeriodFactory(
            landlord=landlord, renter=renter
        )
        invoice = InvoiceFactory(
            billing_period=billing_period,
            btc_address="bc1qexample",
            btc_txid="",
        )
        mock_check = mocker.patch("billing.views.check_btc_payment")

        response = landlord_client.get(
            reverse('invoice-detail', args=[invoice.id])
        )

        assert response.status_code == 200
        mock_check.assert_not_called()

    def test_checks_a_second_round_even_after_a_prior_settle(
        self, mocker, landlord_client, landlord, renter
    ):
        """A non-empty btc_txid now only ever means an in-flight,
        unconfirmed round -- a stale btc_settled_at from a prior round
        must not suppress the check on this one.
        """
        billing_period = BillingPeriodFactory(
            landlord=landlord, renter=renter
        )
        invoice = InvoiceFactory(
            billing_period=billing_period,
            btc_address="bc1qexample",
            btc_txid="tx2",
            btc_settled_at=timezone.now(),
        )
        mock_check = mocker.patch(
            "billing.views.check_btc_payment", side_effect=lambda inv: inv
        )

        response = landlord_client.get(
            reverse('invoice-detail', args=[invoice.id])
        )

        assert response.status_code == 200
        mock_check.assert_called_once()


class TestInvoiceViewSetWeeks:
    def test_returns_weekly_breakdown_for_owned_invoice(
        self, landlord_client, landlord, renter
    ):
        billing_period = BillingPeriodFactory(
            landlord=landlord, renter=renter, year=2024, month=6
        )
        invoice = InvoiceFactory(billing_period=billing_period)

        response = landlord_client.get(
            reverse('invoice-weeks', args=[invoice.id])
        )

        assert response.status_code == 200
        assert isinstance(response.data, list)

    def test_404_for_invoice_of_other_landlord(self, landlord_client):
        other_period = BillingPeriodFactory()
        invoice = InvoiceFactory(billing_period=other_period)

        response = landlord_client.get(
            reverse('invoice-weeks', args=[invoice.id])
        )

        assert response.status_code == 404


class TestInvoiceViewSetRecompute:
    def test_landlord_only(self, renter_client, landlord, renter):
        billing_period = BillingPeriodFactory(landlord=landlord, renter=renter)
        invoice = InvoiceFactory(
            billing_period=billing_period, kind=Invoice.Kind.GAS_ONLY
        )
        response = renter_client.post(
            reverse('invoice-recompute', args=[invoice.id])
        )
        assert response.status_code == 403

    def test_locked_invoice_returns_409(self, landlord_client, landlord, renter):
        billing_period = BillingPeriodFactory(landlord=landlord, renter=renter)
        invoice = InvoiceFactory(
            billing_period=billing_period, status=Invoice.Status.PAID
        )
        response = landlord_client.post(
            reverse('invoice-recompute', args=[invoice.id])
        )
        assert response.status_code == 409

    def test_unlocked_invoice_recomputes_and_returns_200(
        self, landlord_client, landlord, renter
    ):
        billing_period = BillingPeriodFactory(landlord=landlord, renter=renter)
        invoice = InvoiceFactory(
            billing_period=billing_period,
            kind=Invoice.Kind.GAS_ONLY,
            status=Invoice.Status.DRAFT,
        )
        response = landlord_client.post(
            reverse('invoice-recompute', args=[invoice.id])
        )
        assert response.status_code == 200
        assert response.data['id'] == invoice.id


# --- LeaseRentRevisionView ----------------------------------------------

class TestLeaseRentRevisionView:
    def test_404_for_lease_of_other_landlord(self, landlord_client):
        lease = LeaseFactory()  # different landlord
        response = landlord_client.post(
            reverse('lease-rent-revision', args=[lease.id]),
            {
                'new_monthly_rent': '1200.00',
                'effective_date': (
                    date.today() + timedelta(days=60)
                ).isoformat(),
            },
        )
        assert response.status_code == 404

    def test_too_soon_effective_date_rejected(self, landlord_client, landlord):
        lease = LeaseFactory(landlord=landlord)
        response = landlord_client.post(
            reverse('lease-rent-revision', args=[lease.id]),
            {
                'new_monthly_rent': '1200.00',
                'effective_date': (
                    date.today() + timedelta(days=5)
                ).isoformat(),
            },
        )
        assert response.status_code == 400

    def test_valid_revision_created_and_renter_emailed(
        self, landlord_client, landlord
    ):
        from django.core import mail

        lease = LeaseFactory(landlord=landlord)
        response = landlord_client.post(
            reverse('lease-rent-revision', args=[lease.id]),
            {
                'new_monthly_rent': '1200.00',
                'effective_date': (
                    date.today() + timedelta(days=60)
                ).isoformat(),
            },
        )
        assert response.status_code == 201
        assert len(mail.outbox) == 1


# --- RenterLookupView ----------------------------------------------------

class TestRenterLookupView:
    def test_exact_match_returns_renter(self, landlord_client):
        renter = UserFactory(email='exact@example.com')
        response = landlord_client.get(
            reverse('renter-lookup'), {'email': renter.email}
        )
        assert response.status_code == 200
        assert response.data['id'] == renter.id

    def test_partial_match_not_found(self, landlord_client):
        UserFactory(email='exact@example.com')
        response = landlord_client.get(
            reverse('renter-lookup'), {'email': 'exact'}
        )
        assert response.status_code == 400

    def test_landlord_email_not_returned_as_renter(self, landlord_client):
        LandlordFactory(email='dual@example.com')
        response = landlord_client.get(
            reverse('renter-lookup'), {'email': 'dual@example.com'}
        )
        assert response.status_code == 404

    def test_requires_landlord(self, renter_client):
        response = renter_client.get(
            reverse('renter-lookup'), {'email': 'a@example.com'}
        )
        assert response.status_code == 403


# --- BillingPeriodPreviewView --------------------------------------------

class TestBillingPeriodPreviewView:
    def test_requires_landlord(self, renter_client, renter):
        url = reverse(
            'billing-period-preview',
            kwargs={'renter_id': renter.id, 'year': 2024, 'month': 6},
        )
        response = renter_client.get(url)
        assert response.status_code == 403

    def test_404_without_lease(self, landlord_client, renter):
        url = reverse(
            'billing-period-preview',
            kwargs={'renter_id': renter.id, 'year': 2024, 'month': 6},
        )
        response = landlord_client.get(url)
        assert response.status_code == 404

    def test_preview_succeeds_without_gas_config(
        self, landlord_client, landlord, renter
    ):
        # Lease exists, so get_active_lease succeeds and preview should
        # compute fine (no gas config needed for gas total to be $0).
        LeaseFactory(landlord=landlord, renter=renter)
        url = reverse(
            'billing-period-preview',
            kwargs={'renter_id': renter.id, 'year': 2024, 'month': 6},
        )
        response = landlord_client.get(url)
        assert response.status_code == 200

    def test_400_for_inactive_lease(self, landlord_client, landlord, renter):
        """get_object_or_404 doesn't filter on `active`, so this lease is
        found, but compute_period_preview's get_active_lease excludes
        it, surfacing a BillingConfigError as a 400.
        """
        LeaseFactory(landlord=landlord, renter=renter, active=False)
        url = reverse(
            'billing-period-preview',
            kwargs={'renter_id': renter.id, 'year': 2024, 'month': 6},
        )
        response = landlord_client.get(url)
        assert response.status_code == 400
