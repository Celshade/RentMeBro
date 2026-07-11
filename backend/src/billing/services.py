"""Billing calculations: gas cost from mileage, invoice generation."""

from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q

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
    """Raised when a lease is missing mileage/gas config for a date."""


class InvoiceAlreadyExistsError(Exception):
    """Raised when an invoice of this kind already exists for the period."""


def get_mileage_profile_for_date(lease: Lease, on_date: date) -> MileageProfile:
    """Finds the MileageProfile in effect for a lease on a given date.

    Args:
        lease: The lease to look up mileage config for.
        on_date: The date the profile must be effective on or before.

    Returns:
        The most recent MileageProfile with effective_from <= on_date.

    Raises:
        BillingConfigError: If no profile is in effect for that date.
    """
    profile = (
        lease.mileage_profiles.filter(effective_from__lte=on_date)
        .order_by('-effective_from')
        .first()
    )
    if profile is None:
        raise BillingConfigError(
            f'No MileageProfile in effect for lease {lease.id} on {on_date}'
        )
    return profile


def get_gas_price_for_date(lease: Lease, on_date: date) -> GasPriceEntry:
    """Finds the GasPriceEntry in effect for a lease on a given date.

    Args:
        lease: The lease to look up the gas price for.
        on_date: The date the price must be effective on.

    Returns:
        The GasPriceEntry whose effective range covers on_date.

    Raises:
        BillingConfigError: If no price entry covers that date.
    """
    entry = (
        lease.gas_price_entries.filter(effective_from__lte=on_date)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on_date))
        .order_by('-effective_from')
        .first()
    )
    if entry is None:
        raise BillingConfigError(
            f'No GasPriceEntry in effect for lease {lease.id} on {on_date}'
        )
    return entry


def compute_gas_cost_for_log(log: DrivenDayLog) -> Decimal:
    """Computes the gas cost for a single driven-day log entry.

    Cost = day_fraction * full_day_miles / mpg * price_per_gallon,
    using the MileageProfile and GasPriceEntry in effect on the log's
    date.

    Args:
        log: The driven-day entry to price.

    Returns:
        The gas cost for that day, rounded to the nearest cent.
    """
    profile = get_mileage_profile_for_date(log.lease, log.date)
    gas_price = get_gas_price_for_date(log.lease, log.date)
    miles = log.day_fraction * profile.full_day_miles
    gallons = miles / profile.mpg
    cost = gallons * gas_price.price_per_gallon
    return cost.quantize(Decimal('0.01'))


def compute_period_gas_total(lease: Lease, year: int, month: int) -> Decimal:
    """Sums gas cost across all driven-day logs in a billing period.

    Args:
        lease: The lease whose driven-day logs to total.
        year: The billing period's year.
        month: The billing period's month (1-12).

    Returns:
        The total gas cost for the period, rounded to the nearest cent.
    """
    logs = lease.driven_day_logs.filter(date__year=year, date__month=month)
    return sum(
        (compute_gas_cost_for_log(log) for log in logs),
        start=Decimal('0.00'),
    )


def compute_period_preview(
    lease: Lease, year: int, month: int
) -> dict[str, Decimal]:
    """Computes rent + gas totals for a period without creating an invoice.

    Args:
        lease: The lease to preview.
        year: The billing period's year.
        month: The billing period's month (1-12).

    Returns:
        A dict with 'rent' and 'gas' Decimal totals.
    """
    return {
        'rent': lease.monthly_rent,
        'gas': compute_period_gas_total(lease, year, month),
    }


@transaction.atomic
def generate_invoice(
    lease: Lease, year: int, month: int, kind: str
) -> Invoice:
    """Creates (or reuses) the BillingPeriod and builds an Invoice.

    Args:
        lease: The lease to bill.
        year: The billing period's year.
        month: The billing period's month (1-12).
        kind: One of Invoice.Kind (combined / rent_only / gas_only).

    Returns:
        The created Invoice, with its line items already attached.

    Raises:
        InvoiceAlreadyExistsError: If an invoice of this kind already
            exists for the lease's billing period.
    """
    billing_period, _ = BillingPeriod.objects.get_or_create(
        lease=lease, year=year, month=month
    )
    try:
        with transaction.atomic():
            invoice = Invoice.objects.create(
                lease=lease, billing_period=billing_period, kind=kind
            )
    except IntegrityError as exc:
        raise InvoiceAlreadyExistsError(
            f'An invoice of kind {kind!r} already exists for lease '
            f'{lease.id} in {year}-{month:02d}.'
        ) from exc

    if kind in (Invoice.Kind.COMBINED, Invoice.Kind.RENT_ONLY):
        InvoiceLineItem.objects.create(
            invoice=invoice,
            description=f'Rent for {year}-{month:02d}',
            amount=lease.monthly_rent,
            kind=InvoiceLineItem.Kind.RENT,
        )

    if kind in (Invoice.Kind.COMBINED, Invoice.Kind.GAS_ONLY):
        gas_total = compute_period_gas_total(lease, year, month)
        InvoiceLineItem.objects.create(
            invoice=invoice,
            description=f'Gas for {year}-{month:02d}',
            amount=gas_total,
            kind=InvoiceLineItem.Kind.GAS,
        )

    return invoice
