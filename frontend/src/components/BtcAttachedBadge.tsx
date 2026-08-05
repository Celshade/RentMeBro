/**
 * A small orange "₿ BTC" pill marking an invoice that has a Bitcoin
 * address attached to it, shown alongside the invoice status badge.
 *
 * Rendered for both sides of an invoice: it tells a landlord the
 * address they attached actually stuck, and tells a renter that paying
 * with BTC is an option on this invoice.
 * @param props.address - The invoice's attached BTC address. Renders
 *   nothing when empty, so callers can pass `invoice.btc_address`
 *   straight through without guarding first.
 */
export function BtcAttachedBadge({ address }: { address: string }) {
  if (!address) return null;
  return (
    <span
      className="status-badge status-badge--btc"
      title={`Bitcoin payment available — ${address}`}
    >
      ₿ BTC
    </span>
  );
}
