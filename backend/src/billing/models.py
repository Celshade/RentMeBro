from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.db import models
from django.utils import timezone


class Lease(models.Model):
    """Links one landlord to one renter for billing purposes."""

    class LeaseType(models.TextChoices):
        CUSTOM = 'custom', 'Custom'
        DEFAULT = 'default', 'Default'

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
    lease_type = models.CharField(
        max_length=16, choices=LeaseType.choices, default=LeaseType.DEFAULT
    )
    document = models.FileField(
        upload_to='lease_documents/', null=True, blank=True
    )
    term_months = models.PositiveIntegerField(null=True, blank=True)

    @property
    def default_terms_text(self) -> str:
        return (
            f'This lease sets monthly rent at ${self.monthly_rent} for a '
            f'term of {self.term_months} months beginning '
            f'{self.start_date}. This agreement is subject to change '
            'based on future circumstances. Any revisions will be '
            'provided to the renter in writing at least 30 days before '
            'taking effect.'
        )

    @property
    def current_monthly_rent(self) -> Decimal:
        """The rent in effect today, applying any due rent revision."""
        today = timezone.now().date()
        revision = (
            self.rent_revisions.filter(effective_date__lte=today)
            .order_by('-effective_date')
            .first()
        )
        return revision.new_monthly_rent if revision else self.monthly_rent

    def __str__(self) -> str:
        return f'Lease({self.landlord} -> {self.renter})'


class LeaseRentRevision(models.Model):
    """A scheduled change to a lease's monthly rent.

    Landlord-submitted revisions must take effect at least 30 days
    out (enforced in the serializer, not here); Django admin can
    create/edit a revision with an earlier effective_date directly,
    since admin edits bypass that API-level restriction. Either way,
    saving a new revision immediately emails the renter so they have
    advance notice, regardless of how far out it's scheduled.
    """

    lease = models.ForeignKey(
        Lease, on_delete=models.CASCADE, related_name='rent_revisions'
    )
    new_monthly_rent = models.DecimalField(max_digits=10, decimal_places=2)
    effective_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-effective_date']

    def __str__(self) -> str:
        return (
            f'LeaseRentRevision(lease={self.lease_id}, '
            f'${self.new_monthly_rent}, {self.effective_date})'
        )

    def save(self, *args, **kwargs) -> None:
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            self._notify_renter()

    def _notify_renter(self) -> None:
        send_mail(
            subject='Your RentMeBro rent is changing',
            message=(
                f'Your monthly rent will change to '
                f'${self.new_monthly_rent}, effective '
                f'{self.effective_date}.'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[self.lease.renter.email],
        )


class MileageProfile(models.Model):
    """Trip constants used to compute gas cost per driven day.

    Gas billing is a secondary, optional feature tied to a
    (landlord, renter) pair directly rather than a specific lease, so
    it persists across lease renewals/changes. A full day driven is a
    round trip drop-off + pick-up, i.e. the one-way commute distance
    driven four times (matches the manual tracking this replaces).
    """

    landlord = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='mileage_profiles_as_landlord',
    )
    renter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='mileage_profiles_as_renter',
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
            f'MileageProfile(landlord={self.landlord_id}, '
            f'renter={self.renter_id}, from={self.effective_from})'
        )


class GasPriceEntry(models.Model):
    """A gas price (per gallon) in effect for a date range.

    Gas price fluctuates period to period, so it's logged rather than
    treated as a fixed rate. Tied to a (landlord, renter) pair, same
    as MileageProfile.
    """

    landlord = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='gas_price_entries_as_landlord',
    )
    renter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='gas_price_entries_as_renter',
    )
    price_per_gallon = models.DecimalField(max_digits=6, decimal_places=3)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['-effective_from']

    def __str__(self) -> str:
        return (
            f'GasPriceEntry(landlord={self.landlord_id}, '
            f'renter={self.renter_id}, ${self.price_per_gallon}, '
            f'from={self.effective_from})'
        )


class DrivenDayLog(models.Model):
    """A landlord-logged day (or partial day) a renter was driven, or a
    day explicitly logged as not driven by the landlord (a day off, or
    a day someone else drove the renter).
    """

    class Kind(models.TextChoices):
        DRIVEN = 'driven', 'Driven'
        DAY_OFF = 'day_off', 'Day off'
        OTHER_RIDE = 'other_ride', 'Other ride'

    landlord = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='driven_day_logs_as_landlord',
    )
    renter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='driven_day_logs_as_renter',
    )
    date = models.DateField()
    kind = models.CharField(
        max_length=16, choices=Kind.choices, default=Kind.DRIVEN
    )
    day_fraction = models.DecimalField(
        max_digits=3, decimal_places=2, default=1
    )
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['date']
        unique_together = ('landlord', 'renter', 'date')

    def __str__(self) -> str:
        return (
            f'DrivenDayLog(landlord={self.landlord_id}, '
            f'renter={self.renter_id}, {self.date}, {self.kind}, '
            f'{self.day_fraction})'
        )


class BillingPeriod(models.Model):
    """A single month scope for a (landlord, renter) pair's charges."""

    landlord = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='billing_periods_as_landlord',
    )
    renter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='billing_periods_as_renter',
    )
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ['-year', '-month']
        unique_together = ('landlord', 'renter', 'year', 'month')

    def __str__(self) -> str:
        return (
            f'BillingPeriod(landlord={self.landlord_id}, '
            f'renter={self.renter_id}, {self.year}-{self.month:02d})'
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

    billing_period = models.ForeignKey(
        BillingPeriod, on_delete=models.CASCADE, related_name='invoices'
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    due_date = models.DateField()

    class Meta:
        unique_together = ('billing_period', 'kind')

    def __str__(self) -> str:
        return f'Invoice({self.billing_period}, {self.kind})'

    @property
    def total(self) -> Decimal:
        return sum(
            (item.amount for item in self.line_items.all()), start=Decimal(0)
        )

    @property
    def is_late(self) -> bool:
        if self.status in (Invoice.Status.PAID, Invoice.Status.VOID):
            return False
        return timezone.now().date() > self.due_date


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
