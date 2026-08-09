import type { Invoice, InvoiceSettlement } from './types';


/**
 * Whether a line item has been paid.
 * @param invoice - The invoice the item belongs to.
 * @param itemId - The line item's id.
 * @returns True once a settlement covers this item -- the single
 *   authority for per-item paid state, mirroring
 *   `Invoice.paid_line_item_ids` on the backend.
 */
export function isLineItemPaid(invoice: Invoice, itemId: number): boolean {
  return invoice.paid_line_items.includes(itemId);
}


/**
 * Whether a line item may no longer be re-scoped or re-locked: paid,
 * or with a payment in flight on either rail.
 * @param invoice - The invoice the item belongs to.
 * @param itemId - The line item's id.
 */
export function isLineItemFrozen(invoice: Invoice, itemId: number): boolean {
  return invoice.frozen_line_items.includes(itemId);
}


/**
 * The settlement that paid a given line item, if any.
 * @param invoice - The invoice the item belongs to.
 * @param itemId - The line item's id.
 * @returns The covering `InvoiceSettlement`, powering per-item tx
 *   links, or undefined if the item isn't paid.
 */
export function settlementForLineItem(
  invoice: Invoice,
  itemId: number
): InvoiceSettlement | undefined {
  return invoice.settlements.find((s) => s.line_items.includes(itemId));
}


/**
 * Which payment rails are actually usable on this invoice right now,
 * for a glanceable summary rather than spelling out every line item's
 * lock. Does not consult `btc_line_items` -- that field is a
 * non-binding expectation of what BTC will cover, not a restriction,
 * so it says nothing about whether a rail is usable.
 * @param invoice - The invoice to summarize.
 * @returns Whether BTC and/or card can still pay something on this
 *   invoice. `card` is true when any item isn't locked to BTC-only;
 *   `btc` is true when an address is attached and at least one item
 *   isn't locked to card-only.
 */
export function paymentRails(invoice: Invoice): {
  btc: boolean;
  card: boolean;
} {
  return {
    card: Number(invoice.card_full_owed_usd) > 0,
    btc:
      invoice.btc_address !== '' &&
      invoice.line_items.some((item) => item.payment_lock !== 'card'),
  };
}
