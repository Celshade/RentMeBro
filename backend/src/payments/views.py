import stripe
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.models import Invoice
from payments.services import (
    create_payment_intent_for_invoice,
    handle_payment_intent_succeeded,
)


class InvoicePaymentIntentView(APIView):
    """Returns a Stripe PaymentIntent client_secret for the renter to pay."""

    permission_classes = [IsAuthenticated]

    def post(self, request, invoice_id: int) -> Response:
        invoice = get_object_or_404(Invoice, id=invoice_id)
        if request.user.id != invoice.lease.renter_id:
            return Response(status=status.HTTP_403_FORBIDDEN)
        if invoice.status == Invoice.Status.PAID:
            return Response(
                {'detail': 'Invoice is already paid.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        intent = create_payment_intent_for_invoice(invoice)
        return Response(
            {
                'client_secret': intent.client_secret,
                'publishable_key': settings.STRIPE_PUBLISHABLE_KEY,
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
            handle_payment_intent_succeeded(event['data']['object'])

        return Response(status=status.HTTP_200_OK)
