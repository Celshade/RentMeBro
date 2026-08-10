from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0016_remove_invoice_btc_overpaid_usd'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='stripe_round_expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
