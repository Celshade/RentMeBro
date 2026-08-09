import type { Invoice, InvoiceLineItem, InvoiceSettlement } from './types';


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
 * Which payment rails can pay a single line item right now.
 * @param invoice - The invoice the item belongs to.
 * @param item - The line item to check.
 * @returns `btc` is true when an address is attached, the item isn't
 *   locked to card-only, and it's either locked to BTC-only or
 *   explicitly assigned via `btc_line_items` -- assignment is
 *   binding, so an unassigned item never reads as BTC-payable. `card`
 *   is true whenever the item isn't locked to BTC-only.
 */
export function lineItemRails(
  invoice: Invoice,
  item: InvoiceLineItem
): { btc: boolean; card: boolean } {
  return {
    btc:
      invoice.btc_address !== '' &&
      item.payment_lock !== 'card' &&
      (item.payment_lock === 'btc' ||
        invoice.btc_line_items.includes(item.id)),
    card: item.payment_lock !== 'btc',
  };
}


/**
 * Which payment rails are actually usable on this invoice right now,
 * for a glanceable summary rather than spelling out every line item's
 * lock. The union of `lineItemRails` over every unpaid line item, so
 * the tile can never drift from what the rows themselves say.
 * @param invoice - The invoice to summarize.
 * @returns Whether BTC and/or card can still pay something on this
 *   invoice.
 */
export function paymentRails(invoice: Invoice): {
  btc: boolean;
  card: boolean;
} {
  return invoice.line_items
    .filter((item) => !isLineItemPaid(invoice, item.id))
    .reduce<{ btc: boolean; card: boolean }>(
      (rails, item) => {
        const itemRails = lineItemRails(invoice, item);
        return {
          btc: rails.btc || itemRails.btc,
          card: rails.card || itemRails.card,
        };
      },
      { btc: false, card: false }
    );
}
