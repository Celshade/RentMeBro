from decimal import Decimal

from django.conf import settings
from django.db import models


class Lease(models.Model):
    """Links one landlord to one renter for billing purposes."""

    landlord = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='leases_as_landlord',
    )
    renter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='leases_as_renter',
    )
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2)
    start_date = models.DateField()
    active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return f'Lease({self.landlord} -> {self.renter})'


class MileageProfile(models.Model):
    """Per-lease trip constants used to compute gas cost per driven day.

    A full day driven is a round trip drop-off + pick-up, i.e. the
    one-way commute distance driven four times (matches the manual
    tracking this replaces).
    """

    lease = models.ForeignKey(
        Lease, on_delete=models.CASCADE, related_name='mileage_profiles'
    )
    one_way_miles = models.DecimalField(max_digits=6, decimal_places=2)
    mpg = models.DecimalField(max_digits=6, decimal_places=2)
    effective_from = models.DateField()

    class Meta:
        ordering = ['-effective_from']

    @property
    def full_day_miles(self) -> Decimal:
        return self.one_way_miles * 4

    def __str__(self) -> str:
        return (
            f'MileageProfile(lease={self.lease_id}, '
            f'from={self.effective_from})'
        )


class GasPriceEntry(models.Model):
    """A gas price (per gallon) in effect for a date range.

    Gas price fluctuates period to period, so it's logged rather than
    treated as a fixed rate.
    """

    lease = models.ForeignKey(
        Lease, on_delete=models.CASCADE, related_name='gas_price_entries'
    )
    price_per_gallon = models.DecimalField(max_digits=6, decimal_places=3)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['-effective_from']

    def __str__(self) -> str:
        return (
            f'GasPriceEntry(lease={self.lease_id}, '
            f'${self.price_per_gallon}, from={self.effective_from})'
        )


class DrivenDayLog(models.Model):
    """A renter-logged day (or partial day) driven to the worksite."""

    lease = models.ForeignKey(
        Lease, on_delete=models.CASCADE, related_name='driven_day_logs'
    )
    date = models.DateField()
    day_fraction = models.DecimalField(
        max_digits=3, decimal_places=2, default=1
    )
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['date']
        unique_together = ('lease', 'date')

    def __str__(self) -> str:
        return (
            f'DrivenDayLog(lease={self.lease_id}, {self.date}, '
            f'{self.day_fraction})'
        )


class BillingPeriod(models.Model):
    """A single month scope for a lease's rent + driven-day charges."""

    lease = models.ForeignKey(
        Lease, on_delete=models.CASCADE, related_name='billing_periods'
    )
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ['-year', '-month']
        unique_together = ('lease', 'year', 'month')

    def __str__(self) -> str:
        return (
            f'BillingPeriod(lease={self.lease_id}, '
            f'{self.year}-{self.month:02d})'
        )


class Invoice(models.Model):
    class Kind(models.TextChoices):
        COMBINED = 'combined', 'Combined'
        RENT_ONLY = 'rent_only', 'Rent only'
        GAS_ONLY = 'gas_only', 'Gas only'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        SENT = 'sent', 'Sent'
        PAID = 'paid', 'Paid'
        VOID = 'void', 'Void'

    lease = models.ForeignKey(
        Lease, on_delete=models.CASCADE, related_name='invoices'
    )
    billing_period = models.ForeignKey(
        BillingPeriod, on_delete=models.CASCADE, related_name='invoices'
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('lease', 'billing_period', 'kind')

    def __str__(self) -> str:
        return (
            f'Invoice({self.lease_id}, {self.billing_period}, {self.kind})'
        )

    @property
    def total(self) -> Decimal:
        return sum(
            (item.amount for item in self.line_items.all()), start=Decimal(0)
        )


class InvoiceLineItem(models.Model):
    class Kind(models.TextChoices):
        RENT = 'rent', 'Rent'
        GAS = 'gas', 'Gas'

    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name='line_items'
    )
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    kind = models.CharField(max_length=16, choices=Kind.choices)

    def __str__(self) -> str:
        return f'InvoiceLineItem({self.kind}, ${self.amount})'
