/**
 * A four-block chain animating a BTC payment moving from "seen in the
 * mempool" to "confirmed" -- purely decorative, so it's `aria-hidden`
 * and carries no meaning on its own; the adjacent status text is what
 * actually says what's happening.
 *
 * While waiting, the first three blocks fill left-to-right on a loop
 * and the last stays dashed and pulsing, representing the block still
 * being mined. Once `confirmed`, that last block snaps solid with a
 * checkmark in a one-shot animation rather than the looping wait
 * state, since confirmation is an event, not an ongoing process.
 * @param props.confirmed - Whether the tx has confirmed. Defaults to
 *   false (the looping "still waiting" chain).
 */
export function BtcBroadcastBlocks({
  confirmed = false,
}: {
  confirmed?: boolean;
}) {
  return (
    <span className="btc-blocks" aria-hidden="true">
      <span className="btc-blocks__block" />
      <span className="btc-blocks__block" />
      <span className="btc-blocks__block" />
      <span
        className={
          confirmed
            ? 'btc-blocks__block btc-blocks__block--confirmed'
            : 'btc-blocks__block btc-blocks__block--pending'
        }
      >
        {confirmed && '✓'}
      </span>
    </span>
  );
}
