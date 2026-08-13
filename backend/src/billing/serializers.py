from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from accounts.models import User
from accounts.serializers import UserSerializer
from billing import services
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

MIN_RENT_REVISION_NOTICE_DAYS = 30


class LeaseSerializer(serializers.ModelSerializer):
    landlord = serializers.PrimaryKeyRelatedField(read_only=True)
    landlord_detail = UserSerializer(source='landlord', read_only=True)
    renter_detail = UserSerializer(source='renter', read_only=True)
    terms_text = serializers.SerializerMethodField()
    current_monthly_rent = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    pending_rent_revision = serializers.SerializerMethodField()

    class Meta:
        model = Lease
        fields = [
            'id', 'landlord', 'landlord_detail', 'renter', 'renter_detail',
            'monthly_rent', 'current_monthly_rent', 'pending_rent_revision',
            'start_date', 'active', 'lease_type', 'document', 'term_months',
            'terms_text',
        ]

    def get_terms_text(self, obj: Lease) -> str | None:
        if obj.lease_type == Lease.LeaseType.DEFAULT:
            return obj.default_terms_text
        return None

    def get_pending_rent_revision(self, obj: Lease) -> dict | None:
        revision = obj.pending_rent_revision
        if revision is None:
            return None
        return {
            'new_monthly_rent': str(revision.new_monthly_rent),
            'effective_date': revision.effective_date.isoformat(),
        }

    def validate(self, attrs: dict) -> dict:
        lease_type = attrs.get('lease_type', Lease.LeaseType.DEFAULT)
        if lease_type == Lease.LeaseType.CUSTOM and not attrs.get('document'):
            raise serializers.ValidationError(
                'A document is required for a custom lease.'
            )
        if lease_type == Lease.LeaseType.DEFAULT and not attrs.get(
            'term_months'
        ):
            raise serializers.ValidationError(
                'term_months is required for a default lease.'
            )
        return attrs

    def create(self, validated_data: dict) -> Lease:
        validated_data['landlord'] = self.context['request'].user
        return super().create(validated_data)


def _validate_is_own_renter(renter: User, landlord: User) -> User:
    """Confirms a landlord has (or had) a lease with the given renter."""
    if not Lease.objects.filter(landlord=landlord, renter=renter).exists():
        raise serializers.ValidationError(
            'You can only do this for a renter you have a lease with.'
        )
    return renter


class DrivenDayLogSerializer(serializers.ModelSerializer):
    landlord = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = DrivenDayLog
        fields = [
            'id', 'landlord', 'renter', 'date', 'kind', 'day_fraction',
            'half_leg', 'note',
        ]

    def validate_renter(self, renter: User) -> User:
        return _validate_is_own_renter(renter, self.context['request'].user)

    def validate(self, attrs: dict) -> dict:
        kind = attrs.get('kind', getattr(self.instance, 'kind', None))
        if kind is not None and kind != DrivenDayLog.Kind.DRIVEN:
            attrs['day_fraction'] = Decimal('0')

        day_fraction = attrs.get(
            'day_fraction', getattr(self.instance, 'day_fraction', None)
        )
        if kind != DrivenDayLog.Kind.DRIVEN or (
            day_fraction is not None and day_fraction >= 1
        ):
            attrs['half_leg'] = ''

        landlord = self.context['request'].user
        renter = attrs.get('renter', getattr(self.instance, 'renter', None))
        target_date = attrs.get('date', getattr(self.instance, 'date', None))
        # InvoiceLockedError deliberately isn't caught here -- it bubbles
        # up so the view can map it to a 409, distinguishing a lock from
        # a plain validation error.
        services.assert_gas_period_editable(landlord, renter, target_date)
        if self.instance is not None and self.instance.date != target_date:
            services.assert_gas_period_editable(
                landlord, renter, self.instance.date
            )
        return attrs

    def create(self, validated_data: dict) -> DrivenDayLog:
        validated_data['landlord'] = self.context['request'].user
        return super().create(validated_data)


