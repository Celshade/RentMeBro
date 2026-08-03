import { useCallback, useEffect, useRef, useState } from 'react';
import qrcode from 'qrcode-generator';
import { apiFetch } from '../api/client';
import { satsToBtc } from '../api/format';
import type { BtcInvoiceStatus } from '../api/types';

const POLL_INTERVAL_MS = 60_000;


/** Whether the initial "have we seen any tx yet" window has lapsed. */
function isWatchExpired(expiresAt: string | null): boolean {
  return expiresAt !== null && new Date(expiresAt) <= new Date();
}


/**
 * Renter's "Pay with BTC" panel: shows the landlord's fixed address and
 * amount as a copyable address, a `bitcoin:` URI QR code, and polls
 * every 60 seconds for the payment to be seen/confirmed while the
 * panel stays open.
 * @param props.invoiceId - The invoice being paid.
 * @param props.onPaid - Called once the BTC payment is confirmed.
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
    if (btcStatus === null) return;
    if (btcStatus.status === 'paid') {
      onPaidRef.current();
      return;
    }
    if (isWatchExpired(btcStatus.btc_watch_expires_at)) return;

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
  if (btcStatus.status === 'paid') return <p>Payment received!</p>;

  const amountSats = btcStatus.btc_amount_sats ?? 0;
  const bitcoinUri = `bitcoin:${btcStatus.btc_address}?amount=${satsToBtc(
    amountSats
  )}`;
  const qr = qrcode(0, 'M');
  qr.addData(bitcoinUri);
  qr.make();
  const qrDataUrl = qr.createDataURL(6, 4);
  const expired = isWatchExpired(btcStatus.btc_watch_expires_at);

  return (
    <div className="pay-invoice-btc">
      <img
        className="pay-invoice-btc__qr"
        src={qrDataUrl}
        alt="Bitcoin payment QR code"
      />
      <p>Send exactly {satsToBtc(amountSats)} BTC to:</p>
      <p className="pay-invoice-btc__address">{btcStatus.btc_address}</p>
      <p>
        {btcStatus.status === 'pending'
          ? 'Payment seen, waiting for confirmation...'
          : expired
            ? 'No payment detected yet.'
            : 'Waiting for payment...'}
      </p>
      {expired && (
        <button type="button" onClick={startWatch}>
          Check again
        </button>
      )}
    </div>
  );
}
