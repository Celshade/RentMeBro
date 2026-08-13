/** Default tooltip/screen-reader text for each rail. */
const DEFAULT_LABEL: Record<
  'btc' | 'card' | 'cash' | 'check' | 'other',
  string
> = {
  btc: 'Payable in Bitcoin',
  card: 'Payable by card (Cash App)',
  cash: 'Paid in cash',
  check: 'Paid by check',
  other: 'Paid by another method',
};


/**
 * A small symbol marking one payment rail as available on -- or, for
 * the manual rails, as having settled -- an invoice, meant for
 * glanceable stat tiles and dashboard rows rather than spelling the
 * rail out in words.
 * @param props.rail - Which rail to render: 'btc' for the ₿ glyph,
 *   'card' for an inline card icon representing Cash App, 'cash' for
 *   a coin icon, 'check' for a check icon, or 'other' for a generic
 *   marker.
 * @param props.label - Tooltip/screen-reader text. Defaults to a
 *   rail-appropriate description.
 */
export function PaymentRailGlyph({
  rail,
  label,
}: {
  rail: 'btc' | 'card' | 'cash' | 'check' | 'other';
  label?: string;
}) {
  const text = label ?? DEFAULT_LABEL[rail];
  return (
    <span
      className={`rail-glyph rail-glyph--${rail}`}
      title={text}
      aria-label={text}
    >
      {rail === 'btc' ? (
        '₿'
      ) : rail === 'card' ? (
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
      ) : rail === 'cash' ? (
        <svg
          viewBox="0 0 24 24"
          width="1em"
          height="1em"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="9" />
          <text
            x="12"
            y="16"
            textAnchor="middle"
            fontSize="11"
            stroke="none"
            fill="currentColor"
          >
            $
          </text>
        </svg>
      ) : rail === 'check' ? (
        <svg
          viewBox="0 0 24 24"
          width="1em"
          height="1em"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden="true"
        >
          <rect x="2" y="6" width="20" height="12" rx="2" />
          <path d="M6 14l3 3 6-6" />
        </svg>
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
          <circle cx="12" cy="12" r="9" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <circle cx="12" cy="16" r="0.5" fill="currentColor" />
        </svg>
      )}
    </span>
  );
}
