from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def reset_gas_billing_data(apps, schema_editor):
    """Clears gas-billing records ahead of the FK restructuring.

    These are local dev/test rows; the shape of the (landlord,
    renter) pair they'll be re-keyed on doesn't exist yet, so there's
    nothing meaningful to migrate forward.
    """
    Invoice = apps.get_model('billing', 'Invoice')
    BillingPeriod = apps.get_model('billing', 'BillingPeriod')
    MileageProfile = apps.get_model('billing', 'MileageProfile')
    GasPriceEntry = apps.get_model('billing', 'GasPriceEntry')
    DrivenDayLog = apps.get_model('billing', 'DrivenDayLog')

    Invoice.objects.all().delete()
    BillingPeriod.objects.all().delete()
    MileageProfile.objects.all().delete()
    GasPriceEntry.objects.all().delete()
    DrivenDayLog.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('billing', '0003_lease_document_lease_lease_type_lease_term_months'),
    ]

    operations = [
        migrations.RunPython(
            reset_gas_billing_data, migrations.RunPython.noop
        ),
        migrations.AlterUniqueTogether(
            name='drivendaylog',
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name='billingperiod',
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name='invoice',
            unique_together=set(),
        ),
        migrations.RemoveField(model_name='mileageprofile', name='lease'),
        migrations.RemoveField(model_name='gaspriceentry', name='lease'),
        migrations.RemoveField(model_name='drivendaylog', name='lease'),
        migrations.RemoveField(model_name='billingperiod', name='lease'),
        migrations.RemoveField(model_name='invoice', name='lease'),
        migrations.AddField(
            model_name='mileageprofile',
            name='landlord',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='mileage_profiles_as_landlord',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='mileageprofile',
            name='renter',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='mileage_profiles_as_renter',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='gaspriceentry',
            name='landlord',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='gas_price_entries_as_landlord',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='gaspriceentry',
            name='renter',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='gas_price_entries_as_renter',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='drivendaylog',
            name='landlord',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='driven_day_logs_as_landlord',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='drivendaylog',
            name='renter',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='driven_day_logs_as_renter',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='billingperiod',
            name='landlord',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='billing_periods_as_landlord',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='billingperiod',
            name='renter',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='billing_periods_as_renter',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterUniqueTogether(
            name='drivendaylog',
            unique_together={('landlord', 'renter', 'date')},
        ),
        migrations.AlterUniqueTogether(
            name='billingperiod',
            unique_together={('landlord', 'renter', 'year', 'month')},
        ),
        migrations.AlterUniqueTogether(
            name='invoice',
            unique_together={('billing_period', 'kind')},
        ),
    ]
