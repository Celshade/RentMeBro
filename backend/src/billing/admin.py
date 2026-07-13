from django.contrib import admin

from billing.models import (
    BillingPeriod,
    DrivenDayLog,
    GasPriceEntry,
    Invoice,
    InvoiceLineItem,
    Lease,
    LeaseRentRevision,
    MileageProfile,
)


@admin.register(Lease)
class LeaseAdmin(admin.ModelAdmin):
    list_display = ('id', 'landlord', 'renter', 'monthly_rent', 'active')


@admin.register(LeaseRentRevision)
class LeaseRentRevisionAdmin(admin.ModelAdmin):
    """Registered so staff can apply/override a rent change directly.

    Editing here bypasses the API's 30-day-minimum effective_date
    restriction, since that's enforced in the serializer, not the
    model - saving still emails the renter immediately either way.
    """

    list_display = ('lease', 'new_monthly_rent', 'effective_date')


@admin.register(MileageProfile)
class MileageProfileAdmin(admin.ModelAdmin):
    list_display = (
        'landlord', 'renter', 'one_way_miles', 'mpg', 'effective_from'
    )


@admin.register(GasPriceEntry)
class GasPriceEntryAdmin(admin.ModelAdmin):
    list_display = (
        'landlord', 'renter', 'price_per_gallon', 'effective_from',
        'effective_to',
    )


@admin.register(DrivenDayLog)
class DrivenDayLogAdmin(admin.ModelAdmin):
    list_display = ('landlord', 'renter', 'date', 'day_fraction')
    list_filter = ('landlord', 'renter')


@admin.register(BillingPeriod)
class BillingPeriodAdmin(admin.ModelAdmin):
    list_display = ('landlord', 'renter', 'year', 'month')


class InvoiceLineItemInline(admin.TabularInline):
    model = InvoiceLineItem
    extra = 0


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'billing_period', 'kind', 'status', 'total')
    inlines = [InvoiceLineItemInline]
