from django.db import migrations, models


def copy_btc_line_item(apps, schema_editor):
    """Carries each invoice's single assigned line item into the new set."""
    Invoice = apps.get_model('billing', 'Invoice')
    for invoice in Invoice.objects.exclude(btc_line_item=None):
        invoice.btc_line_items.add(invoice.btc_line_item)


def restore_btc_line_item(apps, schema_editor):
    """Collapses the set back to one item, keeping the lowest id."""
    Invoice = apps.get_model('billing', 'Invoice')
    for invoice in Invoice.objects.all():
        item = invoice.btc_line_items.order_by('id').first()
        if item is not None:
            invoice.btc_line_item = item
            invoice.save(update_fields=['btc_line_item'])


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0011_invoice_underpaid_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='btc_line_items',
            field=models.ManyToManyField(
                blank=True, related_name='+', to='billing.invoicelineitem'
            ),
        ),
        migrations.RunPython(copy_btc_line_item, restore_btc_line_item),
        migrations.RemoveField(
            model_name='invoice',
            name='btc_line_item',
        ),
    ]
