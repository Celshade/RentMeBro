import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import qrcode from 'qrcode-generator';
import { apiFetch } from '../api/client';
import {
  formatClockTime,
  formatCountdown,
  formatMoney,
  satsToBtc,
} from '../api/format';
import type {
  BtcInvoiceStatus,
  BtcPaymentClaim,
  InvoiceLineItem,
} from '../api/types';
import { BtcBroadcastBlocks } from '../components/BtcBroadcastBlocks';
import { BtcTxLink } from '../components/BtcTxLink';
import { PaymentLegSummary } from '../components/PaymentLegSummary';

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

// Mirrors payments/services.py's BTC_GRACE_PERIOD: the backend keeps
// matching an incoming tx against a lapsed watch for this long past
// its expiry, so the frontend must keep polling that long too, or a
// renter who pays right at the deadline sees silence instead of the
// confirmation that's actually coming.
const BTC_GRACE_PERIOD_MS = 3 * 60_000;


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
 * Whether the backend has stopped honouring a lapsed watch entirely,
 * i.e. even its grace period has passed.
 * @param expiresAt - The watch window's expiry (ISO 8601), or null if
 *   no watch is in progress.
 * @param now - The current time.
 */
function isGracePeriodOver(expiresAt: string | null, now: Date): boolean {
  return (
    expiresAt !== null &&
    now.getTime() > new Date(expiresAt).getTime() + BTC_GRACE_PERIOD_MS
  );
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
 * Fallback for whatever automatic BTC reconciliation misses: lets the
 * renter submit a txid directly for landlord review. Opens collapsed
 * behind a disclosure toggle so it doesn't compete with the primary
 * QR/address flow, and shows a static "submitted" state afterward
 * rather than polling -- the landlord's review happens outside this
 * panel.
 * @param props.invoiceId - The invoice being claimed as paid.
 */
function BtcClaimForm({ invoiceId }: { invoiceId: number }) {
  const [expanded, setExpanded] = useState(false);
  const [txid, setTxid] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [claim, setClaim] = useState<BtcPaymentClaim | null>(null);

  const submit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      setSubmitting(true);
      setError(null);
      apiFetch<BtcPaymentClaim>(`/api/invoices/${invoiceId}/btc/claim/`, {
        method: 'POST',
        body: { txid },
      })
        .then(setClaim)
        .catch((err: Error) => setError(err.message))
        .finally(() => setSubmitting(false));
    },
    [invoiceId, txid]
  );

  if (claim) {
    return (
      <p className="pay-invoice-btc__claim-submitted">
        Claim submitted for <code>{claim.txid}</code> -- pending landlord
        review.
      </p>
    );
  }

  if (!expanded) {
    return (
      <button
        type="button"
        className="pay-invoice-btc__claim-toggle"
        onClick={() => setExpanded(true)}
      >
        Already paid, but not showing up here?
      </button>
    );
  }

  return (
    <form className="pay-invoice-btc__claim-form" onSubmit={submit}>
      <label htmlFor="btc-claim-txid">
        Enter the transaction id you sent -- the landlord will review it.
      </label>
      <input
        id="btc-claim-txid"
        type="text"
        value={txid}
        onChange={(e) => setTxid(e.target.value)}
        required
      />
      {error && <p role="alert">{error}</p>}
      <button type="submit" disabled={submitting || txid.trim() === ''}>
        Submit claim
      </button>
    </form>
  );
}


/**
 * Renter's "Pay with BTC" panel. Opens idle -- no quote is minted
 * just by looking -- and shows the landlord's fixed address and
 * amount as a copyable address plus a `bitcoin:` URI QR code only
 * once the renter generates a quote, polling every 60 seconds. Once a
 * tx is seen in the mempool, the panel switches to an
 * awaiting-confirmation view (QR/address/countdown dropped, since the
 * renter has already paid) and polling backs off to 90 seconds.
 * Polling continues past the quote's expiry, through the backend's
 * grace period, since a late confirmation is still worth watching
 * for.
 * @param props.invoiceId - The invoice being paid.
 * @param props.lineItems - The invoice's full line-item list, passed
 *   through to `PaymentLegSummary` to look up scoped items.
 * @param props.fullOwedUsd - Every BTC-payable item's total, as a
 *   decimal string, ignoring the landlord's BTC scope -- the opt-in
 *   "pay it all by BTC instead" figure.
 * @param props.onPaid - Called once the whole invoice is paid.
 */
