from django.contrib import admin

from billing.models import (
    BillingPeriod,
    DrivenDayLog,
    GasPriceEntry,
    Invoice,
    InvoiceLineItem,
    Lease,
    MileageProfile,
)


@admin.register(Lease)
class LeaseAdmin(admin.ModelAdmin):
    list_display = ('id', 'landlord', 'renter', 'monthly_rent', 'active')


@admin.register(MileageProfile)
class MileageProfileAdmin(admin.ModelAdmin):
    list_display = ('lease', 'one_way_miles', 'mpg', 'effective_from')


@admin.register(GasPriceEntry)
class GasPriceEntryAdmin(admin.ModelAdmin):
    list_display = (
        'lease', 'price_per_gallon', 'effective_from', 'effective_to'
    )


@admin.register(DrivenDayLog)
class DrivenDayLogAdmin(admin.ModelAdmin):
    list_display = ('lease', 'date', 'day_fraction')
    list_filter = ('lease',)


@admin.register(BillingPeriod)
class BillingPeriodAdmin(admin.ModelAdmin):
    list_display = ('lease', 'year', 'month')


class InvoiceLineItemInline(admin.TabularInline):
    model = InvoiceLineItem
    extra = 0


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'lease', 'billing_period', 'kind', 'status', 'total')
    inlines = [InvoiceLineItemInline]
