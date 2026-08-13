from django.db import migrations


def mark_address_only_invoices_as_fully_btc(apps, schema_editor):
    """Assigns every line item on invoices that only have an address.

    Before the dashboard's BTC indicator was tied to btc_line_items,
    an attached address with an empty btc_line_items set meant "BTC
    covers the whole invoice" -- the same meaning scoping every line
    item now has. Backfilling those invoices to the explicit form
    keeps their existing behavior (and their dashboard indicator)
    unchanged: an empty set now unambiguously means nothing has been
    marked as BTC-billed yet.
    """
    Invoice = apps.get_model('billing', 'Invoice')
    for invoice in Invoice.objects.exclude(btc_address='').filter(
        btc_line_items__isnull=True
    ):
        invoice.btc_line_items.set(invoice.line_items.all())


def clear_fully_assigned_scopes(apps, schema_editor):
    """Reverses the backfill: clears scopes that cover every line item."""
    Invoice = apps.get_model('billing', 'Invoice')
    for invoice in Invoice.objects.exclude(btc_address=''):
        assigned = invoice.btc_line_items.count()
        if assigned and assigned == invoice.line_items.count():
            invoice.btc_line_items.clear()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0012_invoice_btc_line_items'),
    ]

    operations = [
        migrations.RunPython(
            mark_address_only_invoices_as_fully_btc,
            clear_fully_assigned_scopes,
        ),
    ]
