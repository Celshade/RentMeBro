
from unittest.mock import Mock

import pytest
from django.urls import reverse

from billing.models import Invoice
from payments.services import (
    InvoiceAlreadyPaidError,
    LandlordNotOnboardedError,
)

pytestmark = pytest.mark.django_db


class TestInvoicePaymentIntentView:
    def test_requires_authentication(self, api_client, invoice):
        response = api_client.post(
            reverse('invoice-pay', args=[invoice.id])
        )
        assert response.status_code == 401

    def test_renter_gets_client_secret_for_own_invoice(
        self, api_client, mocker, renter, invoice
    ):
        mocker.patch(
            'payments.views.create_payment_intent_for_invoice',
            return_value=Mock(client_secret='secret_123'),
        )
        api_client.force_authenticate(user=renter)

        response = api_client.post(
            reverse('invoice-pay', args=[invoice.id])
        )

        assert response.status_code == 200
        assert response.data['client_secret'] == 'secret_123'

    def test_other_user_gets_404_for_someone_elses_invoice(
        self, api_client, invoice
    ):
        from accounts.tests.factories import UserFactory

        other_renter = UserFactory()
        api_client.force_authenticate(user=other_renter)

        response = api_client.post(
            reverse('invoice-pay', args=[invoice.id])
        )

        assert response.status_code == 404

    def test_already_paid_invoice_returns_400(
        self, api_client, renter, invoice
    ):
        invoice.status = Invoice.Status.PAID
        invoice.save()
        api_client.force_authenticate(user=renter)

        response = api_client.post(
            reverse('invoice-pay', args=[invoice.id])
        )

        assert response.status_code == 400

    def test_landlord_not_onboarded_returns_400(
        self, api_client, mocker, renter, invoice
    ):
        mocker.patch(
            'payments.views.create_payment_intent_for_invoice',
            side_effect=LandlordNotOnboardedError("not onboarded"),
        )
        api_client.force_authenticate(user=renter)

        response = api_client.post(
            reverse('invoice-pay', args=[invoice.id])
        )

        assert response.status_code == 400

    def test_already_succeeded_intent_returns_400(
        self, api_client, mocker, renter, invoice
    ):
        mocker.patch(
            'payments.views.create_payment_intent_for_invoice',
            side_effect=InvoiceAlreadyPaidError("already paid"),
        )
        api_client.force_authenticate(user=renter)

        response = api_client.post(
            reverse('invoice-pay', args=[invoice.id])
        )

        assert response.status_code == 400


class TestConnectOnboardingView:
    def test_requires_landlord(self, api_client, renter):
        api_client.force_authenticate(user=renter)
        response = api_client.post(reverse('connect-onboard'))
        assert response.status_code == 403

    def test_landlord_gets_onboarding_url(
        self, api_client, mocker, landlord
    ):
        mocker.patch(
            'payments.views.start_connect_onboarding',
            return_value='https://connect.stripe.com/setup/x',
        )
        api_client.force_authenticate(user=landlord)

        response = api_client.post(reverse('connect-onboard'))

        assert response.status_code == 200
        assert (
            response.data['onboarding_url']
            == 'https://connect.stripe.com/setup/x'
        )


class TestConnectStatusView:
    def test_requires_landlord(self, api_client, renter):
        api_client.force_authenticate(user=renter)
        response = api_client.get(reverse('connect-status'))
        assert response.status_code == 403

    def test_reports_connection_status(self, api_client, landlord):
        landlord.stripe_account_id = 'acct_1'
        landlord.stripe_charges_enabled = True
        landlord.save()
        api_client.force_authenticate(user=landlord)

        response = api_client.get(reverse('connect-status'))

        assert response.status_code == 200
        assert response.data == {'connected': True, 'charges_enabled': True}

    def test_refresh_pulls_live_status_from_stripe(
        self, api_client, mocker, landlord
    ):
        landlord.stripe_account_id = 'acct_1'
        landlord.stripe_charges_enabled = False
        landlord.save()
        mocker.patch(
            'payments.services.stripe.Account.retrieve',
            return_value={'id': 'acct_1', 'charges_enabled': True},
        )
        api_client.force_authenticate(user=landlord)

        response = api_client.get(
            reverse('connect-status'), {'refresh': 'true'}
        )

        assert response.status_code == 200
        assert response.data == {'connected': True, 'charges_enabled': True}
        landlord.refresh_from_db()
        assert landlord.stripe_charges_enabled is True

    def test_refresh_is_a_noop_before_onboarding_started(
        self, api_client, mocker, landlord
    ):
        retrieve = mocker.patch('payments.services.stripe.Account.retrieve')
        api_client.force_authenticate(user=landlord)

        response = api_client.get(
            reverse('connect-status'), {'refresh': 'true'}
        )

        assert response.status_code == 200
        assert response.data == {'connected': False, 'charges_enabled': False}
        retrieve.assert_not_called()


