/**
 * A small symbol marking one payment rail (Bitcoin or card/Cash App)
 * as available on an invoice, meant for glanceable stat tiles rather
 * than spelling the rail out in words.
 *
 * Deliberately its own component rather than a reuse of
 * `BtcAttachedGlyph`: that glyph's contract is "an address is
 * attached, and the address goes in the tooltip" -- it marks a
 * specific line item as actually billed in BTC. This one just answers
 * "can this rail still be used at all", with no address involved.
 * @param props.rail - Which rail to render: 'btc' for the ₿ glyph,
 *   'card' for an inline card icon representing Cash App.
 * @param props.label - Tooltip/screen-reader text. Defaults to a
 *   rail-appropriate description.
 */
export function PaymentRailGlyph({
  rail,
  label,
}: {
  rail: 'btc' | 'card';
  label?: string;
}) {
  const text =
    label ??
    (rail === 'btc' ? 'Payable in Bitcoin' : 'Payable by card (Cash App)');
  return (
    <span
      className={`rail-glyph rail-glyph--${rail}`}
      title={text}
      aria-label={text}
    >
      {rail === 'btc' ? (
        '₿'
      ) : (
        <svg
          viewBox="0 0 24 24"
          width="1em"
          height="1em"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden="true"
        >
          <rect x="2" y="5" width="20" height="14" rx="2" />
          <line x1="2" y1="10" x2="22" y2="10" />
        </svg>
      )}
    </span>
  );
}
