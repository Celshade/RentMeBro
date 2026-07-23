from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from accounts.models import User
from accounts.serializers import UserSerializer
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
            'id', 'landlord', 'renter', 'date', 'kind', 'day_fraction', 'note',
        ]

    def validate_renter(self, renter: User) -> User:
        return _validate_is_own_renter(renter, self.context['request'].user)

    def validate(self, attrs: dict) -> dict:
        kind = attrs.get('kind', getattr(self.instance, 'kind', None))
        if kind is not None and kind != DrivenDayLog.Kind.DRIVEN:
            attrs['day_fraction'] = Decimal('0')
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
        fields = ['id', 'description', 'amount', 'kind']


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

    class Meta:
        model = Invoice
        fields = [
            'id', 'billing_period', 'kind', 'status', 'due_date',
            'stripe_payment_intent_id', 'created_at', 'line_items', 'total',
            'is_late',
        ]
        read_only_fields = ['status', 'stripe_payment_intent_id', 'created_at']


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
