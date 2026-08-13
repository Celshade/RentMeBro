import { loadStripe, type Stripe } from '@stripe/stripe-js';
import {
  Elements,
  PaymentElement,
  useElements,
  useStripe,
} from '@stripe/react-stripe-js';
import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';
import { formatMoney } from '../api/format';
import { isLineItemPaid, lineItemRails } from '../api/invoice';
import type { Invoice } from '../api/types';
import { PaymentLegSummary } from '../components/PaymentLegSummary';
import { PaymentRailGlyph } from '../components/PaymentRailGlyph';
import { PayInvoiceBtc } from './PayInvoiceBtc';

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
 */
interface PayIntentResponse {
  client_secret: string;
  stripe_account_id: string;
}


/**
 * The embedded Stripe payment form; renders once a client_secret exists.
 * @param props.invoiceId - The invoice this payment attempt is for.
 * @param props.onDone - Called after a successful payment confirmation.
 * @param props.onCancelled - Called after the renter calls off their
 *   own in-flight attempt, so the caller can fetch a fresh intent.
 */
function PaymentForm({
  invoiceId,
  onDone,
  onCancelled,
}: {
  invoiceId: number;
  onDone: () => void;
  onCancelled: () => void;
}) {
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!stripe || !elements) return;

    setSubmitting(true);
    setSubmitted(true);
    setError(null);
    try {
      const submitResult = await elements.submit();
      if (submitResult.error) {
        setError(submitResult.error.message ?? 'Payment failed.');
        return;
      }

      const result = await stripe.confirmPayment({
        elements,
        confirmParams: { return_url: window.location.href },
        redirect: 'if_required',
      });

      if (result.error) {
        setError(result.error.message ?? 'Payment failed.');
      } else {
        onDone();
      }
    } finally {
      setSubmitting(false);
    }
  }

  function handleCancel() {
    setCancelling(true);
    setError(null);
    apiFetch(`/api/invoices/${invoiceId}/pay/cancel/`, { method: 'POST' })
      .then(() => onCancelled())
      .catch((err: Error) => setError(err.message))
      .finally(() => setCancelling(false));
  }

  return (
    <form onSubmit={handleSubmit}>
      <PaymentElement options={{ wallets: { link: 'never' } }} />
      {error && <p role="alert">{error}</p>}
      <button type="submit" disabled={!stripe || submitting}>
        {submitting ? 'Paying...' : 'Pay with Cash App'}
      </button>
      {submitted && (
        <button type="button" onClick={handleCancel} disabled={cancelling}>
          {cancelling ? 'Cancelling...' : "Never mind — don't pay"}
        </button>
      )}
    </form>
  );
}


/**
 * Fetches a Stripe PaymentIntent for an invoice and renders Cash App
 * Pay checkout.
 * @param props.invoiceId - The invoice to pay.
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
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    setPayIntent(null);
    setError(null);
    apiFetch<PayIntentResponse>(`/api/invoices/${invoiceId}/pay/`, {
      method: 'POST',
      body: { pay_full: payFull },
    })
      .then(setPayIntent)
      .catch((err: Error) => setError(err.message));
  }, [invoiceId, payFull, refreshKey]);

  if (error) return <p role="alert">{error}</p>;
  if (!payIntent) return <p>Preparing payment...</p>;

  return (
    <Elements
      key={payIntent.client_secret}
      stripe={loadStripeForAccount(payIntent.stripe_account_id)}
      options={{ clientSecret: payIntent.client_secret }}
    >
      <PaymentForm
        invoiceId={invoiceId}
        onDone={onPaid}
        onCancelled={() => setRefreshKey((key) => key + 1)}
      />
    </Elements>
  );
}


/**
 * Renders a payment option for an invoice: Cash App Pay always, plus a
 * "Pay with BTC" toggle when the landlord has attached a BTC address.
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
    invoice.btc_address !== '' && Number(invoice.btc_owed_usd) > 0;
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
          {canPayFullByCard && (
            <label className="pay-invoice__pay-full">
              <input
                type="checkbox"
                checked={payFull}
                onChange={(e) => setPayFull(e.target.checked)}
              />
              Pay full balance by card instead -- $
              {formatMoney(invoice.card_full_owed_usd)}
            </label>
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
          />
          <PayInvoiceCashApp
            invoiceId={invoice.id}
            payFull={payFull}
            onPaid={onPaid}
          />
        </>
      ) : (
        <PayInvoiceBtc
          invoiceId={invoice.id}
          lineItems={invoice.line_items}
          onPaid={onPaid}
        />
      )}
    </div>
  );
}
