from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0015_payment_rounds_and_locks'),
        # The data migration reads this column to backfill settlement
        # rows, so it must run before the column is dropped.
        ('payments', '0002_backfill_settlements'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='invoice',
            name='btc_overpaid_usd',
        ),
    ]
