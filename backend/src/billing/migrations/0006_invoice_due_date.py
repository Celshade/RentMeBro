from datetime import date

from django.db import migrations, models


def backfill_due_dates(apps, schema_editor):
    """Sets due_date on existing invoices to the 5th of the following month."""
    Invoice = apps.get_model('billing', 'Invoice')
    for invoice in Invoice.objects.select_related('billing_period'):
        period = invoice.billing_period
        next_year, next_month = (
            (period.year + 1, 1) if period.month == 12 else (period.year, period.month + 1)
        )
        invoice.due_date = date(next_year, next_month, 5)
        invoice.save(update_fields=['due_date'])


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0005_leaserentrevision'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='due_date',
            field=models.DateField(null=True),
        ),
        migrations.RunPython(backfill_due_dates, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='invoice',
            name='due_date',
            field=models.DateField(),
        ),
    ]
