import { loadStripe, type Stripe } from '@stripe/stripe-js';
import { useEffect, useRef, useState } from 'react';
import { apiFetch } from '../api/client';
import {
  formatClockTime,
  formatCountdown,
  formatMoney,
} from '../api/format';
import { isLineItemPaid, lineItemRails } from '../api/invoice';
import type { Invoice } from '../api/types';
import { PaymentLegSummary } from '../components/PaymentLegSummary';
import { PaymentRailGlyph } from '../components/PaymentRailGlyph';
import { PayInvoiceBtc } from './PayInvoiceBtc';

// How often to poll for the Cash App payment landing while the QR is
// up. Reuses POST /pay/ itself as the status check -- a still-open
// intent just gets re-synced and returns 200, while a settled one is
// reconciled server-side and answers with the "already paid" 400,
// which is this loop's success signal.
const CASH_APP_POLL_INTERVAL_MS = 4_000;

/**
 * The subset of Stripe's Cash App Pay `next_action` payload this app
 * reads. `@stripe/stripe-js`'s `PaymentIntent.NextAction` type doesn't
 * cover this action yet, so the raw payload is narrowed to this shape
 * instead of trusting the SDK's types.
 */
interface CashAppNextAction {
  cashapp_handle_redirect_or_display_qr_code?: {
    hosted_instructions_url: string;
    qr_code: {
      image_url_png: string;
      expires_at: number;
    };
  };
}

const PUBLISHABLE_KEY = import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY as string;

/**
 * `stripePromise` must be initialized with `stripeAccount` matching the
 * landlord's connected account (the PaymentIntent lives there, not on
 * the platform account), so it can't be a module-level constant — a
 * fresh instance is loaded per invoice once we know that account id.
 */
const stripePromiseCache = new Map<string, Promise<Stripe | null>>();


/**
 * Loads (or reuses) a Stripe.js instance scoped to a connected account.
 * @param stripeAccountId - The landlord's connected Stripe account id.
 */
function loadStripeForAccount(stripeAccountId: string) {
  const cached = stripePromiseCache.get(stripeAccountId);
  if (cached) return cached;
  const promise = loadStripe(PUBLISHABLE_KEY, {
    stripeAccount: stripeAccountId,
  });
  stripePromiseCache.set(stripeAccountId, promise);
  return promise;
}


/**
 * @property client_secret - Stripe PaymentIntent client secret.
 * @property stripe_account_id - The landlord's connected Stripe account
 *   the PaymentIntent was created on.
 * @property intent_status - The PaymentIntent's current Stripe status,
 *   used to decide whether a cancel control should be offered before
 *   the QR code exists.
 */
interface PayIntentResponse {
  client_secret: string;
  stripe_account_id: string;
  intent_status: string;
}

// Mirrors payments/services.py's _CANCELABLE_INTENT_STATUSES -- these
// are the statuses cancel_card_payment_attempt will actually act on.
const CANCELABLE_INTENT_STATUSES = new Set([
  'requires_payment_method',
  'requires_confirmation',
  'requires_action',
]);


/**
 * Fetches a Stripe PaymentIntent for an invoice, confirms it as a
 * Cash App Pay charge, and renders the resulting QR code inline
 * instead of handing off to Stripe's hosted overlay -- which used to
 * make the "Never mind — don't pay" button unreachable once the QR
 * was up, since the overlay ate all clicks.
 * @param props.invoiceId - The invoice to pay.
 * @param props.payFull - Bill the full card-payable balance instead
 *   of just the unscoped portion.
 * @param props.onPaid - Called after the renter successfully pays.
 */
