import { useState, type FormEvent } from 'react';
import { apiFetch } from '../api/client';

/**
 * Landlord form to schedule a rent change for a lease, at least 30
 * days out. Immediately emails the renter regardless of the
 * effective date, so they have advance notice.
 * @param props.leaseId - The lease to change rent for.
 * @param props.onScheduled - Called once the change is scheduled.
 * @param props.onCancel - Called if the landlord backs out without
 *   scheduling a change.
 */
export function EditRent({
  leaseId,
  onScheduled,
  onCancel,
}: {
  leaseId: number;
  onScheduled: () => void;
  onCancel: () => void;
}) {
  const [newMonthlyRent, setNewMonthlyRent] = useState('');
  const [effectiveDate, setEffectiveDate] = useState('');
  const [status, setStatus] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setStatus(null);
    try {
      await apiFetch(`/api/leases/${leaseId}/rent-revisions/`, {
        method: 'POST',
        body: {
          new_monthly_rent: newMonthlyRent,
          effective_date: effectiveDate,
        },
      });
      setStatus('Rent change scheduled. The renter has been notified.');
      onScheduled();
    } catch (err) {
      setStatus((err as Error).message);
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <label htmlFor="new_monthly_rent">New monthly rent</label>
      <input
        id="new_monthly_rent"
        type="number"
        step="0.01"
        required
        value={newMonthlyRent}
        onChange={(e) => setNewMonthlyRent(e.target.value)}
      />
      <label htmlFor="effective_date">Effective date (30+ days out)</label>
      <input
        id="effective_date"
        type="date"
        required
        value={effectiveDate}
        onChange={(e) => setEffectiveDate(e.target.value)}
      />
      <button type="submit">Schedule rent change</button>
      <button type="button" onClick={onCancel}>
        Cancel
      </button>
      {status && <p>{status}</p>}
    </form>
  );
}
