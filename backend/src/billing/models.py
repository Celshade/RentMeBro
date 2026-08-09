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

    @property
    def pending_rent_revision(self) -> 'LeaseRentRevision | None':
        """The nearest scheduled revision not yet in effect, if any."""
        today = timezone.now().date()
        return (
            self.rent_revisions.filter(effective_date__gt=today)
            .order_by('effective_date')
            .first()
        )

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
        PENDING = 'pending', 'Pending'
        # PARTIAL and UNDERPAID both mean "some money arrived" but call
        # for different responses: a split invoice is progressing
        # normally and just needs its other leg, while an underpaid one
        # is short and needs chasing.
        PARTIAL = 'partial', 'Partially Paid'
        UNDERPAID = 'underpaid', 'Underpaid'
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
    btc_address = models.CharField(max_length=64, blank=True)
    btc_amount_sats = models.BigIntegerField(null=True, blank=True)
    btc_txid = models.CharField(max_length=64, blank=True)
    btc_watch_expires_at = models.DateTimeField(null=True, blank=True)
    remainder_owed_usd = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    btc_credited_txid = models.CharField(max_length=64, blank=True)
    btc_credited_usd = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    btc_line_items = models.ManyToManyField(
        'InvoiceLineItem', blank=True, related_name='+'
    )
    btc_settled_at = models.DateTimeField(null=True, blank=True)
    stripe_settled_at = models.DateTimeField(null=True, blank=True)
    btc_round_line_items = models.ManyToManyField(
        'InvoiceLineItem', blank=True, related_name='+'
    )
    stripe_round_line_items = models.ManyToManyField(
        'InvoiceLineItem', blank=True, related_name='+'
    )
    stripe_intent_status = models.CharField(max_length=32, blank=True)

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
        if self.status in (
            Invoice.Status.PENDING,
            Invoice.Status.PARTIAL,
            Invoice.Status.UNDERPAID,
            Invoice.Status.PAID,
            Invoice.Status.VOID,
        ):
            return False
        return timezone.now().date() > self.due_date

    @property
    def paid_line_item_ids(self) -> set[int]:
        """IDs of line items covered by a settled `InvoiceSettlement`.

        The single authority for per-item paid state -- do not derive
        this from `btc_line_items` or any other scope field. Iterates
        `.all()` deliberately: a `.filter()` would re-query and defeat
        prefetching.
        """
        ids: set[int] = set()
        for settlement in self.settlements.all():
            ids.update(item.id for item in settlement.line_items.all())
        return ids

    @property
    def unpaid_line_items(self) -> list['InvoiceLineItem']:
        paid = self.paid_line_item_ids
        return [item for item in self.line_items.all() if item.id not in paid]

    @property
    def btc_round_is_live(self) -> bool:
        """Whether a BTC round is currently in flight.

        True for a live quote window or a seen-but-unconfirmed tx.
        """
        now = timezone.now()
        live_quote = (
            self.btc_watch_expires_at is not None
            and self.btc_watch_expires_at > now
        )
        return live_quote or bool(self.btc_txid)

    @property
    def card_round_is_live(self) -> bool:
        """Whether a card round is currently in flight.

        Only `processing`/`requires_action` count -- a PaymentIntent
        merely sitting at `requires_payment_method` (the renter opened
        the tab and walked away) blocks nothing.
        """
        return self.stripe_intent_status in (
            'processing', 'requires_action'
        )

    @property
    def _btc_in_flight_line_item_ids(self) -> set[int]:
        if not self.btc_round_is_live:
            return set()
        return {item.id for item in self.btc_round_line_items.all()}

    @property
    def _card_in_flight_line_item_ids(self) -> set[int]:
        if not self.card_round_is_live:
            return set()
        return {item.id for item in self.stripe_round_line_items.all()}

    @property
    def in_flight_line_item_ids(self) -> set[int]:
        return (
            self._btc_in_flight_line_item_ids
            | self._card_in_flight_line_item_ids
        )

    @property
    def frozen_line_item_ids(self) -> set[int]:
        """Items the landlord may no longer re-scope or re-lock.

        Paid union in-flight, minus the underpaid exception: a BTC
        round that came up short falls back to open, since money came
        up short and the landlord may legitimately need to re-scope or
        re-address it.
        """
        frozen = self.paid_line_item_ids | self.in_flight_line_item_ids
        if self.remainder_owed_usd:
            frozen -= {item.id for item in self.btc_round_line_items.all()}
        return frozen

    @property
    def _btc_candidates(self) -> list['InvoiceLineItem']:
        return [
            item for item in self.unpaid_line_items
            if item.payment_lock != InvoiceLineItem.Lock.CARD
            and item.id not in self._card_in_flight_line_item_ids
        ]

    @property
    def _card_candidates(self) -> list['InvoiceLineItem']:
        return [
            item for item in self.unpaid_line_items
            if item.payment_lock != InvoiceLineItem.Lock.BTC
            and item.id not in self._btc_in_flight_line_item_ids
        ]

    @property
    def btc_scope_line_items(self) -> list['InvoiceLineItem']:
        """What a fresh BTC quote would cover right now.

        The landlord's expectation (`btc_line_items`) intersected with
        what's actually still payable by BTC, falling back to every
        BTC-payable item when that intersection is empty -- this is
        what lets a second BTC round quote the remaining unpaid rent
        after a first round scoped to gas alone has settled.
        """
        candidates = self._btc_candidates
        expected_ids = {item.id for item in self.btc_line_items.all()}
        scoped = [item for item in candidates if item.id in expected_ids]
        return scoped or candidates

    @property
    def stripe_scope_line_items(self) -> list['InvoiceLineItem']:
        """What the card leg bills by default: card-payable items the
        landlord hasn't expressed a BTC preference for.
        """
        candidates = self._card_candidates
        expected_ids = {item.id for item in self.btc_line_items.all()}
        remaining = [
            item for item in candidates if item.id not in expected_ids
        ]
        return remaining or candidates

    @property
    def btc_portion_usd(self) -> Decimal:
        return sum(
            (item.amount for item in self.btc_scope_line_items),
            start=Decimal(0),
        )

    @property
    def stripe_portion_usd(self) -> Decimal:
        return sum(
            (item.amount for item in self.stripe_scope_line_items),
            start=Decimal(0),
        )

    @property
    def card_full_line_items(self) -> list['InvoiceLineItem']:
        """Every card-payable item, ignoring the BTC expectation.

        Public alias for `_card_candidates` -- other modules (e.g.
        `payments.services`) need the item list, not just its total,
        to snapshot what a full-balance card charge actually bought.
        """
        return self._card_candidates

    @property
    def card_full_owed_usd(self) -> Decimal:
        """Every card-payable item's total -- the opt-in "pay it all by
        card instead" figure, ignoring the BTC expectation.
        """
        return sum(
            (item.amount for item in self.card_full_line_items),
            start=Decimal(0),
        )

    @property
    def is_split_payment(self) -> bool:
        """Informational: whether BTC is scoped to some, but not all, of
        the unpaid charges.

        Drives the split-notice copy only -- `resolve_settled_status`
        no longer consults this.
        """
        if not self.btc_address:
            return False
        unpaid_ids = {item.id for item in self.unpaid_line_items}
        expected_ids = {
            item.id for item in self.btc_line_items.all()
        } & unpaid_ids
        return bool(expected_ids) and expected_ids != unpaid_ids

    @property
    def is_fully_paid(self) -> bool:
        return not self.unpaid_line_items

    @property
    def btc_overpaid_usd(self) -> Decimal | None:
        amounts = [
            settlement.overpaid_usd for settlement in self.settlements.all()
            if settlement.overpaid_usd is not None
        ]
        if not amounts:
            return None
        return sum(amounts, start=Decimal(0))


class InvoiceLineItem(models.Model):
    class Kind(models.TextChoices):
        RENT = 'rent', 'Rent'
        GAS = 'gas', 'Gas'

    class Lock(models.TextChoices):
        BTC = 'btc', 'BTC only'
        CARD = 'card', 'Card only'

    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name='line_items'
    )
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    payment_lock = models.CharField(
        max_length=8, blank=True, choices=Lock.choices, default=''
    )

    def __str__(self) -> str:
        return f'InvoiceLineItem({self.kind}, ${self.amount})'
