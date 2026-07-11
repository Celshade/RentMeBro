import { useState, type FormEvent } from 'react';
import { apiFetch } from '../api/client';
import type { DrivenDayLog } from '../api/types';

/**
 * Form for a renter to log a day (or fraction of a day) driven to the
 * worksite.
 * @param props.leaseId - The lease this driven day belongs to.
 * @param props.onLogged - Called with the created log entry on success.
 */
export function DrivenDayForm({
  leaseId,
  onLogged,
}: {
  leaseId: number;
  onLogged: (log: DrivenDayLog) => void;
}) {
  const [date, setDate] = useState('');
  const [dayFraction, setDayFraction] = useState('1.00');
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const log = await apiFetch<DrivenDayLog>('/api/driven-days/', {
        method: 'POST',
        body: { lease: leaseId, date, day_fraction: dayFraction, note },
      });
      onLogged(log);
      setDate('');
      setNote('');
      setDayFraction('1.00');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <h3>Log a driven day</h3>
      <label htmlFor="date">Date</label>
      <input
        id="date"
        type="date"
        required
        value={date}
        onChange={(e) => setDate(e.target.value)}
      />
      <label htmlFor="day_fraction">
        Day fraction (1 = full day, 0.5 = half)
      </label>
      <input
        id="day_fraction"
        type="number"
        step="0.25"
        min="0.25"
        max="1"
        required
        value={dayFraction}
        onChange={(e) => setDayFraction(e.target.value)}
      />
      <label htmlFor="note">Note (optional)</label>
      <input
        id="note"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <button type="submit" disabled={submitting}>
        Log day
      </button>
      {error && <p role="alert">{error}</p>}
    </form>
  );
}
