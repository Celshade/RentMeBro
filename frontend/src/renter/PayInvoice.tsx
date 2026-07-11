import { loadStripe } from '@stripe/stripe-js';
import {
  Elements,
  PaymentElement,
  useElements,
  useStripe,
} from '@stripe/react-stripe-js';
import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';

const stripePromise = loadStripe(
  import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY as string
);


/** @property client_secret - Stripe PaymentIntent client secret. */
interface PayIntentResponse {
  client_secret: string;
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
    const result = await stripe.confirmPayment({
      elements,
      confirmParams: { return_url: window.location.href },
      redirect: 'if_required',
    });

    if (result.error) {
      setError(result.error.message ?? 'Payment failed.');
      setSubmitting(false);
    } else {
      onDone();
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
  const [clientSecret, setClientSecret] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<PayIntentResponse>(`/api/invoices/${invoiceId}/pay/`, {
      method: 'POST',
    }).then((data) => setClientSecret(data.client_secret));
  }, [invoiceId]);

  if (!clientSecret) return <p>Preparing payment...</p>;

  return (
    <Elements stripe={stripePromise} options={{ clientSecret }}>
      <PaymentForm onDone={onPaid} />
    </Elements>
  );
}