class MileageProfileSerializer(serializers.ModelSerializer):
    landlord = serializers.PrimaryKeyRelatedField(read_only=True)
    full_day_miles = serializers.DecimalField(
        max_digits=6, decimal_places=2, read_only=True
    )

    class Meta:
        model = MileageProfile
        fields = [
            'id', 'landlord', 'renter', 'one_way_miles', 'mpg',
            'effective_from', 'full_day_miles',
        ]

    def validate_renter(self, renter: User) -> User:
        return _validate_is_own_renter(renter, self.context['request'].user)

    def create(self, validated_data: dict) -> MileageProfile:
        validated_data['landlord'] = self.context['request'].user
        return super().create(validated_data)


class GasPriceEntrySerializer(serializers.ModelSerializer):
    landlord = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = GasPriceEntry
        fields = [
            'id', 'landlord', 'renter', 'price_per_gallon',
            'effective_from', 'effective_to',
        ]

    def validate_renter(self, renter: User) -> User:
        return _validate_is_own_renter(renter, self.context['request'].user)

    def create(self, validated_data: dict) -> GasPriceEntry:
        validated_data['landlord'] = self.context['request'].user
        return super().create(validated_data)


class InvoiceLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLineItem
        fields = ['id', 'description', 'amount', 'kind', 'payment_lock']
        read_only_fields = ['payment_lock']


class BillingPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillingPeriod
        fields = ['id', 'landlord', 'renter', 'year', 'month']


class InvoiceSerializer(serializers.ModelSerializer):
    line_items = InvoiceLineItemSerializer(many=True, read_only=True)
    billing_period = BillingPeriodSerializer(read_only=True)
    total = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    is_late = serializers.BooleanField(read_only=True)
    btc_portion_usd = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    stripe_portion_usd = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    card_full_owed_usd = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    btc_full_owed_usd = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    btc_overpaid_usd = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, allow_null=True
    )
    is_split_payment = serializers.BooleanField(read_only=True)
    btc_owed_usd = serializers.SerializerMethodField()
    paid_line_items = serializers.SerializerMethodField()
    frozen_line_items = serializers.SerializerMethodField()
    settlements = serializers.SerializerMethodField()
    btc_scope_line_items = serializers.SerializerMethodField()
    stripe_scope_line_items = serializers.SerializerMethodField()
    card_full_line_items = serializers.SerializerMethodField()
    btc_full_line_items = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id", "billing_period", "kind", "status", "due_date",
            "stripe_payment_intent_id", "created_at", "line_items", "total",
            "is_late", "btc_address", "btc_amount_sats",
            "remainder_owed_usd", "btc_line_items", "btc_portion_usd",
            "stripe_portion_usd", "card_full_owed_usd", "btc_owed_usd",
            "is_split_payment", "btc_settled_at", "btc_overpaid_usd",
            "stripe_settled_at", "btc_txid", "btc_credited_txid",
            "btc_watch_expires_at", "paid_line_items", "frozen_line_items",
            "settlements", "stripe_round_expires_at", "btc_scope_line_items",
            "stripe_scope_line_items", "card_full_line_items",
            "btc_full_owed_usd", "btc_full_line_items",
        ]
        read_only_fields = [
            "status", "stripe_payment_intent_id", "created_at",
            "btc_address", "btc_amount_sats", "remainder_owed_usd",
            "btc_line_items", "btc_settled_at", "btc_overpaid_usd",
            "stripe_settled_at", "btc_txid", "btc_credited_txid",
            "btc_watch_expires_at", "stripe_round_expires_at",
        ]

    def get_btc_owed_usd(self, obj: Invoice) -> str:
        """The USD still owed via BTC, mirroring
        `payments.services._invoice_usd_owed` without importing it --
        the BTC portion, or whatever's left after a prior underpayment
        was credited toward it.
        """
        owed = (
            obj.remainder_owed_usd
            if obj.remainder_owed_usd is not None
            else obj.btc_portion_usd
        )
        return str(owed)

    def get_paid_line_items(self, obj: Invoice) -> list[int]:
        return sorted(obj.paid_line_item_ids)

    def get_frozen_line_items(self, obj: Invoice) -> list[int]:
        return sorted(obj.frozen_line_item_ids)

    def get_btc_scope_line_items(self, obj: Invoice) -> list[int]:
        """What a fresh BTC quote would cover right now.

        The frontend must not re-derive this from `btc_line_items` --
        the fallback rules in `Invoice.btc_scope_line_items` are subtle.
        """
        return sorted(item.id for item in obj.btc_scope_line_items)

    def get_stripe_scope_line_items(self, obj: Invoice) -> list[int]:
        """What the card leg bills by default right now."""
        return sorted(item.id for item in obj.stripe_scope_line_items)

    def get_card_full_line_items(self, obj: Invoice) -> list[int]:
        """Every card-payable item, ignoring the BTC expectation --
        what a `pay_full` card charge would cover.
        """
        return sorted(item.id for item in obj.card_full_line_items)

    def get_btc_full_line_items(self, obj: Invoice) -> list[int]:
        """Every BTC-payable item, ignoring the landlord's BTC scope --
        what a `pay_full` BTC quote would cover.
        """
        return sorted(item.id for item in obj.btc_full_line_items)

    def get_settlements(self, obj: Invoice) -> list[dict]:
        return [
            {
                "id": settlement.id,
                "rail": settlement.rail,
                "txid": settlement.txid,
                "line_items": [
                    item.id for item in settlement.line_items.all()
                ],
                "amount_usd": str(settlement.amount_usd),
                "overpaid_usd": (
                    str(settlement.overpaid_usd)
                    if settlement.overpaid_usd is not None
                    else None
                ),
                "settled_at": settlement.settled_at.isoformat(),
            }
            for settlement in obj.settlements.all()
        ]


class InvoiceWeekDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    kind = serializers.ChoiceField(choices=DrivenDayLog.Kind.choices)
    day_fraction = serializers.DecimalField(max_digits=3, decimal_places=2)
    miles = serializers.DecimalField(max_digits=6, decimal_places=2)
    gas_cost = serializers.DecimalField(max_digits=10, decimal_places=2)


class InvoiceWeekSerializer(serializers.Serializer):
    week_start = serializers.DateField()
    week_end = serializers.DateField()
    total_miles = serializers.DecimalField(max_digits=6, decimal_places=2)
    total_gas_cost = serializers.DecimalField(max_digits=10, decimal_places=2)
    price_per_gallon = serializers.DecimalField(
        max_digits=6, decimal_places=3, allow_null=True
    )
    days = InvoiceWeekDaySerializer(many=True)


MAX_FUTURE_INVOICE_MONTHS = 12


class InvoiceCreateSerializer(serializers.Serializer):
    renter = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.Role.RENTER)
    )
    year = serializers.IntegerField()
    month = serializers.IntegerField(min_value=1, max_value=12)
    kind = serializers.ChoiceField(choices=Invoice.Kind.choices)
    due_date = serializers.DateField(required=False)

    def validate_renter(self, renter: User) -> User:
        return _validate_is_own_renter(renter, self.context['request'].user)

    def validate(self, attrs: dict) -> dict:
        today = timezone.now().date()
        latest_year, latest_month = today.year, today.month + (
            MAX_FUTURE_INVOICE_MONTHS
        )
        latest_year += (latest_month - 1) // 12
        latest_month = (latest_month - 1) % 12 + 1
        if (attrs['year'], attrs['month']) > (latest_year, latest_month):
            raise serializers.ValidationError(
                f'Invoices can only be generated up to '
                f'{MAX_FUTURE_INVOICE_MONTHS} months ahead.'
            )
        return attrs


class PeriodPreviewSerializer(serializers.Serializer):
    rent = serializers.DecimalField(max_digits=10, decimal_places=2)
    gas = serializers.DecimalField(max_digits=10, decimal_places=2)


class RenterLookupQuerySerializer(serializers.Serializer):
    email = serializers.EmailField()


class LeaseRentRevisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaseRentRevision
        fields = ['id', 'lease', 'new_monthly_rent', 'effective_date']
        read_only_fields = ['lease']

    def validate_effective_date(self, value: date) -> date:
        min_date = timezone.now().date() + timedelta(
            days=MIN_RENT_REVISION_NOTICE_DAYS
        )
        if value < min_date:
            raise serializers.ValidationError(
                f'Effective date must be at least '
                f'{MIN_RENT_REVISION_NOTICE_DAYS} days from today.'
            )
        return value
