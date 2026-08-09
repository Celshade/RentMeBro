import type { Invoice, InvoiceSettlement } from './types';

/** Which rail a line item is billed through.
 * - 'btc'/'card' from a `payment_lock` is *binding*: the other rail
 *   won't bill it.
 * - 'btc' from the BTC assignment alone is only an *expectation*: the
 *   card leg can still bill it if the renter pays by card instead.
 *   Both render the same "Due in BTC" copy to the renter, but the
 *   landlord's per-item lock control needs to tell them apart.
 * - 'either' means neither leg has been earmarked for it.
 */
export type LineItemLeg = 'btc' | 'card' | 'either';


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
 * Which rail a line item is billed through.
 * @param invoice - The invoice the item belongs to.
 * @param itemId - The line item's id.
 * @returns The settling rail if paid; the binding lock if one's set;
 *   'btc' if merely assigned to the BTC expectation; otherwise
 *   'either'.
 */
export function lineItemLeg(invoice: Invoice, itemId: number): LineItemLeg {
  const settlement = settlementForLineItem(invoice, itemId);
  if (settlement) return settlement.rail;

  const item = invoice.line_items.find((i) => i.id === itemId);
  if (item?.payment_lock) return item.payment_lock;

  return invoice.btc_line_items.includes(itemId) ? 'btc' : 'either';
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
