import stripe
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.models import Invoice
from billing.permissions import IsLandlord
from billing.serializers import InvoiceSerializer
from billing.services import InvoiceLockedError
from payments.services import (
    BtcLineItemError,
    BtcNotEnabledError,
    BtcWatchCancelError,
    CardCancelNotAllowedError,
    InvoiceAlreadyPaidError,
    LandlordNotOnboardedError,
    InvalidManualRailError,
    ManualSettlementError,
    NothingLeftToChargeError,
    PaymentLockError,
    _invoice_usd_owed,
    attach_btc_payment,
    cancel_btc_watch,
    cancel_card_payment_attempt,
    check_btc_payment,
    create_payment_intent_for_invoice,
    enable_btc_payments,
    get_btc_usd_price,
    handle_account_updated,
    handle_payment_intent_state_change,
    handle_payment_intent_succeeded,
    initiate_btc_watch,
    mark_line_item_paid_manually,
    refresh_connect_status,
    set_line_item_payment_lock,
    start_connect_onboarding,
)

# PaymentIntent webhook events that change a card round's state without
# settling it -- dispatched to handle_payment_intent_state_change so
# stripe_round_expires_at stays accurate without waiting on a poll.
_INTENT_STATE_CHANGE_EVENTS = frozenset(
    {
        'payment_intent.requires_action',
        'payment_intent.processing',
        'payment_intent.payment_failed',
        'payment_intent.canceled',
    }
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

        pay_full = bool(request.data.get('pay_full', False))
        try:
            intent = create_payment_intent_for_invoice(
                invoice, pay_full=pay_full
            )
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
                {'detail': str(exc)}, status=status.HTTP_409_CONFLICT
            )
        landlord = invoice.billing_period.landlord
        return Response(
            {
                'client_secret': intent.client_secret,
                'publishable_key': settings.STRIPE_PUBLISHABLE_KEY,
                'stripe_account_id': landlord.stripe_account_id,
            }
        )


class InvoicePaymentCancelView(APIView):
    """Cancels the renter's in-flight Cash App attempt at their own
    request.

    No landlord route exists for this -- a landlord must never
    interfere with a pending renter payment.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, invoice_id: int) -> Response:
        invoice = get_object_or_404(
            Invoice, id=invoice_id, billing_period__renter=request.user
        )
        try:
            invoice = cancel_card_payment_attempt(invoice)
        except CardCancelNotAllowedError as exc:
            return Response(
                {'detail': str(exc)}, status=status.HTTP_409_CONFLICT
            )
        return Response(InvoiceSerializer(invoice).data)


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
        elif event['type'] in _INTENT_STATE_CHANGE_EVENTS:
            handle_payment_intent_state_change(
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
        elif event['type'] in _INTENT_STATE_CHANGE_EVENTS:
            handle_payment_intent_state_change(
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


class InvoiceLineItemPaymentLockView(APIView):
    """Sets (or clears) a line item's payment-method lock as a landlord.

    The only way a rail may be taken off a charge -- see
    `payments.services.set_line_item_payment_lock`.
    """

    permission_classes = [IsAuthenticated, IsLandlord]

    def post(self, request, invoice_id: int, line_item_id: int) -> Response:
        invoice = get_object_or_404(
            Invoice,
            id=invoice_id,
            billing_period__landlord=request.user,
        )
        try:
            invoice = set_line_item_payment_lock(
                invoice, line_item_id, request.data.get("payment_lock", "")
            )
        except BtcLineItemError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        except PaymentLockError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_409_CONFLICT
            )
        return Response(InvoiceSerializer(invoice).data)


class InvoiceLineItemMarkPaidView(APIView):
    """Records a landlord-attested payment taken outside either rail.

    Separate from `InvoiceLineItemPaymentLockView` on purpose -- this
    is a manual settlement, not a rail lock.
    """

    permission_classes = [IsAuthenticated, IsLandlord]

    def post(self, request, invoice_id: int, line_item_id: int) -> Response:
        invoice = get_object_or_404(
            Invoice,
            id=invoice_id,
            billing_period__landlord=request.user,
        )
        try:
            invoice = mark_line_item_paid_manually(
                invoice,
                line_item_id,
                request.data.get("rail", ""),
                request.data.get("note", ""),
            )
        except (BtcLineItemError, InvalidManualRailError) as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        except ManualSettlementError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_409_CONFLICT
            )
        return Response(InvoiceSerializer(invoice).data)


def _btc_status_response(invoice: Invoice) -> Response:
    if invoice.btc_round_is_live:
        scoped_items = invoice.btc_round_line_items.all()
    else:
        scoped_items = invoice.btc_scope_line_items
    return Response(
        {
            "btc_address": invoice.btc_address,
            "btc_amount_sats": invoice.btc_amount_sats,
            "btc_watch_expires_at": invoice.btc_watch_expires_at,
            "btc_txid": invoice.btc_txid,
            "btc_settled_at": invoice.btc_settled_at,
            "remainder_owed_usd": invoice.remainder_owed_usd,
            "btc_owed_usd": _invoice_usd_owed(invoice),
            "status": invoice.status,
            "line_items": sorted(item.id for item in scoped_items),
        }
    )


class InvoiceBtcWatchView(APIView):
    """Starts (or restarts) the renter's BTC payment watch window."""

    permission_classes = [IsAuthenticated]

    def post(self, request, invoice_id: int) -> Response:
        invoice = get_object_or_404(
            Invoice, id=invoice_id, billing_period__renter=request.user
        )
        pay_full = bool(request.data.get('pay_full', False))
        invoice = initiate_btc_watch(invoice, pay_full=pay_full)
        return _btc_status_response(invoice)


class InvoiceBtcStatusView(APIView):
    """Reports the renter's current BTC payment status with no side
    effects.

    Deliberately distinct from `InvoiceBtcCheckView`, which hits
    mempool.space on every call -- this is what lets the "Pay with
    BTC" panel open without minting a quote or spending against an
    undocumented rate limit just because a tab was opened.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, invoice_id: int) -> Response:
        invoice = get_object_or_404(
            Invoice, id=invoice_id, billing_period__renter=request.user
        )
        return _btc_status_response(invoice)


class InvoiceBtcCancelView(APIView):
    """Cancels the renter's live BTC quote at their own request.

    No landlord route exists for this -- a landlord must never
    interfere with a pending renter payment.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, invoice_id: int) -> Response:
        invoice = get_object_or_404(
            Invoice, id=invoice_id, billing_period__renter=request.user
        )
        try:
            invoice = cancel_btc_watch(invoice)
        except BtcWatchCancelError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_409_CONFLICT
            )
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
