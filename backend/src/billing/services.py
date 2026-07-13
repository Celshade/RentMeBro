"""Billing calculations: gas cost from mileage, invoice generation."""

from datetime import date
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
        raise BillingConfigError(
            f'No GasPriceEntry in effect for landlord {landlord.id}, '
            f'renter {renter.id} on {on_date}'
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
        'rent': lease.monthly_rent,
        'gas': compute_period_gas_total(landlord, renter, year, month),
    }


@transaction.atomic
def generate_invoice(
    landlord: User, renter: User, year: int, month: int, kind: str
) -> Invoice:
    """Creates (or reuses) the BillingPeriod and builds an Invoice.

    Args:
        landlord: The landlord side of the pair to bill.
        renter: The renter side of the pair to bill.
        year: The billing period's year.
        month: The billing period's month (1-12).
        kind: One of Invoice.Kind (combined / rent_only / gas_only).

    Returns:
        The created Invoice, with its line items already attached.

    Raises:
        InvoiceAlreadyExistsError: If an invoice of this kind already
            exists for the pair's billing period.
    """
    billing_period, _ = BillingPeriod.objects.get_or_create(
        landlord=landlord, renter=renter, year=year, month=month
    )
    try:
        with transaction.atomic():
            invoice = Invoice.objects.create(
                billing_period=billing_period, kind=kind
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
            amount=lease.monthly_rent,
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
