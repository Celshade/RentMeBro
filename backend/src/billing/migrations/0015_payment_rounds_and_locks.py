from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0014_invoice_btc_overpaid_usd'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='btc_round_line_items',
            field=models.ManyToManyField(
                blank=True, related_name='+', to='billing.invoicelineitem'
            ),
        ),
        migrations.AddField(
            model_name='invoice',
            name='stripe_round_line_items',
            field=models.ManyToManyField(
                blank=True, related_name='+', to='billing.invoicelineitem'
            ),
        ),
        migrations.AddField(
            model_name='invoice',
            name='stripe_intent_status',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name='invoicelineitem',
            name='payment_lock',
            field=models.CharField(
                blank=True,
                choices=[('btc', 'BTC only'), ('card', 'Card only')],
                default='',
                max_length=8,
            ),
        ),
    ]
