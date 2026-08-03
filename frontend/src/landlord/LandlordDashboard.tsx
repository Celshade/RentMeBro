import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';
import { formatUserName } from '../api/format';
import type { BtcSettings, ConnectStatus, Lease } from '../api/types';
import { BtcPaymentSettings } from './BtcPaymentSettings';
import { CreateLease } from './CreateLease';
import { LeaseDashboard } from './LeaseDashboard';
import { StripeConnectSettings } from './StripeConnectSettings';


/**
 * Short label summarizing the landlord's Stripe Connect status, for a
 * badge next to the "Stripe Payments" button.
 * @param status - The fetched connect status, or null while loading.
 */
function paymentsStatusLabel(status: ConnectStatus | null): string | null {
  if (status === null) return null;
  if (status.charges_enabled) return 'Connected';
  if (status.connected) return 'Setup pending';
  return 'Set up payments';
}


/**
 * Short label summarizing the landlord's BTC payments status, for a
 * badge next to the "BTC Payments" button.
 * @param settings - The fetched BTC settings, or null while loading.
 */
function btcStatusLabel(settings: BtcSettings | null): string | null {
  if (settings === null) return null;
  return settings.enabled ? 'Enabled' : 'Set up payments';
}


/**
 * Landlord's home screen: with a single active renter, goes straight
 * to that lease's dashboard. With more than one, shows a renter
 * picker first.
 * @param props.onBackHandlerChange - Forwarded to the selected lease's
 *   dashboard, so its active sub-view can register the shared header's
 *   "back to dashboard" control.
 */
export function LandlordDashboard({
  onBackHandlerChange,
}: {
  onBackHandlerChange: (handler: (() => void) | null) => void;
}) {
  const [leases, setLeases] = useState<Lease[] | null>(null);
  const [selectedLeaseId, setSelectedLeaseId] = useState<number | null>(null);
  const [addingLease, setAddingLease] = useState(false);
  const [showPaymentSettings, setShowPaymentSettings] = useState(false);
  const [showBtcSettings, setShowBtcSettings] = useState(false);
  const [connectStatus, setConnectStatus] = useState<ConnectStatus | null>(
    null
  );
  const [btcSettings, setBtcSettings] = useState<BtcSettings | null>(null);
  const [refreshingConnect, setRefreshingConnect] = useState(false);

  useEffect(() => {
    apiFetch<Lease[]>('/api/leases/').then((fetched) => {
      setLeases(fetched);
      if (fetched.length === 1) setSelectedLeaseId(fetched[0].id);
    });
  }, []);

  useEffect(() => {
    apiFetch<ConnectStatus>('/api/payments/connect/status/').then(
      setConnectStatus
    );
  }, [showPaymentSettings]);

  useEffect(() => {
    apiFetch<BtcSettings>('/api/payments/btc/settings/').then(setBtcSettings);
  }, [showBtcSettings]);

  async function handleRefreshConnect() {
    setRefreshingConnect(true);
    try {
      const fresh = await apiFetch<ConnectStatus>(
        '/api/payments/connect/status/?refresh=true'
      );
      setConnectStatus(fresh);
    } finally {
      setRefreshingConnect(false);
    }
  }

  if (leases === null) return null;

  if (showPaymentSettings) {
    return (
      <StripeConnectSettings
        onClose={() => setShowPaymentSettings(false)}
      />
    );
  }

  if (showBtcSettings) {
    return <BtcPaymentSettings onClose={() => setShowBtcSettings(false)} />;
  }

  const paymentsLabel = paymentsStatusLabel(connectStatus);
  const btcLabel = btcStatusLabel(btcSettings);

  function handleLeaseCreated(lease: Lease) {
    setLeases([...(leases ?? []), lease]);
    setSelectedLeaseId(lease.id);
    setAddingLease(false);
  }

  if (leases.length === 0 || addingLease) {
    return (
      <div className="card">
        <CreateLease onCreated={handleLeaseCreated} />
        {leases.length > 0 && (
          <button type="button" onClick={() => setAddingLease(false)}>
            Cancel
          </button>
        )}
      </div>
    );
  }

  const selectedLease = leases.find((l) => l.id === selectedLeaseId) ?? null;

  if (!selectedLease) {
    return (
      <div>
        <div className="dashboard-toolbar">
          <h1>Your renters</h1>
          <div className="dashboard-toolbar__actions">
            <button
              type="button"
              className="button--stripe"
              onClick={() => setShowPaymentSettings(true)}
            >
              Stripe Payments
              {paymentsLabel && (
                <span
                  className={
                    connectStatus?.charges_enabled
                      ? 'badge badge--connected'
                      : 'badge'
                  }
                >
                  {paymentsLabel}
                </span>
              )}
            </button>
            {connectStatus?.connected && !connectStatus.charges_enabled && (
              <button
                type="button"
                onClick={handleRefreshConnect}
                disabled={refreshingConnect}
              >
                {refreshingConnect ? 'Refreshing...' : 'Refresh status'}
              </button>
            )}
            <button
              type="button"
              className="button--btc"
              onClick={() => setShowBtcSettings(true)}
            >
              BTC Payments
              {btcLabel && (
                <span
                  className={
                    btcSettings?.enabled
                      ? 'badge badge--connected'
                      : 'badge'
                  }
                >
                  {btcLabel}
                </span>
              )}
            </button>
            <button type="button" onClick={() => setAddingLease(true)}>
              Add another renter
            </button>
          </div>
        </div>
        <ul className="list">
          {leases.map((lease) => (
            <li key={lease.id} className="list-row">
              <button
                type="button"
                onClick={() => setSelectedLeaseId(lease.id)}
              >
                {formatUserName(lease.renter_detail)}
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div>
      <div className="dashboard-toolbar">
        <h1>Your dashboard</h1>
        <div className="dashboard-toolbar__actions">
          {leases.length > 1 && (
            <button type="button" onClick={() => setSelectedLeaseId(null)}>
              ← All renters
            </button>
          )}
          <button
            type="button"
            className="button--stripe"
            onClick={() => setShowPaymentSettings(true)}
          >
            Stripe Payments
            {paymentsLabel && (
              <span
                className={
                  connectStatus?.charges_enabled
                    ? 'badge badge--connected'
                    : 'badge'
                }
              >
                {paymentsLabel}
              </span>
            )}
          </button>
          {connectStatus?.connected && !connectStatus.charges_enabled && (
            <button
              type="button"
              onClick={handleRefreshConnect}
              disabled={refreshingConnect}
            >
              {refreshingConnect ? 'Refreshing...' : 'Refresh status'}
            </button>
          )}
          <button
            type="button"
            className="button--btc"
            onClick={() => setShowBtcSettings(true)}
          >
            BTC Payments
            {btcLabel && (
              <span
                className={
                  btcSettings?.enabled ? 'badge badge--connected' : 'badge'
                }
              >
                {btcLabel}
              </span>
            )}
          </button>
          <button type="button" onClick={() => setAddingLease(true)}>
            Add another renter
          </button>
        </div>
      </div>
      <LeaseDashboard
        lease={selectedLease}
        onBackHandlerChange={onBackHandlerChange}
      />
    </div>
  );
}
