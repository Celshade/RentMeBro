import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';
import { formatUserName } from '../api/format';
import type { Lease } from '../api/types';
import { CreateLease } from './CreateLease';
import { LeaseDashboard } from './LeaseDashboard';

/**
 * Landlord's home screen: with a single active renter, goes straight
 * to that lease's dashboard. With more than one, shows a renter
 * picker first.
 * @param props.gasBillingEnabled - Whether the gas-billing section is
 *   expanded.
 * @param props.onGasBillingEnabledChange - Called to expand/collapse the
 *   gas-billing section; the caller renders the matching "back to
 *   dashboard" control in the shared header.
 */
export function LandlordDashboard({
  gasBillingEnabled,
  onGasBillingEnabledChange,
}: {
  gasBillingEnabled: boolean;
  onGasBillingEnabledChange: (enabled: boolean) => void;
}) {
  const [leases, setLeases] = useState<Lease[] | null>(null);
  const [selectedLeaseId, setSelectedLeaseId] = useState<number | null>(null);
  const [addingLease, setAddingLease] = useState(false);

  useEffect(() => {
    apiFetch<Lease[]>('/api/leases/').then((fetched) => {
      setLeases(fetched);
      if (fetched.length === 1) setSelectedLeaseId(fetched[0].id);
    });
  }, []);

  if (leases === null) return null;

  function handleLeaseCreated(lease: Lease) {
    setLeases([...(leases ?? []), lease]);
    setSelectedLeaseId(lease.id);
    setAddingLease(false);
  }

  if (leases.length === 0 || addingLease) {
    return (
      <div>
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
        <h1>Your renters</h1>
        <ul>
          {leases.map((lease) => (
            <li key={lease.id}>
              <button
                type="button"
                onClick={() => setSelectedLeaseId(lease.id)}
              >
                {formatUserName(lease.renter_detail)}
              </button>
            </li>
          ))}
        </ul>
        <button type="button" onClick={() => setAddingLease(true)}>
          Add another renter
        </button>
      </div>
    );
  }

  return (
    <div>
      <h1>Landlord dashboard</h1>
      <div>
        {leases.length > 1 && (
          <button type="button" onClick={() => setSelectedLeaseId(null)}>
            ← All renters
          </button>
        )}
        <button type="button" onClick={() => setAddingLease(true)}>
          Add another renter
        </button>
      </div>
      <LeaseDashboard
        lease={selectedLease}
        gasBillingEnabled={gasBillingEnabled}
        onGasBillingEnabledChange={onGasBillingEnabledChange}
      />
    </div>
  );
}
