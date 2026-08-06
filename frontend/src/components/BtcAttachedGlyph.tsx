/**
 * A small orange ₿ marking an invoice (or line item) that's actually
 * being billed in Bitcoin, sat inline ahead of its label.
 *
 * Deliberately not a status pill: being billed in BTC is a property
 * that holds for the item's whole life, not a step in the payment
 * lifecycle, so it reads as row chrome (this glyph plus the
 * `invoice-row--btc` edge accent) and leaves the pill slot free for
 * lifecycle state. Pairing the glyph with the accent color also keeps
 * the marker legible without relying on color alone.
 * @param props.address - The BTC address to show once billing is
 *   confirmed. Renders nothing when empty, so callers can pass `''`
 *   for an invoice/line item that has an address attached but isn't
 *   marked as BTC-billed, rather than guarding at the call site.
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
