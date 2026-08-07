import { useCallback, useEffect, useRef, useState } from 'react';
import qrcode from 'qrcode-generator';
import { apiFetch } from '../api/client';
import { formatClockTime, formatCountdown, formatMoney, satsToBtc } from '../api/format';
import type { BtcInvoiceStatus } from '../api/types';

const POLL_INTERVAL_MS = 60_000;


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


/** The renter-facing status line, driven by the fields that actually
 * distinguish these states -- not just `status`, which collapses
 * "tx seen, awaiting confirmation" and "nothing arrived" together once
 * the window lapses.
 */
function statusCopy(btcStatus: BtcInvoiceStatus, expired: boolean): string {
  if (btcStatus.btc_txid) {
    return 'Payment seen, waiting for confirmation...';
  }
  if (btcStatus.status === 'underpaid' && btcStatus.remainder_owed_usd) {
    return `Payment was short -- $${formatMoney(
      btcStatus.remainder_owed_usd
    )} still owed`;
  }
  return expired ? 'No payment detected yet.' : 'Waiting for payment...';
}


/**
 * Renter's "Pay with BTC" panel: shows the landlord's fixed address and
 * amount as a copyable address, a `bitcoin:` URI QR code, and polls
 * every 60 seconds for the payment to be seen/confirmed while the
 * panel stays open. Polling continues past the quote's expiry once a
 * tx has been seen, since a late confirmation is still worth watching
 * for.
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
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (btcStatus === null) return;
    if (btcStatus.status === 'paid') {
      onPaidRef.current();
      return;
    }
    if (btcStatus.btc_settled_at !== null) return;
    if (
      isWatchExpired(btcStatus.btc_watch_expires_at, new Date()) &&
      !btcStatus.btc_txid
    ) {
      return;
    }

    const timer = setInterval(() => {
      apiFetch<BtcInvoiceStatus>(`/api/invoices/${invoiceId}/btc/check/`, {
        method: 'POST',
      })
        .then(setBtcStatus)
        .catch(() => setError('Could not check payment status.'));
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [btcStatus, invoiceId]);

  if (error) return <p role="alert">{error}</p>;
  if (btcStatus === null) return <p>Preparing BTC payment...</p>;
  if (btcStatus.status === 'paid' || btcStatus.btc_settled_at !== null) {
    return <p>BTC payment received</p>;
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
  const bitcoinUri = `bitcoin:${btcStatus.btc_address}?amount=${satsToBtc(
    amountSats
  )}`;
  const qr = qrcode(0, 'M');
  qr.addData(bitcoinUri);
  qr.make();
  const qrDataUrl = qr.createDataURL(6, 4);
  const expired = isWatchExpired(btcStatus.btc_watch_expires_at, now);
  const msRemaining =
    new Date(btcStatus.btc_watch_expires_at).getTime() - now.getTime();

  return (
    <div className="pay-invoice-btc">
      <img
        className="pay-invoice-btc__qr"
        src={qrDataUrl}
        alt="Bitcoin payment QR code"
      />
      <p>Send exactly {satsToBtc(amountSats)} BTC to:</p>
      <p className="pay-invoice-btc__address">{btcStatus.btc_address}</p>
      <p className="pay-invoice-btc__countdown">
        Quote expires in {formatCountdown(msRemaining)}
      </p>
      <p className="pay-invoice-btc__expiry">
        (expires {formatClockTime(btcStatus.btc_watch_expires_at)})
      </p>
      <p>{statusCopy(btcStatus, expired)}</p>
      {expired && !btcStatus.btc_txid && (
        <button type="button" onClick={startWatch}>
          Get a new quote
        </button>
      )}
    </div>
  );
}
