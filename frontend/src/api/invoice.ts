import type { Invoice } from './types';

/** Which rail a line item is billed through, or 'either' when BTC is
 * unscoped (or scoped to every item) and so either leg can cover it. */
export type LineItemLeg = 'btc' | 'card' | 'either';


/**
 * Whether BTC is scoped to a strict subset of an invoice's line items.
 * Mirrors `Invoice._btc_covers_everything` on the backend
 * (`billing/models.py`): an empty scope or one spanning every item
 * both mean the card leg can still bill the full total, so neither
 * counts as a split.
 * @param invoice - The invoice to check.
 */
function btcCoversEverything(invoice: Invoice): boolean {
  const assigned = invoice.btc_line_items.length;
  return assigned === 0 || assigned === invoice.line_items.length;
}


/**
 * Which rail a line item is billed through.
 * @param invoice - The invoice the item belongs to.
 * @param itemId - The line item's id.
 * @returns 'either' when BTC is unscoped or covers every item, since
 *   either leg can settle it; otherwise 'btc' for assigned items and
 *   'card' for the rest.
 */
export function lineItemLeg(invoice: Invoice, itemId: number): LineItemLeg {
  if (btcCoversEverything(invoice)) return 'either';
  return invoice.btc_line_items.includes(itemId) ? 'btc' : 'card';
}


/**
 * Whether a line item has been paid.
 * @param invoice - The invoice the item belongs to.
 * @param itemId - The line item's id.
 * @returns True once the leg billing this item has settled. For an
 *   'either' item, either leg settling is enough.
 */
export function isLineItemPaid(invoice: Invoice, itemId: number): boolean {
  const leg = lineItemLeg(invoice, itemId);
  if (leg === 'either') {
    return (
      invoice.btc_settled_at !== null || invoice.stripe_settled_at !== null
    );
  }
  if (leg === 'btc') return invoice.btc_settled_at !== null;
  return invoice.stripe_settled_at !== null;
}
