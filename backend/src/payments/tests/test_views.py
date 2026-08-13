
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from django.urls import reverse
from django.utils import timezone

from billing.models import Invoice
from payments.services import (
    CardCancelNotAllowedError,
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
            return_value=Mock(
                client_secret='secret_123',
                status='requires_payment_method',
            ),
        )
        api_client.force_authenticate(user=renter)

        response = api_client.post(
            reverse('invoice-pay', args=[invoice.id])
        )

        assert response.status_code == 200
        assert response.data['client_secret'] == 'secret_123'
        assert response.data['intent_status'] == 'requires_payment_method'

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

    def test_requires_action_event_syncs_intent_state(
        self, api_client, mocker, landlord, invoice
    ):
        landlord.stripe_account_id = 'acct_1'
        landlord.save()
        invoice.stripe_payment_intent_id = 'pi_1'
        invoice.save()
        fake_event = {
            'type': 'payment_intent.requires_action',
            'account': 'acct_1',
            'data': {
                'object': {
                    'id': 'pi_1',
                    'status': 'requires_action',
                    'metadata': {'invoice_id': str(invoice.id)},
                }
            },
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
        assert invoice.stripe_intent_status == 'requires_action'

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

    def test_canceled_event_syncs_and_clears_round_line_items(
        self, api_client, mocker, landlord, invoice
    ):
        from billing.tests.factories import InvoiceLineItemFactory

        landlord.stripe_account_id = 'acct_1'
        landlord.save()
        invoice.stripe_payment_intent_id = 'pi_1'
        invoice.stripe_intent_status = 'requires_action'
        invoice.save()
        item = InvoiceLineItemFactory(invoice=invoice)
        invoice.stripe_round_line_items.set([item])
        fake_event = {
            'type': 'payment_intent.canceled',
            'account': 'acct_1',
            'data': {
                'object': {
                    'id': 'pi_1',
                    'status': 'canceled',
                    'metadata': {'invoice_id': str(invoice.id)},
                }
            },
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
        assert invoice.stripe_intent_status == 'canceled'
        assert invoice.stripe_round_line_items.exists() is False

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


class TestBtcSettingsView:
    def test_requires_authentication(self, api_client):
        response = api_client.get(reverse("btc-settings"))
        assert response.status_code == 401

    def test_requires_landlord(self, api_client, renter):
        api_client.force_authenticate(user=renter)
        response = api_client.get(reverse("btc-settings"))
        assert response.status_code == 403

    def test_get_reports_disabled_by_default(self, api_client, landlord):
        api_client.force_authenticate(user=landlord)
        response = api_client.get(reverse("btc-settings"))
        assert response.status_code == 200
        assert response.data["enabled"] is False

    def test_post_without_agree_returns_400(self, api_client, landlord):
        api_client.force_authenticate(user=landlord)
        response = api_client.post(reverse("btc-settings"), data={})
        assert response.status_code == 400
        landlord.refresh_from_db()
        assert landlord.btc_payments_enabled is False

    def test_post_with_agree_enables(self, api_client, landlord):
        api_client.force_authenticate(user=landlord)
        response = api_client.post(
            reverse("btc-settings"), data={"agree": True}, format="json"
        )
        assert response.status_code == 200
        landlord.refresh_from_db()
        assert landlord.btc_payments_enabled is True


class TestBtcPriceView:
    def test_requires_authentication(self, api_client):
        response = api_client.get(reverse("btc-price"))
        assert response.status_code == 401

    def test_requires_landlord(self, api_client, renter):
        api_client.force_authenticate(user=renter)
        response = api_client.get(reverse("btc-price"))
        assert response.status_code == 403

    def test_returns_price(self, api_client, landlord, mocker):
        mocker.patch(
            "payments.views.get_btc_usd_price", return_value=65000
        )
        api_client.force_authenticate(user=landlord)
        response = api_client.get(reverse("btc-price"))
        assert response.status_code == 200
        assert response.data["usd"] == 65000

    def test_unavailable_price_returns_503(self, api_client, landlord, mocker):
        mocker.patch("payments.views.get_btc_usd_price", return_value=None)
        api_client.force_authenticate(user=landlord)
        response = api_client.get(reverse("btc-price"))
        assert response.status_code == 503


class TestInvoiceBtcAttachView:
    def test_requires_landlord(self, api_client, renter, invoice):
        api_client.force_authenticate(user=renter)
        response = api_client.post(
            reverse("invoice-btc-attach", args=[invoice.id]),
            data={"address": "bc1qexample"},
        )
        assert response.status_code == 403

    def test_other_landlord_gets_404(self, api_client, invoice):
        from accounts.tests.factories import LandlordFactory

        other_landlord = LandlordFactory()
        api_client.force_authenticate(user=other_landlord)
        response = api_client.post(
            reverse("invoice-btc-attach", args=[invoice.id]),
            data={"address": "bc1qexample"},
        )
        assert response.status_code == 404

    def test_owning_landlord_attaches(self, api_client, landlord, invoice):
        landlord.btc_payments_enabled = True
        landlord.save()
        api_client.force_authenticate(user=landlord)

        response = api_client.post(
            reverse("invoice-btc-attach", args=[invoice.id]),
            data={"address": "bc1qexample"},
        )

        assert response.status_code == 200
        invoice.refresh_from_db()
        assert invoice.btc_address == "bc1qexample"
        assert invoice.btc_amount_sats is None

    def test_not_enabled_returns_400(self, api_client, landlord, invoice):
        api_client.force_authenticate(user=landlord)
        response = api_client.post(
            reverse("invoice-btc-attach", args=[invoice.id]),
            data={"address": "bc1qexample"},
        )
        assert response.status_code == 400

    def test_locked_invoice_returns_409(self, api_client, landlord, invoice):
        landlord.btc_payments_enabled = True
        landlord.save()
        invoice.status = Invoice.Status.PAID
        invoice.save()
        api_client.force_authenticate(user=landlord)

        response = api_client.post(
            reverse("invoice-btc-attach", args=[invoice.id]),
            data={"address": "bc1qexample"},
        )

        assert response.status_code == 409

    def test_scopes_to_posted_line_items(self, api_client, landlord, invoice):
        from billing.tests.factories import InvoiceLineItemFactory

        landlord.btc_payments_enabled = True
        landlord.save()
        line_item = InvoiceLineItemFactory(invoice=invoice)
        api_client.force_authenticate(user=landlord)

        response = api_client.post(
            reverse("invoice-btc-attach", args=[invoice.id]),
            data={"address": "bc1qexample", "line_items": [line_item.id]},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["btc_line_items"] == [line_item.id]
        invoice.refresh_from_db()
        assert list(invoice.btc_line_items.all()) == [line_item]

    def test_blank_address_detaches_and_clears_line_items(
        self, api_client, landlord, invoice
    ):
        from billing.tests.factories import InvoiceLineItemFactory

        landlord.btc_payments_enabled = True
        landlord.save()
        line_item = InvoiceLineItemFactory(invoice=invoice)
        api_client.force_authenticate(user=landlord)
        api_client.post(
            reverse("invoice-btc-attach", args=[invoice.id]),
            data={"address": "bc1qexample", "line_items": [line_item.id]},
            format="json",
        )

        response = api_client.post(
            reverse("invoice-btc-attach", args=[invoice.id]),
            data={"address": "", "line_items": []},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["btc_address"] == ""
        assert response.data["btc_line_items"] == []
        invoice.refresh_from_db()
        assert invoice.btc_address == ""
        assert invoice.btc_line_items.exists() is False

    def test_live_round_item_returns_400_with_service_detail(
        self, api_client, landlord, invoice
    ):
        """A live quote freezes the item it covers -- re-scoping away
        from it goes through `BtcLineItemError`, not the PAID/VOID
        `InvoiceLockedError` path `test_locked_invoice_returns_409`
        covers.
        """
        from billing.tests.factories import InvoiceLineItemFactory

        landlord.btc_payments_enabled = True
        landlord.save()
        line_item = InvoiceLineItemFactory(invoice=invoice)
        invoice.btc_address = "bc1qexample"
        invoice.btc_watch_expires_at = timezone.now() + timedelta(minutes=5)
        invoice.save()
        invoice.btc_line_items.set([line_item])
        invoice.btc_round_line_items.set([line_item])
        api_client.force_authenticate(user=landlord)

        response = api_client.post(
            reverse("invoice-btc-attach", args=[invoice.id]),
            data={"address": "bc1qexample", "line_items": []},
            format="json",
        )

        assert response.status_code == 400
        assert str(line_item.id) in response.data["detail"]
        assert "in flight" in response.data["detail"]


class TestInvoiceBtcWatchView:
    def test_requires_authentication(self, api_client, invoice):
        response = api_client.post(
            reverse("invoice-btc-watch", args=[invoice.id])
        )
        assert response.status_code == 401

    def test_other_user_gets_404(self, api_client, invoice):
        from accounts.tests.factories import UserFactory

        other_renter = UserFactory()
        api_client.force_authenticate(user=other_renter)
        response = api_client.post(
            reverse("invoice-btc-watch", args=[invoice.id])
        )
        assert response.status_code == 404

    def test_starts_watch_for_own_invoice(
        self, api_client, renter, invoice, mocker
    ):
        from billing.tests.factories import InvoiceLineItemFactory

        item = InvoiceLineItemFactory(invoice=invoice)
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )
        invoice.status = Invoice.Status.SENT
        invoice.btc_address = "bc1qexample"
        invoice.save()
        invoice.btc_line_items.set([item])
        api_client.force_authenticate(user=renter)

        response = api_client.post(
            reverse("invoice-btc-watch", args=[invoice.id])
        )

        assert response.status_code == 200
        assert response.data["btc_watch_expires_at"] is not None

    def test_pay_full_quotes_unassigned_item(
        self, api_client, renter, invoice, mocker
    ):
        from billing.tests.factories import InvoiceLineItemFactory

        item = InvoiceLineItemFactory(invoice=invoice)
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )
        invoice.status = Invoice.Status.SENT
        invoice.btc_address = "bc1qexample"
        invoice.save()
        api_client.force_authenticate(user=renter)

        response = api_client.post(
            reverse("invoice-btc-watch", args=[invoice.id]),
            {"pay_full": True},
        )

        assert response.status_code == 200
        assert response.data["btc_watch_expires_at"] is not None
        assert response.data["line_items"] == [item.id]

    def test_no_btc_address_returns_409(
        self, api_client, renter, invoice, mocker
    ):
        from billing.tests.factories import InvoiceLineItemFactory

        InvoiceLineItemFactory(invoice=invoice)
        mocker.patch(
            "payments.services.get_btc_usd_price", return_value=50000
        )
        invoice.status = Invoice.Status.SENT
        invoice.save()
        api_client.force_authenticate(user=renter)

        response = api_client.post(
            reverse("invoice-btc-watch", args=[invoice.id])
        )

        assert response.status_code == 409


class TestInvoiceBtcCheckView:
    def test_requires_authentication(self, api_client, invoice):
        response = api_client.post(
            reverse("invoice-btc-check", args=[invoice.id])
        )
        assert response.status_code == 401

    def test_returns_current_status_for_own_invoice(
        self, api_client, renter, invoice
    ):
        api_client.force_authenticate(user=renter)

        response = api_client.post(
            reverse("invoice-btc-check", args=[invoice.id])
        )

        assert response.status_code == 200
        assert response.data["status"] == invoice.status


class TestInvoiceBtcStatusView:
    """Read-only counterpart to InvoiceBtcWatchView: opening the panel
    must not mint a quote or spend against mempool.space's rate limit.
    """

    def test_requires_authentication(self, api_client, invoice):
        response = api_client.get(
            reverse("invoice-btc-status", args=[invoice.id])
        )
        assert response.status_code == 401

    def test_other_user_gets_404(self, api_client, invoice):
        from accounts.tests.factories import UserFactory

        other_renter = UserFactory()
        api_client.force_authenticate(user=other_renter)
        response = api_client.get(
            reverse("invoice-btc-status", args=[invoice.id])
        )
        assert response.status_code == 404

    def test_creates_no_quote_and_hits_no_mempool_endpoint(
        self, api_client, mocker, renter, invoice
    ):
        mock_price = mocker.patch(
            "payments.services.get_btc_usd_price"
        )
        mock_get = mocker.patch("payments.services.requests.get")
        api_client.force_authenticate(user=renter)

        response = api_client.get(
            reverse("invoice-btc-status", args=[invoice.id])
        )

        assert response.status_code == 200
        assert response.data["btc_amount_sats"] is None
        assert response.data["line_items"] == []
        mock_price.assert_not_called()
        mock_get.assert_not_called()

    def test_live_quote_survives_a_get_untouched(
        self, api_client, mocker, renter, invoice
    ):
        """Bug 2: a GET here must never restamp `btc_watch_expires_at`
        or `btc_amount_sats` -- this is the exact field pair that
        regression clobbered.
        """
        from billing.tests.factories import InvoiceLineItemFactory

        item = InvoiceLineItemFactory(invoice=invoice)
        invoice.status = Invoice.Status.SENT
        invoice.btc_address = "bc1qexample"
        invoice.btc_amount_sats = 12345
        invoice.btc_watch_expires_at = timezone.now() + timedelta(minutes=5)
        invoice.save()
        invoice.btc_line_items.set([item])
        invoice.btc_round_line_items.set([item])
        mock_price = mocker.patch("payments.services.get_btc_usd_price")
        mock_get = mocker.patch("payments.services.requests.get")
        api_client.force_authenticate(user=renter)

        response = api_client.get(
            reverse("invoice-btc-status", args=[invoice.id])
        )

        assert response.status_code == 200
        invoice.refresh_from_db()
        assert invoice.btc_amount_sats == 12345
        assert response.data["btc_amount_sats"] == 12345
        mock_price.assert_not_called()
        mock_get.assert_not_called()

    def test_live_round_reports_the_frozen_snapshot_not_live_scope(
        self, api_client, renter, invoice
    ):
        """`line_items` must come from `btc_round_line_items` while a
        round is live, not the live `btc_scope_line_items` -- the two
        diverge the moment a landlord re-scopes mid-round.
        """
        from billing.tests.factories import InvoiceLineItemFactory

        item_a = InvoiceLineItemFactory(invoice=invoice)
        item_b = InvoiceLineItemFactory(invoice=invoice)
        invoice.status = Invoice.Status.SENT
        invoice.btc_address = "bc1qexample"
        invoice.btc_watch_expires_at = timezone.now() + timedelta(minutes=5)
        invoice.save()
        # The round was quoted against both items ...
        invoice.btc_round_line_items.set([item_a, item_b])
        # ... but the landlord has since re-scoped down to just one.
        invoice.btc_line_items.set([item_a])
        api_client.force_authenticate(user=renter)

        response = api_client.get(
            reverse("invoice-btc-status", args=[invoice.id])
        )

        assert response.status_code == 200
        assert response.data["line_items"] == sorted(
            [item_a.id, item_b.id]
        )


class TestInvoiceBtcCancelView:
    def test_requires_authentication(self, api_client, invoice):
        response = api_client.post(
            reverse("invoice-btc-cancel", args=[invoice.id])
        )
        assert response.status_code == 401

    def test_other_user_gets_404(self, api_client, invoice):
        from accounts.tests.factories import UserFactory

        other_renter = UserFactory()
        api_client.force_authenticate(user=other_renter)
        response = api_client.post(
            reverse("invoice-btc-cancel", args=[invoice.id])
        )
        assert response.status_code == 404

    def test_landlord_gets_404(self, api_client, landlord, invoice):
        """No landlord route exists for this -- a landlord must never
        interfere with a pending renter payment.
        """
        api_client.force_authenticate(user=landlord)
        response = api_client.post(
            reverse("invoice-btc-cancel", args=[invoice.id])
        )
        assert response.status_code == 404

    def test_cancels_the_live_quote(
        self, api_client, renter, invoice
    ):
        from billing.tests.factories import InvoiceLineItemFactory

        item = InvoiceLineItemFactory(invoice=invoice)
        invoice.btc_amount_sats = 400000
        invoice.btc_watch_expires_at = timezone.now()
        invoice.save(
            update_fields=["btc_amount_sats", "btc_watch_expires_at"]
        )
        invoice.btc_round_line_items.set([item])
        api_client.force_authenticate(user=renter)

        response = api_client.post(
            reverse("invoice-btc-cancel", args=[invoice.id])
        )

        assert response.status_code == 200
        assert response.data["btc_amount_sats"] is None
        invoice.refresh_from_db()
        assert invoice.btc_amount_sats is None
        assert invoice.btc_round_line_items.exists() is False

    def test_409_when_a_tx_has_already_been_seen(
        self, api_client, renter, invoice
    ):
        invoice.btc_txid = "tx1"
        invoice.save(update_fields=["btc_txid"])
        api_client.force_authenticate(user=renter)

        response = api_client.post(
            reverse("invoice-btc-cancel", args=[invoice.id])
        )

        assert response.status_code == 409


class TestInvoicePaymentCancelView:
    def test_requires_authentication(self, api_client, invoice):
        response = api_client.post(
            reverse("invoice-pay-cancel", args=[invoice.id])
        )
        assert response.status_code == 401

    def test_other_user_gets_404(self, api_client, invoice):
        from accounts.tests.factories import UserFactory

        other_renter = UserFactory()
        api_client.force_authenticate(user=other_renter)
        response = api_client.post(
            reverse("invoice-pay-cancel", args=[invoice.id])
        )
        assert response.status_code == 404

    def test_landlord_gets_404(self, api_client, landlord, invoice):
        """No landlord route exists for this -- a landlord must never
        interfere with a pending renter payment.
        """
        api_client.force_authenticate(user=landlord)
        response = api_client.post(
            reverse("invoice-pay-cancel", args=[invoice.id])
        )
        assert response.status_code == 404

    def test_cancels_for_own_invoice(
        self, api_client, mocker, renter, invoice
    ):
        mocker.patch(
            "payments.views.cancel_card_payment_attempt",
            return_value=invoice,
        )
        api_client.force_authenticate(user=renter)

        response = api_client.post(
            reverse("invoice-pay-cancel", args=[invoice.id])
        )

        assert response.status_code == 200

    def test_not_allowed_returns_409(
        self, api_client, mocker, renter, invoice
    ):
        mocker.patch(
            "payments.views.cancel_card_payment_attempt",
            side_effect=CardCancelNotAllowedError("nope"),
        )
        api_client.force_authenticate(user=renter)

        response = api_client.post(
            reverse("invoice-pay-cancel", args=[invoice.id])
        )

        assert response.status_code == 409


class TestInvoiceLineItemPaymentLockView:
    def test_requires_landlord(self, api_client, renter, invoice):
        from billing.tests.factories import InvoiceLineItemFactory

        line_item = InvoiceLineItemFactory(invoice=invoice)
        api_client.force_authenticate(user=renter)

        response = api_client.post(
            reverse(
                "invoice-line-item-payment-lock",
                args=[invoice.id, line_item.id],
            ),
            data={"payment_lock": "card"},
        )

        assert response.status_code == 403

    def test_other_landlord_gets_404(self, api_client, invoice):
        from accounts.tests.factories import LandlordFactory
        from billing.tests.factories import InvoiceLineItemFactory

        line_item = InvoiceLineItemFactory(invoice=invoice)
        other_landlord = LandlordFactory()
        api_client.force_authenticate(user=other_landlord)

        response = api_client.post(
            reverse(
                "invoice-line-item-payment-lock",
                args=[invoice.id, line_item.id],
            ),
            data={"payment_lock": "card"},
        )

        assert response.status_code == 404

    def test_owning_landlord_locks_and_returns_full_invoice(
        self, api_client, landlord, invoice
    ):
        from billing.tests.factories import InvoiceLineItemFactory

        line_item = InvoiceLineItemFactory(invoice=invoice)
        api_client.force_authenticate(user=landlord)

        response = api_client.post(
            reverse(
                "invoice-line-item-payment-lock",
                args=[invoice.id, line_item.id],
            ),
            data={"payment_lock": "card"},
        )

        assert response.status_code == 200
        assert response.data["id"] == invoice.id
        assert "line_items" in response.data

    def test_stray_line_item_returns_400(
        self, api_client, landlord, invoice
    ):
        from billing.tests.factories import InvoiceLineItemFactory

        other_invoice_item = InvoiceLineItemFactory()
        api_client.force_authenticate(user=landlord)

        response = api_client.post(
            reverse(
                "invoice-line-item-payment-lock",
                args=[invoice.id, other_invoice_item.id],
            ),
            data={"payment_lock": "card"},
        )

        assert response.status_code == 400

    def test_frozen_item_returns_409_with_service_detail(
        self, api_client, landlord, invoice
    ):
        from billing.tests.factories import InvoiceLineItemFactory

        line_item = InvoiceLineItemFactory(invoice=invoice)
        invoice.btc_address = "bc1qexample"
        invoice.btc_watch_expires_at = timezone.now() + timedelta(minutes=5)
        invoice.save()
        invoice.btc_line_items.set([line_item])
        invoice.btc_round_line_items.set([line_item])
        api_client.force_authenticate(user=landlord)

        response = api_client.post(
            reverse(
                "invoice-line-item-payment-lock",
                args=[invoice.id, line_item.id],
            ),
            data={"payment_lock": "card"},
        )

        assert response.status_code == 409
        assert str(line_item.id) in response.data["detail"]
        assert "in flight" in response.data["detail"]

    def test_lapsed_quote_unfreezes_the_item(
        self, api_client, landlord, invoice
    ):
        """PR #5 Test plan L99: the freeze from a live quote must
        release once the quote lapses -- `set_line_item_payment_lock`
        calls `refresh_payment_state` first, so a lapsed watch with no
        settling tx never shows up in `frozen_line_item_ids`.
        """
        from billing.tests.factories import InvoiceLineItemFactory

        line_item = InvoiceLineItemFactory(invoice=invoice)
        invoice.btc_address = "bc1qexample"
        invoice.btc_watch_expires_at = timezone.now() - timedelta(minutes=30)
        invoice.save()
        invoice.btc_line_items.set([line_item])
        invoice.btc_round_line_items.set([line_item])
        api_client.force_authenticate(user=landlord)

        response = api_client.post(
            reverse(
                "invoice-line-item-payment-lock",
                args=[invoice.id, line_item.id],
            ),
            data={"payment_lock": "card"},
        )

        assert response.status_code == 200

    def test_underpaid_item_unfreezes_the_item(
        self, api_client, landlord, invoice
    ):
        """PR #5 Test plan L99: an UNDERPAID round clears
        `btc_watch_expires_at` and never sets `btc_txid`, so the item
        it covered is no longer in flight either.
        """
        from billing.tests.factories import InvoiceLineItemFactory

        line_item = InvoiceLineItemFactory(invoice=invoice)
        invoice.status = Invoice.Status.UNDERPAID
        invoice.btc_address = "bc1qexample"
        invoice.remainder_owed_usd = Decimal("35.00")
        invoice.save()
        invoice.btc_line_items.set([line_item])
        invoice.btc_round_line_items.set([line_item])
        api_client.force_authenticate(user=landlord)

        response = api_client.post(
            reverse(
                "invoice-line-item-payment-lock",
                args=[invoice.id, line_item.id],
            ),
            data={"payment_lock": "card"},
        )

        assert response.status_code == 200


class TestInvoiceLineItemMarkPaidView:
    def test_requires_landlord(self, api_client, renter, invoice):
        from billing.tests.factories import InvoiceLineItemFactory

        line_item = InvoiceLineItemFactory(invoice=invoice)
        api_client.force_authenticate(user=renter)

        response = api_client.post(
            reverse(
                "invoice-line-item-mark-paid",
                args=[invoice.id, line_item.id],
            ),
            data={"rail": "cash"},
        )

        assert response.status_code == 403

    def test_other_landlord_gets_404(self, api_client, invoice):
        from accounts.tests.factories import LandlordFactory
        from billing.tests.factories import InvoiceLineItemFactory

        line_item = InvoiceLineItemFactory(invoice=invoice)
        other_landlord = LandlordFactory()
        api_client.force_authenticate(user=other_landlord)

        response = api_client.post(
            reverse(
                "invoice-line-item-mark-paid",
                args=[invoice.id, line_item.id],
            ),
            data={"rail": "cash"},
        )

        assert response.status_code == 404

    def test_owning_landlord_marks_paid_and_returns_full_invoice(
        self, api_client, landlord, invoice
    ):
        from billing.tests.factories import InvoiceLineItemFactory

        line_item = InvoiceLineItemFactory(invoice=invoice)
        api_client.force_authenticate(user=landlord)

        response = api_client.post(
            reverse(
                "invoice-line-item-mark-paid",
                args=[invoice.id, line_item.id],
            ),
            data={"rail": "cash", "note": "Handed over at the door"},
        )

        assert response.status_code == 200
        assert response.data["id"] == invoice.id
        assert line_item.id in response.data["paid_line_items"]
        settlement = response.data["settlements"][0]
        assert settlement["rail"] == "cash"

    def test_invalid_rail_returns_400(self, api_client, landlord, invoice):
        from billing.tests.factories import InvoiceLineItemFactory

        line_item = InvoiceLineItemFactory(invoice=invoice)
        api_client.force_authenticate(user=landlord)

        response = api_client.post(
            reverse(
                "invoice-line-item-mark-paid",
                args=[invoice.id, line_item.id],
            ),
            data={"rail": "btc"},
        )

        assert response.status_code == 400

    def test_stray_line_item_returns_400(
        self, api_client, landlord, invoice
    ):
        from billing.tests.factories import InvoiceLineItemFactory

        other_invoice_item = InvoiceLineItemFactory()
        api_client.force_authenticate(user=landlord)

        response = api_client.post(
            reverse(
                "invoice-line-item-mark-paid",
                args=[invoice.id, other_invoice_item.id],
            ),
            data={"rail": "cash"},
        )

        assert response.status_code == 400

    def test_already_paid_item_returns_409(
        self, api_client, landlord, invoice
    ):
        from billing.tests.factories import InvoiceLineItemFactory

        line_item = InvoiceLineItemFactory(invoice=invoice)
        api_client.force_authenticate(user=landlord)
        api_client.post(
            reverse(
                "invoice-line-item-mark-paid",
                args=[invoice.id, line_item.id],
            ),
            data={"rail": "cash"},
        )

        response = api_client.post(
            reverse(
                "invoice-line-item-mark-paid",
                args=[invoice.id, line_item.id],
            ),
            data={"rail": "check"},
        )

        assert response.status_code == 409
