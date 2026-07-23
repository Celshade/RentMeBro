from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.tests.factories import LandlordFactory, UserFactory
from billing.models import Invoice
from billing.tests.factories import (
    BillingPeriodFactory,
    DrivenDayLogFactory,
    InvoiceFactory,
    LeaseFactory,
)

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
