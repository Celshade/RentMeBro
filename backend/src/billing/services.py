"""Billing calculations: gas cost from mileage, invoice generation."""

from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q

from accounts.models import User
from billing.models import (
    BillingPeriod,
    DrivenDayLog,
    GasPriceEntry,
    Invoice,
    InvoiceLineItem,
    Lease,
    MileageProfile,
)


class BillingConfigError(Exception):
    """Raised when a (landlord, renter) pair is missing config for a date."""


class InvoiceAlreadyExistsError(Exception):
    """Raised when an invoice of this kind already exists for the period."""


class InvoiceLockedError(Exception):
    """Raised when trying to edit an invoice that's already paid/void."""


def get_active_lease(landlord: User, renter: User) -> Lease:
    """Finds the active lease between a landlord and renter.

    Args:
        landlord: The landlord to look up the lease for.
        renter: The renter to look up the lease for.

    Returns:
        The most recently started active Lease between the two.

    Raises:
        BillingConfigError: If there's no active lease between them.
    """
    lease = (
        Lease.objects.filter(landlord=landlord, renter=renter, active=True)
        .order_by('-start_date')
        .first()
    )
    if lease is None:
        raise BillingConfigError(
            f'No active lease between landlord {landlord.id} and '
            f'renter {renter.id}'
        )
    return lease


def get_mileage_profile_for_date(
    landlord: User, renter: User, on_date: date
) -> MileageProfile:
    """Finds the MileageProfile in effect for a pair on a given date.

    Args:
        landlord: The landlord side of the pair.
        renter: The renter side of the pair.
        on_date: The date the profile must be effective on or before.

    Returns:
        The most recent MileageProfile with effective_from <= on_date.

    Raises:
        BillingConfigError: If no profile is in effect for that date.
    """
    profile = (
        MileageProfile.objects.filter(
            landlord=landlord, renter=renter, effective_from__lte=on_date
        )
        .order_by('-effective_from')
        .first()
    )
    if profile is None:
        raise BillingConfigError(
            f'No MileageProfile in effect for landlord {landlord.id}, '
            f'renter {renter.id} on {on_date}'
        )
    return profile


def get_gas_price_for_date(
    landlord: User, renter: User, on_date: date
) -> GasPriceEntry:
    """Finds the GasPriceEntry in effect for a pair on a given date.

    Args:
        landlord: The landlord side of the pair.
        renter: The renter side of the pair.
        on_date: The date the price must be effective on.

    Returns:
        The GasPriceEntry whose effective range covers on_date.

    Raises:
        BillingConfigError: If no price entry covers that date.
    """
    entry = (
        GasPriceEntry.objects.filter(
            landlord=landlord, renter=renter, effective_from__lte=on_date
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on_date))
        .order_by('-effective_from')
        .first()
    )
    if entry is None:
        week_start = on_date - timedelta(days=(on_date.weekday() + 1) % 7)
        week_end = week_start + timedelta(days=6)
        raise BillingConfigError(
            f'No gas price is set for the week of {week_start} to '
            f'{week_end}. Add one before generating this invoice.'
        )
    return entry


def compute_gas_cost_for_log(log: DrivenDayLog) -> Decimal:
    """Computes the gas cost for a single driven-day log entry.

    Cost = day_fraction * full_day_miles / mpg * price_per_gallon,
    using the MileageProfile and GasPriceEntry in effect on the log's
    date. Days off and days someone else drove the renter aren't
    billed to the landlord, so they cost nothing.

    Args:
        log: The driven-day entry to price.

    Returns:
        The gas cost for that day, rounded to the nearest cent.
    """
    if log.kind != DrivenDayLog.Kind.DRIVEN:
        return Decimal('0.00')
    profile = get_mileage_profile_for_date(log.landlord, log.renter, log.date)
    gas_price = get_gas_price_for_date(log.landlord, log.renter, log.date)
    miles = log.day_fraction * profile.full_day_miles
    gallons = miles / profile.mpg
    cost = gallons * gas_price.price_per_gallon
    return cost.quantize(Decimal('0.01'))


