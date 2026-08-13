from django.db import models


class InvoiceSettlement(models.Model):
    """One completed payment round against an invoice, and what it bought.

    Lives in `payments`, not `billing`: the FK/M2M reference `billing`
    models by string, avoiding a circular import, and `billing` only
    ever touches the reverse `invoice.settlements` accessor.

    `amount_usd` is stored, not derived -- `recompute_invoice_gas`
    (`billing/services.py`) mutates line item amounts after the fact,
    and a derived figure would retroactively rewrite settled history.

    Rail-tagged rather than BTC-only: the card leg needs the same
    snapshot, since "card items = items outside the BTC scope" drifts
    the moment a later BTC round changes that scope.
    """

    class Rail(models.TextChoices):
        BTC = 'btc', 'Bitcoin'
        CARD = 'card', 'Card / Cash App'
        CASH = 'cash', 'Cash'
        CHECK = 'check', 'Check'
        OTHER = 'other', 'Other'

    invoice = models.ForeignKey(
        'billing.Invoice', on_delete=models.CASCADE,
        related_name='settlements',
    )
    rail = models.CharField(max_length=8, choices=Rail.choices)
    line_items = models.ManyToManyField(
        'billing.InvoiceLineItem', related_name='+'
    )
    amount_usd = models.DecimalField(max_digits=10, decimal_places=2)
    amount_sats = models.BigIntegerField(null=True, blank=True)
    txid = models.CharField(max_length=64, blank=True)
    credited_txid = models.CharField(max_length=64, blank=True)
    credited_usd = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    overpaid_usd = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True)
    note = models.CharField(max_length=255, blank=True)
    settled_at = models.DateTimeField()

    class Meta:
        ordering = ['settled_at', 'id']
        indexes = [
            models.Index(fields=['invoice', 'settled_at']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['invoice', 'txid'],
                condition=~models.Q(txid=''),
                name='unique_settlement_txid_per_invoice',
            ),
            models.UniqueConstraint(
                fields=['invoice', 'stripe_payment_intent_id'],
                condition=~models.Q(stripe_payment_intent_id=''),
                name='unique_settlement_intent_per_invoice',
            ),
        ]

    def __str__(self) -> str:
        return (
            f'InvoiceSettlement(invoice={self.invoice_id}, '
            f'rail={self.rail}, ${self.amount_usd})'
        )
