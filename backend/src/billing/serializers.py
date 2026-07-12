from rest_framework import serializers

from billing.models import (
    BillingPeriod,
    DrivenDayLog,
    GasPriceEntry,
    Invoice,
    InvoiceLineItem,
    Lease,
    MileageProfile,
)


class LeaseSerializer(serializers.ModelSerializer):
    landlord = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Lease
        fields = [
            'id', 'landlord', 'renter', 'monthly_rent', 'start_date', 'active'
        ]

    def create(self, validated_data: dict) -> Lease:
        validated_data['landlord'] = self.context['request'].user
        return super().create(validated_data)


class DrivenDayLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = DrivenDayLog
        fields = ['id', 'lease', 'date', 'day_fraction', 'note']

    def validate_lease(self, lease: Lease) -> Lease:
        request = self.context['request']
        if lease.renter_id != request.user.id:
            raise serializers.ValidationError(
                'You can only log driven days for your own lease.'
            )
        return lease


class MileageProfileSerializer(serializers.ModelSerializer):
    full_day_miles = serializers.DecimalField(
        max_digits=6, decimal_places=2, read_only=True
    )

    class Meta:
        model = MileageProfile
        fields = [
            'id', 'lease', 'one_way_miles', 'mpg', 'effective_from',
            'full_day_miles',
        ]

    def validate_lease(self, lease: Lease) -> Lease:
        request = self.context['request']
        if lease.landlord_id != request.user.id:
            raise serializers.ValidationError(
                'You can only configure mileage profiles for your own '
                'leases.'
            )
        return lease


class GasPriceEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = GasPriceEntry
        fields = [
            'id', 'lease', 'price_per_gallon', 'effective_from',
            'effective_to',
        ]

    def validate_lease(self, lease: Lease) -> Lease:
        request = self.context['request']
        if lease.landlord_id != request.user.id:
            raise serializers.ValidationError(
                'You can only configure gas prices for your own leases.'
            )
        return lease


class InvoiceLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLineItem
        fields = ['id', 'description', 'amount', 'kind']


class BillingPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillingPeriod
        fields = ['id', 'lease', 'year', 'month']


class InvoiceSerializer(serializers.ModelSerializer):
    line_items = InvoiceLineItemSerializer(many=True, read_only=True)
    billing_period = BillingPeriodSerializer(read_only=True)
    total = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = Invoice
        fields = [
            'id', 'lease', 'billing_period', 'kind', 'status',
            'stripe_payment_intent_id', 'created_at', 'line_items', 'total',
        ]
        read_only_fields = ['status', 'stripe_payment_intent_id', 'created_at']


class InvoiceCreateSerializer(serializers.Serializer):
    lease = serializers.PrimaryKeyRelatedField(queryset=Lease.objects.all())
    year = serializers.IntegerField()
    month = serializers.IntegerField(min_value=1, max_value=12)
    kind = serializers.ChoiceField(choices=Invoice.Kind.choices)

    def validate_lease(self, lease: Lease) -> Lease:
        request = self.context['request']
        if lease.landlord_id != request.user.id:
            raise serializers.ValidationError(
                'You can only generate invoices for your own leases.'
            )
        return lease


class PeriodPreviewSerializer(serializers.Serializer):
    rent = serializers.DecimalField(max_digits=10, decimal_places=2)
    gas = serializers.DecimalField(max_digits=10, decimal_places=2)


class RenterLookupQuerySerializer(serializers.Serializer):
    email = serializers.EmailField()
