from django.urls import include, path
from rest_framework.routers import DefaultRouter

from billing.views import (
    BillingPeriodPreviewView,
    DrivenDayLogViewSet,
    GasPriceEntryViewSet,
    InvoiceViewSet,
    LeaseViewSet,
    MileageProfileViewSet,
)

router = DefaultRouter()
router.register('leases', LeaseViewSet, basename='lease')
router.register('driven-days', DrivenDayLogViewSet, basename='driven-day')
router.register(
    'mileage-profiles', MileageProfileViewSet, basename='mileage-profile'
)
router.register(
    'gas-price-entries', GasPriceEntryViewSet, basename='gas-price-entry'
)
router.register('invoices', InvoiceViewSet, basename='invoice')

urlpatterns = [
    path('', include(router.urls)),
    path(
        'leases/<int:lease_id>/billing-periods/'
        '<int:year>-<int:month>/preview/',
        BillingPeriodPreviewView.as_view(),
        name='billing-period-preview',
    ),
]
