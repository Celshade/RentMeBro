/**
 * A small orange ₿ marking an invoice that has a Bitcoin address
 * attached, sat inline ahead of the invoice's label.
 *
 * Deliberately not a status pill: having a BTC address is a property of
 * the invoice that holds for its whole life, not a step in the payment
 * lifecycle, so it reads as row chrome (this glyph plus the
 * `invoice-row--btc` edge accent) and leaves the pill slot free for
 * lifecycle state. Pairing the glyph with the accent color also keeps
 * the marker legible without relying on color alone.
 * @param props.address - The invoice's attached BTC address. Renders
 *   nothing when empty, so callers can pass `invoice.btc_address`
 *   straight through without guarding first.
 * @param props.label - What the glyph is marking, for the tooltip and
 *   screen readers. Defaults to the whole-invoice wording; pass
 *   something else when marking a single line item.
 */
export function BtcAttachedGlyph({
  address,
  label = 'Bitcoin payment available',
}: {
  address: string;
  label?: string;
}) {
  if (!address) return null;
  return (
    <span
      className="btc-glyph"
      title={`${label} — ${address}`}
      aria-label={label}
    >
      ₿
    </span>
  );
}
