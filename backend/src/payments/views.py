import stripe
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.models import Invoice
from billing.permissions import IsLandlord
from payments.services import (
    LandlordNotOnboardedError,
    create_payment_intent_for_invoice,
    handle_account_updated,
    handle_payment_intent_succeeded,
    start_connect_onboarding,
)


class InvoicePaymentIntentView(APIView):
    """Returns a Stripe PaymentIntent client_secret for the renter to pay."""

    permission_classes = [IsAuthenticated]

    def post(self, request, invoice_id: int) -> Response:
        invoice = get_object_or_404(
            Invoice, id=invoice_id, billing_period__renter=request.user
        )
        if invoice.status == Invoice.Status.PAID:
            return Response(
                {'detail': 'Invoice is already paid.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            intent = create_payment_intent_for_invoice(invoice)
        except LandlordNotOnboardedError as exc:
            return Response(
                {'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        landlord = invoice.billing_period.landlord
        return Response(
            {
                'client_secret': intent.client_secret,
                'publishable_key': settings.STRIPE_PUBLISHABLE_KEY,
                'stripe_account_id': landlord.stripe_account_id,
            }
        )


class ConnectOnboardingView(APIView):
    """Starts (or resumes) the landlord's Stripe Connect onboarding."""

    permission_classes = [IsAuthenticated, IsLandlord]

    def post(self, request) -> Response:
        url = start_connect_onboarding(request.user)
        return Response({'onboarding_url': url})


class ConnectStatusView(APIView):
    """Reports the landlord's Stripe Connect onboarding status."""

    permission_classes = [IsAuthenticated, IsLandlord]

    def get(self, request) -> Response:
        return Response(
            {
                'connected': bool(request.user.stripe_account_id),
                'charges_enabled': request.user.stripe_charges_enabled,
            }
        )


class StripeWebhookView(APIView):
    """Receives Stripe events; no auth (Stripe calls this directly),
    signature verification stands in for auth instead.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request) -> Response:
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except (ValueError, stripe.SignatureVerificationError):
            return Response(status=status.HTTP_400_BAD_REQUEST)

        if event['type'] == 'payment_intent.succeeded':
            handle_payment_intent_succeeded(
                event['data']['object'],
                connected_account_id=event.get('account'),
            )

        return Response(status=status.HTTP_200_OK)


class ConnectWebhookView(APIView):
    """Receives Stripe Connect events (fired on connected accounts).

    Registered as a separate Dashboard webhook endpoint scoped to
    "events on connected accounts," with its own signing secret,
    since direct charges created on a connected account don't fire
    events on the platform's own webhook endpoint.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request) -> Response:
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_CONNECT_WEBHOOK_SECRET
            )
        except (ValueError, stripe.SignatureVerificationError):
            return Response(status=status.HTTP_400_BAD_REQUEST)

        if event['type'] == 'payment_intent.succeeded':
            handle_payment_intent_succeeded(
                event['data']['object'],
                connected_account_id=event.get('account'),
            )
        elif event['type'] == 'account.updated':
            handle_account_updated(event['data']['object'])

        return Response(status=status.HTTP_200_OK)
