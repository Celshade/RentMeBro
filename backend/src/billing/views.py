from django.db.models import Q, QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from billing import services
from billing.models import (
    DrivenDayLog,
    GasPriceEntry,
    Invoice,
    Lease,
    MileageProfile,
)
from billing.permissions import IsLandlord, IsRenterOwner
from billing.serializers import (
    DrivenDayLogSerializer,
    GasPriceEntrySerializer,
    InvoiceCreateSerializer,
    InvoiceSerializer,
    LeaseSerializer,
    MileageProfileSerializer,
    PeriodPreviewSerializer,
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
    """Renters log their own driven days; landlords have read-only access."""

    serializer_class = DrivenDayLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[DrivenDayLog]:
        user = self.request.user
        return DrivenDayLog.objects.filter(
            Q(lease__landlord=user) | Q(lease__renter=user)
        )

    def get_permissions(self) -> list[BasePermission]:
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsAuthenticated(), IsRenterOwner()]
        return super().get_permissions()


class MileageProfileViewSet(viewsets.ModelViewSet):
    serializer_class = MileageProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[MileageProfile]:
        user = self.request.user
        return MileageProfile.objects.filter(
            Q(lease__landlord=user) | Q(lease__renter=user)
        )

    def get_permissions(self) -> list[BasePermission]:
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsAuthenticated(), IsLandlord()]
        return super().get_permissions()


class GasPriceEntryViewSet(viewsets.ModelViewSet):
    serializer_class = GasPriceEntrySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[GasPriceEntry]:
        user = self.request.user
        return GasPriceEntry.objects.filter(
            Q(lease__landlord=user) | Q(lease__renter=user)
        )

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
            Q(lease__landlord=user) | Q(lease__renter=user)
        )

    def create(self, request, *args, **kwargs) -> Response:
        serializer = InvoiceCreateSerializer(
            data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        try:
            invoice = services.generate_invoice(
                lease=serializer.validated_data['lease'],
                year=serializer.validated_data['year'],
                month=serializer.validated_data['month'],
                kind=serializer.validated_data['kind'],
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


class BillingPeriodPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, lease_id: int, year: int, month: int) -> Response:
        lease = get_object_or_404(Lease, id=lease_id)
        if request.user not in (lease.landlord, lease.renter):
            return Response(status=status.HTTP_403_FORBIDDEN)

        try:
            preview = services.compute_period_preview(
                lease, int(year), int(month)
            )
        except services.BillingConfigError as exc:
            return Response(
                {'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(PeriodPreviewSerializer(preview).data)
