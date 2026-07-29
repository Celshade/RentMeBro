import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';
import type { ConnectStatus } from '../api/types';


/**
 * @property onboarding_url - Stripe-hosted URL to complete onboarding.
 */
interface OnboardingResponse {
  onboarding_url: string;
}


/**
 * Landlord account settings for connecting Stripe so renters can pay
 * invoices with Cash App Pay.
 * @param props.onClose - Called when the landlord dismisses this view.
 */
export function StripeConnectSettings({ onClose }: { onClose: () => void }) {
  const [status, setStatus] = useState<ConnectStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<ConnectStatus>('/api/payments/connect/status/').then(setStatus);
  }, []);

  async function handleConnect() {
    setStarting(true);
    setError(null);
    try {
      const { onboarding_url } = await apiFetch<OnboardingResponse>(
        '/api/payments/connect/onboard/',
        { method: 'POST' }
      );
      window.location.href = onboarding_url;
    } catch {
      setError('Could not start Stripe onboarding. Try again.');
      setStarting(false);
    }
  }

  return (
    <div className="card">
      <div className="dashboard-toolbar">
        <h1>Stripe Payments</h1>
        <div className="dashboard-toolbar__actions">
          <button type="button" onClick={onClose}>
            ← Back
          </button>
        </div>
      </div>

      {status === null && <p>Loading...</p>}

      {status !== null && status.charges_enabled && (
        <p>Stripe is connected — renters can pay invoices with Cash App.</p>
      )}

      {status !== null && !status.charges_enabled && (
        <>
          <p>
            {status.connected
              ? 'Finish connecting Stripe to start accepting Cash App ' +
                'payments.'
              : 'Connect Stripe to start accepting Cash App payments ' +
                'from renters.'}
          </p>
          <button type="button" onClick={handleConnect} disabled={starting}>
            {starting ? 'Redirecting...' : 'Connect with Stripe'}
          </button>
          {error && <p role="alert">{error}</p>}
        </>
      )}
    </div>
  );
}