def compute_period_gas_total(
    landlord: User, renter: User, year: int, month: int
) -> Decimal:
    """Sums gas cost across all driven-day logs in a billing period.

    Args:
        landlord: The landlord side of the pair.
        renter: The renter side of the pair.
        year: The billing period's year.
        month: The billing period's month (1-12).

    Returns:
        The total gas cost for the period, rounded to the nearest cent.
    """
    logs = DrivenDayLog.objects.filter(
        landlord=landlord, renter=renter, date__year=year, date__month=month
    )
    return sum(
        (compute_gas_cost_for_log(log) for log in logs),
        start=Decimal('0.00'),
    )


def compute_period_weekly_breakdown(
    landlord: User, renter: User, year: int, month: int
) -> list[dict]:
    """Groups a period's driven-day logs into Sunday-Saturday weeks.

    Uses the same week convention as `get_gas_price_for_date`'s error
    message and the driven-days calendar UI (weeks start on Sunday).

    Args:
        landlord: The landlord side of the pair.
        renter: The renter side of the pair.
        year: The billing period's year.
        month: The billing period's month (1-12).

    Includes every logged day (driven, day off, other ride) so the
    invoice detail calendar can render them all, but only driven days
    count toward the week's totals.

    Returns:
        A list of week dicts, ordered by week_start, each with
        'week_start', 'week_end', 'total_miles', 'total_gas_cost',
        'price_per_gallon' (the price in effect for the week's first
        driven day), and 'days' (a list of per-day dicts with 'date',
        'kind', 'day_fraction', 'miles', 'gas_cost').
    """
    logs = DrivenDayLog.objects.filter(
        landlord=landlord, renter=renter, date__year=year, date__month=month
    ).order_by('date')

    weeks: dict[date, dict] = {}
    for log in logs:
        week_start = log.date - timedelta(days=(log.date.weekday() + 1) % 7)
        week = weeks.setdefault(
            week_start,
            {
                'week_start': week_start,
                'week_end': week_start + timedelta(days=6),
                'total_miles': Decimal('0.00'),
                'total_gas_cost': Decimal('0.00'),
                'price_per_gallon': None,
                'days': [],
            },
        )
        is_driven = log.kind == DrivenDayLog.Kind.DRIVEN
        miles = Decimal('0.00')
        gas_cost = Decimal('0.00')
        if is_driven:
            profile = get_mileage_profile_for_date(
                landlord, renter, log.date
            )
            gas_price = get_gas_price_for_date(landlord, renter, log.date)
            gas_cost = compute_gas_cost_for_log(log)
            miles = (log.day_fraction * profile.full_day_miles).quantize(
                Decimal('0.01')
            )
            if week['price_per_gallon'] is None:
                week['price_per_gallon'] = gas_price.price_per_gallon
        week['days'].append(
            {
                'date': log.date,
                'kind': log.kind,
                'day_fraction': log.day_fraction,
                'miles': miles,
                'gas_cost': gas_cost,
            }
        )
        week['total_miles'] += miles
        week['total_gas_cost'] += gas_cost

    return [weeks[key] for key in sorted(weeks)]


def compute_period_preview(
    landlord: User, renter: User, year: int, month: int
) -> dict[str, Decimal]:
    """Computes rent + gas totals for a period without creating an invoice.

    Args:
        landlord: The landlord side of the pair.
        renter: The renter side of the pair.
        year: The billing period's year.
        month: The billing period's month (1-12).

    Returns:
        A dict with 'rent' and 'gas' Decimal totals.
    """
    lease = get_active_lease(landlord, renter)
    return {
        'rent': lease.current_monthly_rent,
        'gas': compute_period_gas_total(landlord, renter, year, month),
    }


def default_invoice_due_date(year: int, month: int) -> date:
    """The 5th of the month after a billing period, e.g. June -> July 5.

    Args:
        year: The billing period's year.
        month: The billing period's month (1-12).

    Returns:
        The default due date for an invoice covering that period.
    """
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return date(next_year, next_month, 5)


