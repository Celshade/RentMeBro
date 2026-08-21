from decimal import Decimal

from django.db import migrations
from django.db.models import Q


def backfill_settlements(apps, schema_editor):
    """Creates settlement rows for invoices that already settled a leg.

    Historical models have no properties, so the old
    `_btc_covers_everything` semantics are recomputed inline: a
    landlord who scoped BTC to every line item (or left it unscoped)
    could settle the whole invoice from either leg alone, so that
    leg's settlement is backfilled to cover every line item rather
    than just `btc_line_items`.
    """
    Invoice = apps.get_model('billing', 'Invoice')
    InvoiceSettlement = apps.get_model('payments', 'InvoiceSettlement')

    invoices = Invoice.objects.filter(
        Q(btc_settled_at__isnull=False) | Q(stripe_settled_at__isnull=False)
    )
    for invoice in invoices:
        all_items = list(invoice.line_items.all())
        btc_items = list(invoice.btc_line_items.all())
        assigned = len(btc_items)
        covers_everything = assigned == 0 or assigned == len(all_items)
        is_split = bool(invoice.btc_address) and not covers_everything

        if invoice.btc_settled_at is not None:
            btc_settlement_items = btc_items if is_split else all_items
            txid = invoice.btc_txid or f'legacy-btc-{invoice.id}'
            settlement, _ = InvoiceSettlement.objects.get_or_create(
                invoice=invoice,
                txid=txid,
                defaults={
                    'rail': 'btc',
                    'amount_usd': sum(
                        (item.amount for item in btc_settlement_items),
                        Decimal('0'),
                    ),
                    'amount_sats': invoice.btc_amount_sats,
                    'overpaid_usd': invoice.btc_overpaid_usd,
                    'settled_at': invoice.btc_settled_at,
                },
            )
            settlement.line_items.set(btc_settlement_items)

        if invoice.stripe_settled_at is not None:
            btc_ids = {item.id for item in btc_items}
            card_settlement_items = (
                [item for item in all_items if item.id not in btc_ids]
                if is_split
                else all_items
            )
            intent_id = (
                invoice.stripe_payment_intent_id
                or f'legacy-card-{invoice.id}'
            )
            settlement, _ = InvoiceSettlement.objects.get_or_create(
                invoice=invoice,
                stripe_payment_intent_id=intent_id,
                defaults={
                    'rail': 'card',
                    'amount_usd': sum(
                        (item.amount for item in card_settlement_items),
                        Decimal('0'),
                    ),
                    'settled_at': invoice.stripe_settled_at,
                },
            )
            settlement.line_items.set(card_settlement_items)


def clear_settlements(apps, schema_editor):
    InvoiceSettlement = apps.get_model('payments', 'InvoiceSettlement')
    InvoiceSettlement.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(backfill_settlements, clear_settlements),
    ]
