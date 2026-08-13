import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('billing', '0014_invoice_btc_overpaid_usd'),
    ]

    operations = [
        migrations.CreateModel(
            name='InvoiceSettlement',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                (
                    'rail',
                    models.CharField(
                        choices=[
                            ('btc', 'Bitcoin'),
                            ('card', 'Card / Cash App'),
                        ],
                        max_length=8,
                    ),
                ),
                (
                    'amount_usd',
                    models.DecimalField(decimal_places=2, max_digits=10),
                ),
                (
                    'amount_sats',
                    models.BigIntegerField(blank=True, null=True),
                ),
                ('txid', models.CharField(blank=True, max_length=64)),
                (
                    'credited_txid',
                    models.CharField(blank=True, max_length=64),
                ),
                (
                    'credited_usd',
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=10,
                        null=True,
                    ),
                ),
                (
                    'overpaid_usd',
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=10,
                        null=True,
                    ),
                ),
                (
                    'stripe_payment_intent_id',
                    models.CharField(blank=True, max_length=255),
                ),
                ('settled_at', models.DateTimeField()),
                (
                    'invoice',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='settlements',
                        to='billing.invoice',
                    ),
                ),
                (
                    'line_items',
                    models.ManyToManyField(
                        related_name='+', to='billing.invoicelineitem'
                    ),
                ),
            ],
            options={
                'ordering': ['settled_at', 'id'],
                'indexes': [
                    models.Index(
                        fields=['invoice', 'settled_at'],
                        name='payments_in_invoice_77cc5b_idx',
                    )
                ],
                'constraints': [
                    models.UniqueConstraint(
                        condition=models.Q(('txid', ''), _negated=True),
                        fields=('invoice', 'txid'),
                        name='unique_settlement_txid_per_invoice',
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(
                            ('stripe_payment_intent_id', ''), _negated=True
                        ),
                        fields=('invoice', 'stripe_payment_intent_id'),
                        name='unique_settlement_intent_per_invoice',
                    ),
                ],
            },
        ),
    ]
