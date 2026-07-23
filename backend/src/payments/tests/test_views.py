
from unittest.mock import Mock

import pytest
from django.urls import reverse

from billing.models import Invoice

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


class TestStripeWebhookView:
    def test_valid_signature_succeeded_event_marks_invoice_paid(
        self, api_client, mocker, invoice
    ):
        fake_event = {
            'type': 'payment_intent.succeeded',
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
