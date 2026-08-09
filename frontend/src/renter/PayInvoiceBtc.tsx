import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import qrcode from 'qrcode-generator';
import { apiFetch } from '../api/client';
import {
  formatClockTime,
  formatCountdown,
  formatMoney,
  satsToBtc,
} from '../api/format';
import type { BtcInvoiceStatus } from '../api/types';
import { BtcBroadcastBlocks } from '../components/BtcBroadcastBlocks';
import { BtcTxLink } from '../components/BtcTxLink';

// Pre-payment the watch window is hard-capped at 15 min, so 60s buys
// a responsive "we saw it" moment at a bounded request cost. Once a
// tx is seen the poll is unbounded -- a low-fee tx can sit in the
// mempool for hours, and the check-on-read path (billing/views.py)
// means this panel isn't the only thing that will notice a
// confirmation -- so it backs off to 90s, which trims ~33% of calls
// in that unbounded phase for ~15s of added mean latency against a
// ~10-minute confirmation cadence.
const POLL_INTERVAL_MS = 60_000;
const CONFIRM_POLL_INTERVAL_MS = 90_000;


/**
 * Whether the initial "have we seen any tx yet" window has lapsed.
 * @param expiresAt - The watch window's expiry (ISO 8601), or null if
 *   no watch is in progress.
 * @param now - The current time, passed in so callers (render and the
 *   polling effect) can share one clock reading.
 */
function isWatchExpired(expiresAt: string | null, now: Date): boolean {
  return expiresAt !== null && new Date(expiresAt) <= now;
}


/**
 * The renter-facing status line for the pre-broadcast panel (QR,
 * address, countdown). A tx being seen moves the panel to a separate
 * awaiting-confirmation branch entirely, so this never has to
 * distinguish that state.
 */
function statusCopy(
  btcStatus: Pick<BtcInvoiceStatus, 'status' | 'remainder_owed_usd'>,
  expired: boolean
): string {
  if (btcStatus.status === 'underpaid' && btcStatus.remainder_owed_usd) {
    return `Payment was short -- $${formatMoney(
      btcStatus.remainder_owed_usd
    )} still owed`;
  }
  return expired ? 'No payment detected yet.' : 'Waiting for payment...';
}


/**
 * Renter's "Pay with BTC" panel. Before a tx is seen, shows the
 * landlord's fixed address and amount as a copyable address plus a
 * `bitcoin:` URI QR code, polling every 60 seconds. Once a tx is seen
 * in the mempool, the panel switches to an awaiting-confirmation view
 * (QR/address/countdown dropped, since the renter has already paid)
 * and polling backs off to 90 seconds. Polling continues past the
 * quote's expiry once a tx has been seen, since a late confirmation is
 * still worth watching for.
 * @param props.invoiceId - The invoice being paid.
 * @param props.onPaid - Called once the whole invoice is paid.
 */