class TestStripeWebhookView:
    def test_valid_signature_succeeded_event_marks_invoice_paid(
        self, api_client, mocker, landlord, invoice
    ):
        landlord.stripe_account_id = 'acct_1'
        landlord.save()
        fake_event = {
            'type': 'payment_intent.succeeded',
            'account': 'acct_1',
            'data': {'object': {'metadata': {'invoice_id': str(invoice.id)}}},
        }
        mocker.patch(
            'payments.views.stripe.Webhook.construct_event',
            return_value=fake_event,
        )

        response = api_client.post(
            reverse('stripe-webhook'),
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='fake-sig',
        )

        assert response.status_code == 200
        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.PAID

    def test_invalid_signature_returns_400(self, api_client, mocker):
        import stripe

        mocker.patch(
            'payments.views.stripe.Webhook.construct_event',
            side_effect=stripe.SignatureVerificationError('bad sig', 'hdr'),
        )

        response = api_client.post(
            reverse('stripe-webhook'),
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='bad-sig',
        )

        assert response.status_code == 400

    def test_malformed_payload_returns_400(self, api_client, mocker):
        mocker.patch(
            'payments.views.stripe.Webhook.construct_event',
            side_effect=ValueError('bad payload'),
        )

        response = api_client.post(
            reverse('stripe-webhook'),
            data=b'not json',
            content_type='application/json',
        )

        assert response.status_code == 400

    def test_other_event_types_return_200_and_do_not_update_invoice(
        self, api_client, mocker, invoice
    ):
        fake_event = {
            'type': 'payment_intent.created',
            'data': {'object': {'metadata': {'invoice_id': str(invoice.id)}}},
        }
        mocker.patch(
            'payments.views.stripe.Webhook.construct_event',
            return_value=fake_event,
        )

        response = api_client.post(
            reverse('stripe-webhook'),
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='fake-sig',
        )

        assert response.status_code == 200
        invoice.refresh_from_db()
        assert invoice.status != Invoice.Status.PAID

    def test_no_authentication_required(self, api_client, mocker):
        mocker.patch(
            'payments.views.stripe.Webhook.construct_event',
            return_value={'type': 'unrelated.event', 'data': {'object': {}}},
        )
        response = api_client.post(
            reverse('stripe-webhook'),
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='fake-sig',
        )
        assert response.status_code == 200


class TestConnectWebhookView:
    def test_valid_signature_succeeded_event_marks_invoice_paid(
        self, api_client, mocker, landlord, invoice
    ):
        landlord.stripe_account_id = 'acct_1'
        landlord.save()
        fake_event = {
            'type': 'payment_intent.succeeded',
            'account': 'acct_1',
            'data': {'object': {'metadata': {'invoice_id': str(invoice.id)}}},
        }
        mocker.patch(
            'payments.views.stripe.Webhook.construct_event',
            return_value=fake_event,
        )

        response = api_client.post(
            reverse('stripe-connect-webhook'),
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='fake-sig',
        )

        assert response.status_code == 200
        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.PAID

    def test_succeeded_event_from_wrong_account_is_noop(
        self, api_client, mocker, landlord, invoice
    ):
        landlord.stripe_account_id = 'acct_1'
        landlord.save()
        fake_event = {
            'type': 'payment_intent.succeeded',
            'account': 'acct_someone_else',
            'data': {'object': {'metadata': {'invoice_id': str(invoice.id)}}},
        }
        mocker.patch(
            'payments.views.stripe.Webhook.construct_event',
            return_value=fake_event,
        )

        response = api_client.post(
            reverse('stripe-connect-webhook'),
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='fake-sig',
        )

        assert response.status_code == 200
        invoice.refresh_from_db()
        assert invoice.status != Invoice.Status.PAID

    def test_account_updated_event_syncs_charges_enabled(
        self, api_client, mocker, landlord
    ):
        landlord.stripe_account_id = 'acct_1'
        landlord.save()
        fake_event = {
            'type': 'account.updated',
            'data': {'object': {'id': 'acct_1', 'charges_enabled': True}},
        }
        mocker.patch(
            'payments.views.stripe.Webhook.construct_event',
            return_value=fake_event,
        )

        response = api_client.post(
            reverse('stripe-connect-webhook'),
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='fake-sig',
        )

        assert response.status_code == 200
        landlord.refresh_from_db()
        assert landlord.stripe_charges_enabled is True

    def test_invalid_signature_returns_400(self, api_client, mocker):
        import stripe

        mocker.patch(
            'payments.views.stripe.Webhook.construct_event',
            side_effect=stripe.SignatureVerificationError('bad sig', 'hdr'),
        )

        response = api_client.post(
            reverse('stripe-connect-webhook'),
            data=b'{}',
            content_type='application/json',
            HTTP_STRIPE_SIGNATURE='bad-sig',
        )

        assert response.status_code == 400
