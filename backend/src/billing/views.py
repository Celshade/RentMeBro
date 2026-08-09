from django.db.models import Q, QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.serializers import UserSerializer
from billing import services
from billing.models import (
    DrivenDayLog,
    GasPriceEntry,
    Invoice,
    Lease,
    MileageProfile,
)
from billing.permissions import IsLandlord
from billing.serializers import (
    DrivenDayLogSerializer,
    GasPriceEntrySerializer,
    InvoiceCreateSerializer,
    InvoiceSerializer,
    InvoiceWeekSerializer,
    LeaseRentRevisionSerializer,
    LeaseSerializer,
    MileageProfileSerializer,
    PeriodPreviewSerializer,
    RenterLookupQuerySerializer,
)
from payments.services import check_btc_payment


class LeaseViewSet(viewsets.ModelViewSet):
    serializer_class = LeaseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[Lease]:
        user = self.request.user
        return Lease.objects.filter(Q(landlord=user) | Q(renter=user))

    def get_permissions(self) -> list[BasePermission]:
        if self.action == 'create':
            return [IsAuthenticated(), IsLandlord()]
        return super().get_permissions()


class DrivenDayLogViewSet(viewsets.ModelViewSet):
    """Landlords log driven days for a renter; renters have read-only access."""

    serializer_class = DrivenDayLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[DrivenDayLog]:
        user = self.request.user
        return DrivenDayLog.objects.filter(Q(landlord=user) | Q(renter=user))

    def get_permissions(self) -> list[BasePermission]:
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsAuthenticated(), IsLandlord()]
        return super().get_permissions()


class MileageProfileViewSet(viewsets.ModelViewSet):
    serializer_class = MileageProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[MileageProfile]:
        user = self.request.user
        return MileageProfile.objects.filter(Q(landlord=user) | Q(renter=user))

    def get_permissions(self) -> list[BasePermission]:
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsAuthenticated(), IsLandlord()]
        return super().get_permissions()


class GasPriceEntryViewSet(viewsets.ModelViewSet):
    serializer_class = GasPriceEntrySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[GasPriceEntry]:
        user = self.request.user
        return GasPriceEntry.objects.filter(Q(landlord=user) | Q(renter=user))

    def get_permissions(self) -> list[BasePermission]:
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsAuthenticated(), IsLandlord()]
        return super().get_permissions()


class InvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[Invoice]:
        user = self.request.user
        return Invoice.objects.filter(
            Q(billing_period__landlord=user) | Q(billing_period__renter=user)
        ).prefetch_related(
            'line_items',
            'btc_line_items',
            'btc_round_line_items',
            'stripe_round_line_items',
            'settlements__line_items',
        )

    def retrieve(self, request, *args, **kwargs) -> Response:
        """Serves a single invoice, checking a pending BTC tx first.

        The renter's browser is otherwise the only thing that ever
        polls mempool.space, so a payment that confirms after the tab
        closes would never get settled. Scoped to the one case that
        matters -- a tx already seen but not yet confirmed -- so this
        costs nothing on every other invoice, and never runs
        `_reconcile_lapsed_watch` (that consumes the renter's quote and
        belongs to the renter explicitly restarting a watch, not to a
        landlord opening a page). Deliberately not on `list`, which
        would otherwise fan out to one mempool.space request per
        invoice on a dashboard page load.
        """
        invoice = self.get_object()
        if invoice.btc_address and invoice.btc_txid:
            invoice = check_btc_payment(invoice)
        serializer = self.get_serializer(invoice)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs) -> Response:
        serializer = InvoiceCreateSerializer(
            data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        try:
            invoice = services.generate_invoice(
                landlord=request.user,
                renter=serializer.validated_data['renter'],
                year=serializer.validated_data['year'],
                month=serializer.validated_data['month'],
                kind=serializer.validated_data['kind'],
                due_date=serializer.validated_data.get('due_date'),
            )
        except services.InvoiceAlreadyExistsError as exc:
            return Response(
                {'detail': str(exc)}, status=status.HTTP_409_CONFLICT
            )
        except services.BillingConfigError as exc:
            return Response(
                {'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(
            InvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED
        )

    def get_permissions(self) -> list[BasePermission]:
        if self.action == 'create':
            return [IsAuthenticated(), IsLandlord()]
        return super().get_permissions()

    @action(detail=True, methods=['get'])
    def weeks(self, request, pk=None) -> Response:
        """Returns the invoice's driven days grouped into billed weeks."""
        invoice = self.get_object()
        period = invoice.billing_period
        weeks = services.compute_period_weekly_breakdown(
            period.landlord, period.renter, period.year, period.month
        )
        return Response(InvoiceWeekSerializer(weeks, many=True).data)

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[IsAuthenticated, IsLandlord],
    )
    def recompute(self, request, pk=None) -> Response:
        """Re-derives a not-yet-paid invoice's gas total from current logs."""
        invoice = self.get_object()
        try:
            invoice = services.recompute_invoice_gas(invoice)
        except services.InvoiceLockedError as exc:
            return Response(
                {'detail': str(exc)}, status=status.HTTP_409_CONFLICT
            )
        return Response(InvoiceSerializer(invoice).data)


class LeaseRentRevisionView(APIView):
    """Schedules a rent change for a lease, at least 30 days out.

    Immediately emails the renter regardless of how far out the
    change is scheduled, so they have advance notice.
    """

    permission_classes = [IsAuthenticated, IsLandlord]

    def post(self, request, lease_id: int) -> Response:
        lease = get_object_or_404(Lease, id=lease_id, landlord=request.user)
        serializer = LeaseRentRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        revision = serializer.save(lease=lease)
        return Response(
            LeaseRentRevisionSerializer(revision).data,
            status=status.HTTP_201_CREATED,
        )


class RenterLookupView(APIView):
    """Exact-match renter lookup by email, for attaching to a new lease.

    Deliberately exact-match only (no partial/prefix search, no list
    endpoint) so landlords can't enumerate renter emails on the
    platform.
    """

    permission_classes = [IsAuthenticated, IsLandlord]

    def get(self, request) -> Response:
        serializer = RenterLookupQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        renter = User.objects.filter(
            email__iexact=email, role=User.Role.RENTER
        ).first()
        if renter is None:
            return Response(
                {'detail': 'No matching renter found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(UserSerializer(renter).data)


class BillingPeriodPreviewView(APIView):
    """Previews a billing period's rent + gas totals for a renter.

    Landlord-only: renters are strictly view/pay on already-generated
    invoices, not previews of upcoming ones.
    """

    permission_classes = [IsAuthenticated, IsLandlord]

    def get(self, request, renter_id: int, year: int, month: int) -> Response:
        renter = get_object_or_404(
            User.objects.filter(role=User.Role.RENTER), id=renter_id
        )
        get_object_or_404(Lease, landlord=request.user, renter=renter)

        try:
            preview = services.compute_period_preview(
                request.user, renter, int(year), int(month)
            )
        except services.BillingConfigError as exc:
            return Response(
                {'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(PeriodPreviewSerializer(preview).data)