export function PayInvoiceBtc({
  invoiceId,
  onPaid,
}: {
  invoiceId: number;
  onPaid: () => void;
}) {
  const [btcStatus, setBtcStatus] = useState<BtcInvoiceStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => new Date());
  const onPaidRef = useRef(onPaid);
  onPaidRef.current = onPaid;
  // A settled round's txid is cleared from btcStatus.btc_txid the
  // moment it settles, so the confirmed views below can't read it
  // straight off the latest status -- this remembers the last
  // non-empty one seen.
  const lastTxidRef = useRef('');
  if (btcStatus?.btc_txid) lastTxidRef.current = btcStatus.btc_txid;

  const startWatch = useCallback(() => {
    setError(null);
    apiFetch<BtcInvoiceStatus>(`/api/invoices/${invoiceId}/btc/watch/`, {
      method: 'POST',
    })
      .then(setBtcStatus)
      .catch(() => setError('Could not start watching for payment.'));
  }, [invoiceId]);

  useEffect(() => {
    startWatch();
  }, [startWatch]);

  useEffect(() => {
    // No countdown is shown once a tx has been seen or there's
    // nothing left owed via BTC, so there's nothing for a 1s tick to
    // drive.
    if (
      !btcStatus ||
      btcStatus.btc_txid ||
      Number(btcStatus.btc_owed_usd) === 0
    ) {
      return;
    }
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, [btcStatus]);

  useEffect(() => {
    if (btcStatus === null) return;
    if (btcStatus.status === 'paid') {
      onPaidRef.current();
      return;
    }
    if (Number(btcStatus.btc_owed_usd) === 0) return;
    if (
      isWatchExpired(btcStatus.btc_watch_expires_at, new Date()) &&
      !btcStatus.btc_txid
    ) {
      return;
    }

    const intervalMs = btcStatus.btc_txid
      ? CONFIRM_POLL_INTERVAL_MS
      : POLL_INTERVAL_MS;
    const timer = setInterval(() => {
      apiFetch<BtcInvoiceStatus>(`/api/invoices/${invoiceId}/btc/check/`, {
        method: 'POST',
      })
        .then(setBtcStatus)
        .catch(() => setError('Could not check payment status.'));
    }, intervalMs);
    return () => clearInterval(timer);
  }, [btcStatus, invoiceId]);

  // Hooks must run unconditionally, so this sits above the early
  // returns and tolerates a null btcStatus -- without the memo the QR
  // was being rebuilt every second by the countdown ticker.
  const qrDataUrl = useMemo(() => {
    if (!btcStatus?.btc_address || btcStatus.btc_amount_sats === null) {
      return null;
    }
    const bitcoinUri = `bitcoin:${btcStatus.btc_address}?amount=${satsToBtc(
      btcStatus.btc_amount_sats
    )}`;
    const qr = qrcode(0, 'M');
    qr.addData(bitcoinUri);
    qr.make();
    return qr.createDataURL(6, 4);
  }, [btcStatus?.btc_address, btcStatus?.btc_amount_sats]);

  if (error) return <p role="alert">{error}</p>;
  if (btcStatus === null) return <p>Preparing BTC payment...</p>;
  if (btcStatus.status === 'paid' || Number(btcStatus.btc_owed_usd) === 0) {
    return (
      <div className="pay-invoice-btc">
        <BtcBroadcastBlocks confirmed />
        <p className="pay-invoice-btc__seen">Payment confirmed</p>
        <BtcTxLink txid={lastTxidRef.current} />
      </div>
    );
  }
  if (btcStatus.btc_settled_at !== null) {
    // A round settled but not everything owed via BTC was covered by
    // it -- the renter must explicitly restart the watch for the
    // remainder, since settling clears the live quote fields.
    return (
      <div className="pay-invoice-btc">
        <BtcBroadcastBlocks confirmed />
        <p className="pay-invoice-btc__seen">Payment confirmed</p>
        <BtcTxLink txid={lastTxidRef.current} />
        <p className="pay-invoice-btc__seen-note">
          ${formatMoney(btcStatus.btc_owed_usd)} is still owed via BTC.
        </p>
        <button type="button" onClick={startWatch}>
          Pay the rest
        </button>
      </div>
    );
  }
  if (btcStatus.btc_txid) {
    // Seen in the mempool but not yet confirmed. QR, address, and
    // countdown are deliberately gone -- the renter has already paid,
    // so those elements now just mislead / invite a duplicate send.
    return (
      <div className="pay-invoice-btc">
        <BtcBroadcastBlocks />
        <p className="pay-invoice-btc__seen">Payment seen on the network</p>
        <p className="pay-invoice-btc__seen-sub">Waiting for confirmation…</p>
        <BtcTxLink txid={btcStatus.btc_txid} pending />
        <p className="pay-invoice-btc__seen-note">
          You're done -- no need to send again. This usually confirms
          within an hour, and you can close this page.
        </p>
      </div>
    );
  }
  if (
    btcStatus.btc_amount_sats === null ||
    btcStatus.btc_watch_expires_at === null
  ) {
    return (
      <div className="pay-invoice-btc">
        <p>BTC price is temporarily unavailable.</p>
        <button type="button" onClick={startWatch}>
          Try again
        </button>
      </div>
    );
  }

  const amountSats = btcStatus.btc_amount_sats;
  const expired = isWatchExpired(btcStatus.btc_watch_expires_at, now);
  const msRemaining =
    new Date(btcStatus.btc_watch_expires_at).getTime() - now.getTime();

  return (
    <div className="pay-invoice-btc">
      {qrDataUrl && (
        <img
          className="pay-invoice-btc__qr"
          src={qrDataUrl}
          alt="Bitcoin payment QR code"
        />
      )}
      <p>Send exactly {satsToBtc(amountSats)} BTC to:</p>
      <p className="pay-invoice-btc__address">{btcStatus.btc_address}</p>
      <p className="pay-invoice-btc__countdown">
        Quote expires in {formatCountdown(msRemaining)}
      </p>
      <p className="pay-invoice-btc__expiry">
        (expires {formatClockTime(btcStatus.btc_watch_expires_at)})
      </p>
      <p>{statusCopy(btcStatus, expired)}</p>
      {expired && (
        <button type="button" onClick={startWatch}>
          Get a new quote
        </button>
      )}
    </div>
  );
}