export function PayInvoiceBtc({
  invoiceId,
  lineItems,
  fullOwedUsd,
  onPaid,
}: {
  invoiceId: number;
  lineItems: InvoiceLineItem[];
  fullOwedUsd: string;
  onPaid: () => void;
}) {
  const [btcStatus, setBtcStatus] = useState<BtcInvoiceStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  // True once the renter has explicitly asked for a quote -- distinguishes
  // the default idle view from a real price outage, which shows once a
  // requested quote comes back still amount-less.
  const [quoteRequested, setQuoteRequested] = useState(false);
  const [payFull, setPayFull] = useState(false);
  const [now, setNow] = useState(() => new Date());
  const onPaidRef = useRef(onPaid);
  onPaidRef.current = onPaid;
  // A settled round's txid is cleared from btcStatus.btc_txid the
  // moment it settles, so the confirmed views below can't read it
  // straight off the latest status -- this remembers the last
  // non-empty one seen.
  const lastTxidRef = useRef('');
  if (btcStatus?.btc_txid) lastTxidRef.current = btcStatus.btc_txid;

  const fetchStatus = useCallback(() => {
    setError(null);
    apiFetch<BtcInvoiceStatus>(`/api/invoices/${invoiceId}/btc/status/`)
      .then((newStatus) => {
        setQuoteRequested(false);
        setBtcStatus(newStatus);
      })
      .catch(() => setError('Could not load BTC payment status.'));
  }, [invoiceId]);

  const generateQuote = useCallback(() => {
    setError(null);
    setQuoteRequested(true);
    apiFetch<BtcInvoiceStatus>(`/api/invoices/${invoiceId}/btc/watch/`, {
      method: 'POST',
      body: { pay_full: payFull },
    })
      .then(setBtcStatus)
      .catch(() => setError('Could not start watching for payment.'));
  }, [invoiceId, payFull]);

  const cancelQuote = useCallback(() => {
    setError(null);
    apiFetch<BtcInvoiceStatus>(`/api/invoices/${invoiceId}/btc/cancel/`, {
      method: 'POST',
    })
      .then((newStatus) => {
        setQuoteRequested(false);
        setBtcStatus(newStatus);
      })
      .catch((err: Error) => setError(err.message));
  }, [invoiceId]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  useEffect(() => {
    // No countdown is shown once a tx has been seen, there's nothing
    // left owed via BTC, or no watch is live -- nothing for a 1s tick
    // to drive. Stopping once the watch itself has expired keeps this
    // from ticking forever against a frozen 0:00.
    if (
      !btcStatus ||
      btcStatus.btc_txid ||
      btcStatus.btc_watch_expires_at === null ||
      Number(btcStatus.btc_owed_usd) === 0
    ) {
      return;
    }
    const expiresAt = btcStatus.btc_watch_expires_at;
    const timer = setInterval(() => {
      const tick = new Date();
      setNow(tick);
      if (isWatchExpired(expiresAt, tick)) clearInterval(timer);
    }, 1000);
    return () => clearInterval(timer);
  }, [btcStatus]);

  useEffect(() => {
    if (btcStatus === null) return;
    if (btcStatus.status === 'paid') {
      onPaidRef.current();
      return;
    }
    if (Number(btcStatus.btc_owed_usd) === 0) return;
    if (btcStatus.btc_watch_expires_at === null) return;
    if (
      isGracePeriodOver(btcStatus.btc_watch_expires_at, new Date()) &&
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

  if (btcStatus === null) {
    if (error) {
      return (
        <div className="pay-invoice-btc">
          <p role="alert">{error}</p>
          <button type="button" onClick={fetchStatus}>
            Retry
          </button>
        </div>
      );
    }
    return <p>Preparing BTC payment...</p>;
  }

  const errorBanner = error && <p role="alert">{error}</p>;

  if (btcStatus.status === 'paid') {
    return (
      <div className="pay-invoice-btc">
        {errorBanner}
        <BtcBroadcastBlocks confirmed />
        <p className="pay-invoice-btc__seen">Payment confirmed</p>
        <BtcTxLink txid={lastTxidRef.current} />
      </div>
    );
  }
  if (
    Number(btcStatus.btc_owed_usd) === 0 &&
    Number(fullOwedUsd) === 0
  ) {
    // Nothing is scoped to BTC and there's no pay-full-by-BTC option
    // either -- distinct from the scoped amount alone being zero,
    // which just means BTC is still available via the pay-full
    // checkbox below.
    return (
      <div className="pay-invoice-btc">
        {errorBanner}
        <p>Nothing is currently owed via Bitcoin on this invoice.</p>
      </div>
    );
  }
  if (btcStatus.btc_txid) {
    // Seen in the mempool but not yet confirmed. QR, address, and
    // countdown are deliberately gone -- the renter has already paid,
    // so those elements now just mislead / invite a duplicate send.
    return (
      <div className="pay-invoice-btc">
        {errorBanner}
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
    // btc_settled_at is a historical stamp -- it's restamped on every
    // settle and never cleared -- so its presence here just means an
    // earlier round on this invoice settled, not that this one has.
    // That's still useful context: it's why there's a remainder left
    // to quote instead of a fresh invoice with nothing paid yet.
    const priorRoundSettled = btcStatus.btc_settled_at !== null;
    const canPayFullByBtc =
      Number(fullOwedUsd) > Number(btcStatus.btc_owed_usd);
    return (
      <div className="pay-invoice-btc">
        {errorBanner}
        {priorRoundSettled && (
          <p className="pay-invoice-btc__seen-note">
            A previous BTC payment on this invoice was confirmed.
          </p>
        )}
        <PaymentLegSummary
          rail="btc"
          lineItems={lineItems}
          itemIds={btcStatus.line_items}
          totalUsd={btcStatus.btc_owed_usd}
          heading="Available to pay via Bitcoin"
        />
        {canPayFullByBtc ? (
          <label className="pay-invoice__pay-full">
            <input
              type="checkbox"
              checked={payFull}
              onChange={(e) => setPayFull(e.target.checked)}
            />
            Pay full balance by BTC instead -- $
            {formatMoney(fullOwedUsd)}
          </label>
        ) : (
          <p className="pay-invoice__pay-full-note">
            This covers the full balance.
          </p>
        )}
        {quoteRequested ? (
          <>
            <p>BTC price is temporarily unavailable.</p>
            <button type="button" onClick={generateQuote}>
              Try again
            </button>
          </>
        ) : (
          <>
            <p>
              A Bitcoin amount is locked to the market rate for 15
              minutes once you generate a quote. Generate it when
              you're ready to send.
            </p>
            <button type="button" onClick={generateQuote}>
              {priorRoundSettled ? 'Pay the rest' : 'Generate quote'}
            </button>
          </>
        )}
        <BtcClaimForm invoiceId={invoiceId} />
      </div>
    );
  }

  const amountSats = btcStatus.btc_amount_sats;
  const expired = isWatchExpired(btcStatus.btc_watch_expires_at, now);
  const note = btcStatus.remainder_owed_usd
    ? 'A previous payment already covered part of this total.'
    : undefined;

  if (expired) {
    return (
      <div className="pay-invoice-btc">
        {errorBanner}
        <PaymentLegSummary
          rail="btc"
          lineItems={lineItems}
          itemIds={btcStatus.line_items}
          totalUsd={btcStatus.btc_owed_usd}
          note={note}
        />
        <p>{statusCopy(btcStatus, true)}</p>
        <button type="button" onClick={generateQuote}>
          Generate a new quote
        </button>
        <BtcClaimForm invoiceId={invoiceId} />
      </div>
    );
  }

  const msRemaining =
    new Date(btcStatus.btc_watch_expires_at).getTime() - now.getTime();

  return (
    <div className="pay-invoice-btc">
      {errorBanner}
      <PaymentLegSummary
        rail="btc"
        lineItems={lineItems}
        itemIds={btcStatus.line_items}
        totalUsd={btcStatus.btc_owed_usd}
        totalBtc={satsToBtc(amountSats)}
        note={note}
      />
      {qrDataUrl && (
        <img
          className="pay-invoice-btc__qr"
          src={qrDataUrl}
          alt="Bitcoin payment QR code"
        />
      )}
      <p>
        Send exactly {satsToBtc(amountSats)} BTC (
        ${formatMoney(btcStatus.btc_owed_usd)}) to:
      </p>
      <p className="pay-invoice-btc__address">{btcStatus.btc_address}</p>
      <p className="pay-invoice-btc__countdown">
        Quote expires in {formatCountdown(msRemaining)}
      </p>
      <p className="pay-invoice-btc__expiry">
        (expires {formatClockTime(btcStatus.btc_watch_expires_at)})
      </p>
      <p>{statusCopy(btcStatus, false)}</p>
      <button type="button" onClick={cancelQuote}>
        Cancel payment
      </button>
      <BtcClaimForm invoiceId={invoiceId} />
    </div>
  );
}
