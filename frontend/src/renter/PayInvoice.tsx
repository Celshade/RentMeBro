import { loadStripe, type Stripe } from '@stripe/stripe-js';
import {
  Elements,
  PaymentElement,
  useElements,
  useStripe,
} from '@stripe/react-stripe-js';
import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';

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
 * @param props.onDone - Called after a successful payment confirmation.
 */
function PaymentForm({ onDone }: { onDone: () => void }) {
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!stripe || !elements) return;

    setSubmitting(true);
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

  return (
    <form onSubmit={handleSubmit}>
      <PaymentElement />
      {error && <p role="alert">{error}</p>}
      <button type="submit" disabled={!stripe || submitting}>
        {submitting ? 'Paying...' : 'Pay with Cash App'}
      </button>
    </form>
  );
}


/**
 * Fetches a Stripe PaymentIntent for an invoice and renders Cash App
 * Pay checkout.
 * @param props.invoiceId - The invoice to pay.
 * @param props.onPaid - Called after the renter successfully pays.
 */
export function PayInvoice({
  invoiceId,
  onPaid,
}: {
  invoiceId: number;
  onPaid: () => void;
}) {
  const [payIntent, setPayIntent] = useState<PayIntentResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setPayIntent(null);
    setError(null);
    apiFetch<PayIntentResponse>(`/api/invoices/${invoiceId}/pay/`, {
      method: 'POST',
    })
      .then(setPayIntent)
      .catch((err: Error) => setError(err.message));
  }, [invoiceId]);

  if (error) return <p role="alert">{error}</p>;
  if (!payIntent) return <p>Preparing payment...</p>;

  return (
    <Elements
      stripe={loadStripeForAccount(payIntent.stripe_account_id)}
      options={{ clientSecret: payIntent.client_secret }}
    >
      <PaymentForm onDone={onPaid} />
    </Elements>
  );
}
