import { formatMoney } from '../api/format';
import type { InvoiceLineItem } from '../api/types';
import { PaymentRailGlyph } from './PaymentRailGlyph';

const RAIL_HEADING: Record<'btc' | 'card', string> = {
  btc: "You're paying with Bitcoin",
  card: "You're paying by card",
};


/**
 * A per-leg "you're paying X" breakdown, shown above a payment panel
 * so the renter sees exactly what a rail is about to bill before they
 * commit to it -- distinct from the invoice's full line-item list,
 * which mixes both rails together.
 * @param props.rail - Which rail this summary is for.
 * @param props.lineItems - The invoice's full line-item list, used to
 *   look up each scoped item's description/amount.
 * @param props.itemIds - Which of `lineItems` this leg bills right
 *   now (e.g. `invoice.btc_scope_line_items`).
 * @param props.totalUsd - This leg's total, as a decimal string.
 * @param props.totalBtc - This leg's total in BTC, as a decimal
 *   string. Given only on the BTC leg, once a quote has locked a
 *   rate; omitted pre-quote or on the card leg.
 * @param props.note - Optional explanatory line shown below the
 *   total, e.g. crediting an already-covered amount toward a
 *   remainder quote.
 * @param props.heading - Overrides the default "you're paying X"
 *   heading -- used pre-quote, where nothing is locked in yet and the
 *   default phrasing would overstate commitment.
 */
export function PaymentLegSummary({
  rail,
  lineItems,
  itemIds,
  totalUsd,
  totalBtc,
  note,
  heading,
}: {
  rail: 'btc' | 'card';
  lineItems: InvoiceLineItem[];
  itemIds: number[];
  totalUsd: string;
  totalBtc?: string;
  note?: string;
  heading?: string;
}) {
  if (itemIds.length === 0) return null;
  const scopedItems = lineItems.filter((item) => itemIds.includes(item.id));

  return (
    <div className={`payment-leg-summary payment-leg-summary--${rail}`}>
      <p className="payment-leg-summary__heading">
        <PaymentRailGlyph
          rail={rail}
          label={
            rail === 'btc' ? 'Payable in Bitcoin' : 'Payable by card (Cash App)'
          }
        />
        {heading ?? RAIL_HEADING[rail]}
      </p>
      <ul className="payment-leg-summary__items">
        {scopedItems.map((item) => (
          <li key={item.id} className="payment-leg-summary__item">
            <span>{item.description}</span>
            <span>${formatMoney(item.amount)}</span>
          </li>
        ))}
      </ul>
      <p className="payment-leg-summary__total">
        {totalBtc !== undefined
          ? `${totalBtc} BTC ($${formatMoney(totalUsd)})`
          : `$${formatMoney(totalUsd)}`}
      </p>
      {note && <p className="payment-leg-summary__note">{note}</p>}
    </div>
  );
}
