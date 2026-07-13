from django.db.models import Q, QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
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
    LeaseSerializer,
    MileageProfileSerializer,
    PeriodPreviewSerializer,
    RenterLookupQuerySerializer,
)


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
        )

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
