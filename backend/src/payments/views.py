import stripe
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.models import Invoice
from billing.permissions import IsLandlord
from billing.services import InvoiceLockedError
from payments.services import (
    BtcLineItemError,
    BtcNotEnabledError,
    InvoiceAlreadyPaidError,
    LandlordNotOnboardedError,
    NothingLeftToChargeError,
    attach_btc_payment,
    check_btc_payment,
    create_payment_intent_for_invoice,
    enable_btc_payments,
    get_btc_usd_price,
    handle_account_updated,
    handle_payment_intent_succeeded,
    initiate_btc_watch,
    refresh_connect_status,
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
        except InvoiceAlreadyPaidError as exc:
            return Response(
                {'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        except NothingLeftToChargeError as exc:
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
    """Reports the landlord's Stripe Connect onboarding status.

    Normally reads the DB-cached status kept in sync by the
    account.updated Connect webhook. Pass `?refresh=true` to pull the
    latest status directly from Stripe first, for callers that can't
    wait on webhook delivery (e.g. the onboarding return page).
    """

    permission_classes = [IsAuthenticated, IsLandlord]

    def get(self, request) -> Response:
        if request.query_params.get('refresh') == 'true':
            refresh_connect_status(request.user)
            request.user.refresh_from_db(fields=['stripe_charges_enabled'])
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


class BtcSettingsView(APIView):
    """Reports and enables the landlord's BTC payment option."""

    permission_classes = [IsAuthenticated, IsLandlord]

    def get(self, request) -> Response:
        return Response({"enabled": request.user.btc_payments_enabled})

    def post(self, request) -> Response:
        if request.data.get("agree") is not True:
            return Response(
                {"detail": "You must confirm before enabling BTC payments."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        enable_btc_payments(request.user)
        return Response({"enabled": True})


class BtcPriceView(APIView):
    """Reports the current BTC/USD price for manual amount entry."""

    permission_classes = [IsAuthenticated, IsLandlord]

    def get(self, request) -> Response:
        price = get_btc_usd_price()
        if price is None:
            return Response(
                {"detail": "BTC price is temporarily unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"usd": price})


class InvoiceBtcAttachView(APIView):
    """Attaches a BTC address to an invoice as a landlord.

    The renter's payment amount is no longer set here — it's generated
    and rate-locked from the current market price once the renter
    starts paying (see `InvoiceBtcWatchView`).
    """

    permission_classes = [IsAuthenticated, IsLandlord]

    def post(self, request, invoice_id: int) -> Response:
        invoice = get_object_or_404(
            Invoice,
            id=invoice_id,
            billing_period__landlord=request.user,
        )
        try:
            attach_btc_payment(
                invoice,
                request.data.get("address", ""),
                line_item_ids=request.data.get("line_items"),
            )
        except InvoiceLockedError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_409_CONFLICT
            )
        except (BtcNotEnabledError, BtcLineItemError) as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(
            {
                "btc_address": invoice.btc_address,
                "btc_line_items": list(
                    invoice.btc_line_items.values_list("id", flat=True)
                ),
            }
        )


def _btc_status_response(invoice: Invoice) -> Response:
    return Response(
        {
            "btc_address": invoice.btc_address,
            "btc_amount_sats": invoice.btc_amount_sats,
            "btc_watch_expires_at": invoice.btc_watch_expires_at,
            "remainder_owed_usd": invoice.remainder_owed_usd,
            "status": invoice.status,
        }
    )


class InvoiceBtcWatchView(APIView):
    """Starts (or restarts) the renter's BTC payment watch window."""

    permission_classes = [IsAuthenticated]

    def post(self, request, invoice_id: int) -> Response:
        invoice = get_object_or_404(
            Invoice, id=invoice_id, billing_period__renter=request.user
        )
        invoice = initiate_btc_watch(invoice)
        return _btc_status_response(invoice)


class InvoiceBtcCheckView(APIView):
    """Polls mempool.space for the renter's BTC payment status.

    Hit by the renter's browser every 60 seconds while the "Pay with
    BTC" panel is open.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, invoice_id: int) -> Response:
        invoice = get_object_or_404(
            Invoice, id=invoice_id, billing_period__renter=request.user
        )
        invoice = check_btc_payment(invoice)
        return _btc_status_response(invoice)
