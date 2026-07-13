import { useState, type FormEvent } from 'react';
import { apiFetch } from '../api/client';
import type { DrivenDayLog } from '../api/types';

/**
 * Landlord form to log a (partial) day a renter was driven.
 * @param props.renterId - The renter who was driven.
 * @param props.onLogged - Called with the created log entry on success.
 */
export function LogDrivenDay({
  renterId,
  onLogged,
}: {
  renterId: number;
  onLogged: (log: DrivenDayLog) => void;
}) {
  const [date, setDate] = useState('');
  const [dayFraction, setDayFraction] = useState('1');
  const [note, setNote] = useState('');
  const [status, setStatus] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setStatus(null);
    try {
      const log = await apiFetch<DrivenDayLog>('/api/driven-days/', {
        method: 'POST',
        body: { renter: renterId, date, day_fraction: dayFraction, note },
      });
      onLogged(log);
      setDate('');
      setNote('');
      setStatus('Logged.');
    } catch (err) {
      setStatus((err as Error).message);
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <label htmlFor="driven_date">Date</label>
      <input
        id="driven_date"
        type="date"
        required
        value={date}
        onChange={(e) => setDate(e.target.value)}
      />
      <label htmlFor="day_fraction">Fraction of day</label>
      <input
        id="day_fraction"
        type="number"
        step="0.25"
        min="0"
        max="1"
        required
        value={dayFraction}
        onChange={(e) => setDayFraction(e.target.value)}
      />
      <label htmlFor="driven_note">Note (optional)</label>
      <input
        id="driven_note"
        type="text"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <button type="submit">Log day</button>
      {status && <p>{status}</p>}
    </form>
  );
}
