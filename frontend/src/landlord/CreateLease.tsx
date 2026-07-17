import { useState, type FormEvent } from 'react';
import { apiFetch } from '../api/client';
import type { Lease, LeaseType, User } from '../api/types';

/**
 * Landlord form to create a lease: looks up the renter by exact email,
 * then creates either a custom (uploaded document) or default
 * (price/term) lease for them.
 * @param props.onCreated - Called with the created lease on success.
 */
export function CreateLease({
  onCreated,
}: {
  onCreated: (lease: Lease) => void;
}) {
  const [renterEmail, setRenterEmail] = useState('');
  const [renter, setRenter] = useState<User | null>(null);
  const [renterError, setRenterError] = useState<string | null>(null);

  const [leaseType, setLeaseType] = useState<LeaseType>('default');
  const [monthlyRent, setMonthlyRent] = useState('');
  const [startDate, setStartDate] = useState('');
  const [termMonths, setTermMonths] = useState('');
  const [document, setDocument] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleFindRenter() {
    setRenterError(null);
    setRenter(null);
    try {
      const found = await apiFetch<User>(
        `/api/renters/lookup/?email=${encodeURIComponent(renterEmail)}`
      );
      setRenter(found);
    } catch (err) {
      setRenterError((err as Error).message);
    }
  }

  function buildBody(renterId: number): FormData | Record<string, unknown> {
    if (leaseType === 'custom') {
      const formData = new FormData();
      formData.append('renter', String(renterId));
      formData.append('lease_type', leaseType);
      formData.append('monthly_rent', monthlyRent);
      formData.append('start_date', startDate);
      if (document) {
        formData.append('document', document);
      }
      return formData;
    }
    return {
      renter: renterId,
      lease_type: leaseType,
      monthly_rent: monthlyRent,
      start_date: startDate,
      term_months: Number(termMonths),
    };
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!renter) return;
    setError(null);
    try {
      const lease = await apiFetch<Lease>('/api/leases/', {
        method: 'POST',
        body: buildBody(renter.id),
      });
      onCreated(lease);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div>
      <h3>Create a lease</h3>
      <label htmlFor="renter_email">Renter email</label>
      <input
        id="renter_email"
        type="email"
        required
        value={renterEmail}
        onChange={(e) => setRenterEmail(e.target.value)}
      />
      <button type="button" onClick={handleFindRenter}>
        Find renter
      </button>
      {renterError && <p role="alert">{renterError}</p>}
      {renter && <p>Renter found: {renter.email}</p>}

      {renter && (
        <form onSubmit={handleSubmit}>
          <fieldset>
            <legend>Lease type</legend>
            <label>
              <input
                type="radio"
                name="lease_type"
                value="default"
                checked={leaseType === 'default'}
                onChange={() => setLeaseType('default')}
              />
              Default lease
            </label>
            <label>
              <input
                type="radio"
                name="lease_type"
                value="custom"
                checked={leaseType === 'custom'}
                onChange={() => setLeaseType('custom')}
              />
              Custom lease (upload document)
            </label>
          </fieldset>

          <label htmlFor="monthly_rent">Monthly rent</label>
          <input
            id="monthly_rent"
            type="number"
            step="0.01"
            required
            value={monthlyRent}
            onChange={(e) => setMonthlyRent(e.target.value)}
          />
          <label htmlFor="start_date">Start date</label>
          <input
            id="start_date"
            type="date"
            required
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
          />

          {leaseType === 'default' && (
            <>
              <label htmlFor="term_months">Term (months)</label>
              <input
                id="term_months"
                type="number"
                min="1"
                required
                value={termMonths}
                onChange={(e) => setTermMonths(e.target.value)}
              />
              <p>
                The default lease's terms are subject to change; any
                revisions will be provided to the renter at least 30 days
                before taking effect.
              </p>
            </>
          )}

          {leaseType === 'custom' && (
            <>
              <label htmlFor="document">Lease document</label>
              <input
                id="document"
                type="file"
                required
                onChange={(e) => setDocument(e.target.files?.[0] ?? null)}
              />
            </>
          )}

          <button type="submit">Create lease</button>
          {error && <p role="alert">{error}</p>}
        </form>
      )}
    </div>
  );
}