function PayInvoiceCashApp({
  invoiceId,
  payFull,
  onPaid,
}: {
  invoiceId: number;
  payFull: boolean;
  onPaid: () => void;
}) {
  const [payIntent, setPayIntent] = useState<PayIntentResponse | null>(null);
  const [stripe, setStripe] = useState<Stripe | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [qrCode, setQrCode] = useState<{
    imageUrl: string;
    expiresAt: number;
  } | null>(null);
  const [hostedInstructionsUrl, setHostedInstructionsUrl] = useState<
    string | null
  >(null);
  const [now, setNow] = useState(() => new Date());
  const [refreshKey, setRefreshKey] = useState(0);
  const onPaidRef = useRef(onPaid);
  onPaidRef.current = onPaid;

  useEffect(() => {
    setPayIntent(null);
    setStripe(null);
    setQrCode(null);
    setHostedInstructionsUrl(null);
    setError(null);
    setFetchError(null);
    apiFetch<PayIntentResponse>(`/api/invoices/${invoiceId}/pay/`, {
      method: 'POST',
      body: { pay_full: payFull },
    })
      .then((intent) => {
        setPayIntent(intent);
        return loadStripeForAccount(intent.stripe_account_id);
      })
      .then(setStripe)
      .catch((err: Error) => setFetchError(err.message));
  }, [invoiceId, payFull, refreshKey]);

  useEffect(() => {
    if (!qrCode) return;
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, [qrCode]);

  useEffect(() => {
    if (!qrCode) return;
    const timer = setInterval(() => {
      apiFetch<PayIntentResponse>(`/api/invoices/${invoiceId}/pay/`, {
        method: 'POST',
        body: { pay_full: payFull },
      }).catch((err: Error) => {
        if (err.message === 'Invoice is already paid.') {
          onPaidRef.current();
        }
      });
    }, CASH_APP_POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [qrCode, invoiceId, payFull]);

  async function handlePay() {
    if (!stripe || !payIntent) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await stripe.confirmCashappPayment(
        payIntent.client_secret,
        { payment_method: {}, return_url: window.location.href },
        { handleActions: false }
      );
      if (result.error) {
        setError(result.error.message ?? 'Payment failed.');
        return;
      }
      if (result.paymentIntent.status === 'succeeded') {
        onPaidRef.current();
        return;
      }
      const nextAction = result.paymentIntent
        .next_action as unknown as CashAppNextAction | null;
      const cashapp = nextAction?.cashapp_handle_redirect_or_display_qr_code;
      if (!cashapp) {
        setError('Could not start the Cash App payment.');
        return;
      }
      setQrCode({
        imageUrl: cashapp.qr_code.image_url_png,
        expiresAt: cashapp.qr_code.expires_at,
      });
      setHostedInstructionsUrl(cashapp.hosted_instructions_url);
    } finally {
      setSubmitting(false);
    }
  }

  function handleCancel() {
    setCancelling(true);
    setError(null);
    apiFetch(`/api/invoices/${invoiceId}/pay/cancel/`, { method: 'POST' })
      .then(() => setRefreshKey((key) => key + 1))
      .catch((err: Error) => setError(err.message))
      .finally(() => setCancelling(false));
  }

  if (fetchError) {
    return (
      <div>
        <p role="alert">{fetchError}</p>
        <button
          type="button"
          onClick={() => setRefreshKey((key) => key + 1)}
        >
          Try again
        </button>
      </div>
    );
  }
  if (!payIntent || !stripe) return <p>Preparing payment...</p>;

  if (qrCode) {
    const msRemaining = qrCode.expiresAt * 1000 - now.getTime();
    return (
      <div className="pay-invoice-cashapp">
        {error && <p role="alert">{error}</p>}
        <img
          className="pay-invoice-cashapp__qr"
          src={qrCode.imageUrl}
          alt="Cash App payment QR code"
        />
        <p>
          Scan with the Cash App on your phone, or{' '}
          <a
            href={hostedInstructionsUrl ?? undefined}
            target="_blank"
            rel="noreferrer"
          >
            open the payment page
          </a>
          .
        </p>
        {msRemaining > 0 && (
          <p className="pay-invoice-cashapp__countdown">
            Expires in {formatCountdown(msRemaining)} (
            {formatClockTime(new Date(qrCode.expiresAt * 1000).toISOString())}
            )
          </p>
        )}
        <p>Waiting for payment...</p>
        <button type="button" onClick={handleCancel} disabled={cancelling}>
          {cancelling ? 'Cancelling...' : 'Cancel payment'}
        </button>
      </div>
    );
  }

  const canCancel = CANCELABLE_INTENT_STATUSES.has(payIntent.intent_status);

  return (
    <div>
      {error && <p role="alert">{error}</p>}
      <button type="button" onClick={handlePay} disabled={submitting}>
        {submitting ? 'Starting...' : 'Pay with Cash App'}
      </button>
      {canCancel && (
        <button type="button" onClick={handleCancel} disabled={cancelling}>
          {cancelling ? 'Cancelling...' : 'Cancel payment'}
        </button>
      )}
    </div>
  );
}


/**
 * Renders a payment option for an invoice: Cash App Pay always, plus a
 * "Pay with BTC" toggle once the landlord has actually assigned BTC to
 * at least one line item -- an attached address alone isn't enough,
 * since attaching one with nothing scoped is a real, reachable state.
 *
 * When the landlord has scoped BTC to one line item the two aren't
 * alternatives -- both legs have to be paid to settle the invoice -- so
 * the split is spelled out and the toggle opens on whichever leg is
 * still outstanding.
 * @param props.invoice - The invoice to pay.
 * @param props.onPaid - Called after the renter successfully pays.
 */
export function PayInvoice({
  invoice,
  onPaid,
}: {
  invoice: Invoice;
  onPaid: () => void;
}) {
  const hasBtcOption =
    invoice.btc_scope_line_items.length > 0 &&
    Number(invoice.btc_full_owed_usd) > 0;
  const [mode, setMode] = useState<'cashapp' | 'btc'>(
    Number(invoice.btc_owed_usd) > 0 &&
      Number(invoice.stripe_portion_usd) === 0
      ? 'btc'
      : 'cashapp'
  );
  const [payFull, setPayFull] = useState(false);

  // The card leg only genuinely has nothing to bill when every unpaid
  // item is BTC-locked -- a merely BTC-*assigned* invoice still owes
  // the full total by card, so the tab stays up.
  const cardOwesNothing = Number(invoice.card_full_owed_usd) === 0;
  const canPayFullByCard =
    Number(invoice.card_full_owed_usd) > Number(invoice.stripe_portion_usd);

  return (
    <div>
      <ul className="list">
        {invoice.line_items.map((item) => {
          const paid = isLineItemPaid(invoice, item.id);
          const itemRails = lineItemRails(invoice, item);
          const lockLabel =
            item.payment_lock === 'btc'
              ? 'BTC only'
              : item.payment_lock === 'card'
                ? 'Card only'
                : null;
          return (
            <li key={item.id} className="list-row">
              <span>
                <span className="list-row__rails">
                  {itemRails.btc && (
                    <PaymentRailGlyph rail="btc" label="Payable in Bitcoin" />
                  )}
                  {itemRails.card && (
                    <PaymentRailGlyph
                      rail="card"
                      label="Payable by card (Cash App)"
                    />
                  )}
                </span>
                {item.description}
              </span>
              <span className="renter-dashboard__invoice-actions">
                ${item.amount}
                {paid && (
                  <span className="status-badge status-badge--paid">
                    Paid
                  </span>
                )}
                {!paid && lockLabel && (
                  <span className="status-badge status-badge--pending">
                    {lockLabel}
                  </span>
                )}
              </span>
            </li>
          );
        })}
      </ul>
      {invoice.is_split_payment && (
        <p className="pay-invoice__split-notice">
          Both a BTC and a card payment are needed to settle this invoice.
        </p>
      )}
      {cardOwesNothing && (
        <p className="pay-invoice__split-notice">
          The landlord has set these charges to be paid in BTC.
        </p>
      )}
      {hasBtcOption && (
        <div className="pay-invoice__mode-toggle">
          {!cardOwesNothing && (
            <button
              type="button"
              onClick={() => setMode('cashapp')}
              disabled={mode === 'cashapp'}
            >
              Pay with Cash App
            </button>
          )}
          <button
            type="button"
            onClick={() => setMode('btc')}
            disabled={mode === 'btc'}
          >
            Pay with BTC
          </button>
        </div>
      )}
      {mode === 'cashapp' && !cardOwesNothing ? (
        <>
          {canPayFullByCard ? (
            <label className="pay-invoice__pay-full">
              <input
                type="checkbox"
                checked={payFull}
                onChange={(e) => setPayFull(e.target.checked)}
              />
              Pay full balance by card instead -- $
              {formatMoney(invoice.card_full_owed_usd)}
            </label>
          ) : (
            <p className="pay-invoice__pay-full-note">
              This covers the full balance.
            </p>
          )}
          <PaymentLegSummary
            rail="card"
            lineItems={invoice.line_items}
            itemIds={
              payFull
                ? invoice.card_full_line_items
                : invoice.stripe_scope_line_items
            }
            totalUsd={
              payFull
                ? invoice.card_full_owed_usd
                : invoice.stripe_portion_usd
            }
            note={
              invoice.remainder_owed_usd !== null
                ? 'A previous payment already covered part of this total.'
                : undefined
            }
          />
          <PayInvoiceCashApp
            invoiceId={invoice.id}
            payFull={payFull}
            onPaid={onPaid}
          />
        </>
      ) : hasBtcOption ? (
        <PayInvoiceBtc
          invoiceId={invoice.id}
          lineItems={invoice.line_items}
          fullOwedUsd={invoice.btc_full_owed_usd}
          onPaid={onPaid}
        />
      ) : (
        <p role="alert">
          This invoice has no payment method available right now. Contact
          your landlord.
        </p>
      )}
    </div>
  );
}
