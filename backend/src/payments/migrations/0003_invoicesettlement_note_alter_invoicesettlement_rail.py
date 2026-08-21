from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0002_backfill_settlements'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoicesettlement',
            name='note',
            field=models.CharField(blank=True, max_length=255, default=''),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='invoicesettlement',
            name='rail',
            field=models.CharField(
                choices=[
                    ('btc', 'Bitcoin'),
                    ('card', 'Card / Cash App'),
                    ('cash', 'Cash'),
                    ('check', 'Check'),
                    ('other', 'Other'),
                ],
                max_length=8,
            ),
        ),
    ]