@transaction.atomic
def generate_invoice(
    landlord: User,
    renter: User,
    year: int,
    month: int,
    kind: str,
    due_date: date | None = None,
) -> Invoice:
    """Creates (or reuses) the BillingPeriod and builds an Invoice.

    Args:
        landlord: The landlord side of the pair to bill.
        renter: The renter side of the pair to bill.
        year: The billing period's year.
        month: The billing period's month (1-12).
        kind: One of Invoice.Kind (combined / rent_only / gas_only).
        due_date: When the invoice is due. Defaults to the 5th of the
            month after the billing period.

    Returns:
        The created Invoice, with its line items already attached.

    Raises:
        InvoiceAlreadyExistsError: If an invoice of this kind already
            exists for the pair's billing period.
    """
    if due_date is None:
        due_date = default_invoice_due_date(year, month)

    billing_period, _ = BillingPeriod.objects.get_or_create(
        landlord=landlord, renter=renter, year=year, month=month
    )
    try:
        with transaction.atomic():
            invoice = Invoice.objects.create(
                billing_period=billing_period, kind=kind, due_date=due_date
            )
    except IntegrityError as exc:
        raise InvoiceAlreadyExistsError(
            f'An invoice of kind {kind!r} already exists for landlord '
            f'{landlord.id}, renter {renter.id} in {year}-{month:02d}.'
        ) from exc

    if kind in (Invoice.Kind.COMBINED, Invoice.Kind.RENT_ONLY):
        lease = get_active_lease(landlord, renter)
        InvoiceLineItem.objects.create(
            invoice=invoice,
            description=f'Rent for {year}-{month:02d}',
            amount=lease.current_monthly_rent,
            kind=InvoiceLineItem.Kind.RENT,
        )

    if kind in (Invoice.Kind.COMBINED, Invoice.Kind.GAS_ONLY):
        gas_total = compute_period_gas_total(landlord, renter, year, month)
        InvoiceLineItem.objects.create(
            invoice=invoice,
            description=f'Gas for {year}-{month:02d}',
            amount=gas_total,
            kind=InvoiceLineItem.Kind.GAS,
        )

    return invoice


@transaction.atomic
def recompute_invoice_gas(invoice: Invoice) -> Invoice:
    """Re-derives a draft/sent invoice's gas line item from current logs.

    Lets a landlord correct mileage logs for an already-generated
    invoice's billing month and pull the correction into the invoice
    total, up until the renter pays it.

    Args:
        invoice: The invoice to recompute. Must not yet be paid or void.

    Returns:
        The updated invoice.

    Raises:
        InvoiceLockedError: If the invoice is already pending a BTC
            payment, has an outstanding BTC remainder, paid, or void.
    """
    if invoice.status in (
        Invoice.Status.PENDING,
        Invoice.Status.PARTIAL,
        Invoice.Status.UNDERPAID,
        Invoice.Status.PAID,
        Invoice.Status.VOID,
    ):
        raise InvoiceLockedError(
            f'Invoice {invoice.id} is {invoice.status} and can no longer '
            'be edited.'
        )

    gas_line_item = invoice.line_items.filter(
        kind=InvoiceLineItem.Kind.GAS
    ).first()
    if gas_line_item is None:
        return invoice

    period = invoice.billing_period
    new_amount = compute_period_gas_total(
        period.landlord, period.renter, period.year, period.month
    )
    if new_amount == gas_line_item.amount:
        return invoice

    gas_line_item.amount = new_amount
    gas_line_item.save(update_fields=['amount'])

    invoice.btc_address = ""
    invoice.btc_amount_sats = None
    invoice.btc_txid = ""
    invoice.btc_watch_expires_at = None
    invoice.remainder_owed_usd = None
    invoice.btc_credited_txid = ""
    invoice.btc_credited_usd = None
    invoice.save(
        update_fields=[
            "btc_address",
            "btc_amount_sats",
            "btc_txid",
            "btc_watch_expires_at",
            "remainder_owed_usd",
            "btc_credited_txid",
            "btc_credited_usd",
        ]
    )
    return invoice
