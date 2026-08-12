import { formatTxidShort, mempoolTxUrl } from '../api/format';


/**
 * A link to a BTC transaction's mempool.space (or configured explorer)
 * page, shown as its shortened txid.
 * @param props.txid - The full transaction id. Renders nothing when
 *   empty, so callers don't have to guard at the call site.
 * @param props.pending - Whether the tx is still awaiting confirmation.
 *   Adds a "(pending)" suffix and modifier class rather than a separate
 *   component, since the link itself doesn't change.
 */
export function BtcTxLink({
  txid,
  pending = false,
}: {
  txid: string;
  pending?: boolean;
}) {
  if (!txid) return null;
  return (
    <a
      className={pending ? 'btc-tx-link btc-tx-link--pending' : 'btc-tx-link'}
      href={mempoolTxUrl(txid)}
      target="_blank"
      rel="noopener noreferrer"
      title={txid}
    >
      {formatTxidShort(txid)}
      {pending && ' (pending)'}
    </a>
  );
}
