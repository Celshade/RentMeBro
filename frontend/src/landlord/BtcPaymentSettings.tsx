import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';
import { BTC_IRREVERSIBILITY_WARNING } from '../api/format';
import type { BtcSettings } from '../api/types';


/**
 * Landlord account settings for enabling Bitcoin as an invoice payment
 * option alongside Stripe Cash App Pay. Enabling requires confirming a
 * one-time dialogue -- including a disclaimer to use a separate BTC
 * address per renter, since a shared address makes tx matching
 * ambiguous, and a warning that attached-address transactions are
 * permanent and irreversible; the platform never custodies funds.
 * @param props.onClose - Called when the landlord dismisses this view.
 */
export function BtcPaymentSettings({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<BtcSettings | null>(null);
  const [agreed, setAgreed] = useState(false);
  const [enabling, setEnabling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<BtcSettings>('/api/payments/btc/settings/').then(setSettings);
  }, []);

  async function handleEnable() {
    setEnabling(true);
    setError(null);
    try {
      const updated = await apiFetch<BtcSettings>(
        '/api/payments/btc/settings/',
        { method: 'POST', body: { agree: true } }
      );
      setSettings(updated);
    } catch {
      setError('Could not enable BTC payments. Try again.');
    } finally {
      setEnabling(false);
    }
  }

  return (
    <div className="card">
      <div className="dashboard-toolbar">
        <h1>BTC Payments</h1>
        <div className="dashboard-toolbar__actions">
          <button type="button" onClick={onClose}>
            ← Back
          </button>
        </div>
      </div>

      {settings === null && <p>Loading...</p>}

      {settings !== null && settings.enabled && (
        <p>
          BTC payments are enabled — you can attach a Bitcoin address to an
          invoice.
        </p>
      )}

      {settings !== null && !settings.enabled && (
        <form onSubmit={(e) => e.preventDefault()}>
          <p className="btc-address-disclaimer">
            Use a <strong>separate BTC address for each renter</strong>. A
            shared address makes payments ambiguous to match and can
            misattribute one renter's payment to another's invoice.
          </p>
          <p className="btc-address-disclaimer">{BTC_IRREVERSIBILITY_WARNING}</p>
          <label>
            <input
              type="checkbox"
              checked={agreed}
              onChange={(e) => setAgreed(e.target.checked)}
            />
            Confirm BTC payments enabled
          </label>
          <button
            type="button"
            onClick={handleEnable}
            disabled={!agreed || enabling}
          >
            {enabling ? 'Enabling...' : 'Enable BTC Payments'}
          </button>
          {error && <p role="alert">{error}</p>}
        </form>
      )}
    </div>
  );
}
