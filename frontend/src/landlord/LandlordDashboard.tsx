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
        <h1>Landlord dashboard</h1>
        <div className="dashboard-toolbar__actions">
          {leases.length > 1 && (
            <button type="button" onClick={() => setSelectedLeaseId(null)}>
              ← All renters
            </button>
          )}
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
