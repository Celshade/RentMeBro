/** A payment rail an invoice line item can be paid or settled on. */
export type Rail = 'btc' | 'card' | 'cash' | 'check' | 'other';


/** Default tooltip/screen-reader text for each rail, unsettled. */
const DEFAULT_LABEL: Record<Rail, string> = {
  btc: 'Payable in Bitcoin',
  card: 'Payable by card (Cash App)',
  cash: 'Paid in cash',
  check: 'Paid by check',
  other: 'Paid by another method',
};


/** Default tooltip/screen-reader text for each rail, once settled. */
const SETTLED_DEFAULT_LABEL: Record<Rail, string> = {
  btc: 'Paid in Bitcoin',
  card: 'Paid by card (Cash App)',
  cash: 'Paid in cash',
  check: 'Paid by check',
  other: 'Paid by another method',
};


/** Short label for a manual rail, shown in its settled badge. */
export const MANUAL_RAIL_LABEL: Record<'cash' | 'check' | 'other', string> = {
  cash: 'Cash',
  check: 'Check',
  other: 'Other',
};


/** Emoji identifying a manual rail in its settled badge. */
export const MANUAL_RAIL_EMOJI: Record<'cash' | 'check' | 'other', string> = {
  cash: '💵',
  check: '🧾',
  other: '📝',
};


/**
 * A small symbol marking one payment rail as available on -- or, when
 * `settled` is set, as having paid -- an invoice, meant for glanceable
 * stat tiles and dashboard rows rather than spelling the rail out in
 * words.
 * @param props.rail - Which rail to render: 'btc' for the ₿ glyph,
 *   'card' for an inline card icon representing Cash App, 'cash' for
 *   a coin icon, 'check' for a check icon, or 'other' for a generic
 *   marker.
 * @param props.label - Tooltip/screen-reader text. Defaults to a
 *   rail-appropriate description.
 * @param props.settled - Marks the glyph as a completed payment rather
 *   than an available one: adds a `rail-glyph--settled` chip style and,
 *   for the manual rails, swaps the SVG icon for the same emoji used in
 *   `InvoiceDetail`'s settlement badge.
 */
export function PaymentRailGlyph({
  rail,
  label,
  settled,
}: {
  rail: Rail;
  label?: string;
  settled?: boolean;
}) {
  const text =
    label ?? (settled ? SETTLED_DEFAULT_LABEL : DEFAULT_LABEL)[rail];
  const className =
    `rail-glyph rail-glyph--${rail}` + (settled ? ' rail-glyph--settled' : '');
  const isManualRail = rail === 'cash' || rail === 'check' || rail === 'other';
  if (settled && isManualRail) {
    return (
      <span className={className} title={text} aria-label={text}>
        {MANUAL_RAIL_EMOJI[rail]}
      </span>
    );
  }
  return (
    <span className={className} title={text} aria-label={text}>
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
