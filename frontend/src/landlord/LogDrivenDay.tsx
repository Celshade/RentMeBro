import { useState, type FormEvent } from 'react';
import { apiFetch } from '../api/client';
import type { DrivenDayLog } from '../api/types';

/**
 * Snaps a stored day_fraction to the nearest of the two choices the
 * form offers (full/half), for logs created before this restriction.
 */
function normalizeFraction(dayFraction: string): string {
  return Number(dayFraction) >= 0.75 ? '1' : '0.5';
}


/**
 * Landlord form to log a (partial) day a renter was driven, or edit
 * an existing entry.
 * @param props.renterId - The renter who was driven.
 * @param props.initialDate - Date to prefill (e.g. from a calendar
 *   day click), ignored if `editingLog` is set.
 * @param props.editingLog - The existing log to edit, or null/undefined
 *   to create a new one.
 * @param props.onSaved - Called with the created/updated log entry on
 *   success.
 * @param props.onCancel - Called if the landlord backs out without
 *   saving.
 */
export function LogDrivenDay({
  renterId,
  initialDate,
  editingLog,
  onSaved,
  onCancel,
}: {
  renterId: number;
  initialDate?: string;
  editingLog?: DrivenDayLog | null;
  onSaved: (log: DrivenDayLog) => void;
  onCancel: () => void;
}) {
  const [date, setDate] = useState(editingLog?.date ?? initialDate ?? '');
  const [dayFraction, setDayFraction] = useState(
    editingLog ? normalizeFraction(editingLog.day_fraction) : '1'
  );
  const [note, setNote] = useState(editingLog?.note ?? '');
  const [status, setStatus] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setStatus(null);
    try {
      const path = editingLog
        ? `/api/driven-days/${editingLog.id}/`
        : '/api/driven-days/';
      const log = await apiFetch<DrivenDayLog>(path, {
        method: editingLog ? 'PATCH' : 'POST',
        body: { renter: renterId, date, day_fraction: dayFraction, note },
      });
      onSaved(log);
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
      <label htmlFor="day_fraction">Trip</label>
      <select
        id="day_fraction"
        required
        value={dayFraction}
        onChange={(e) => setDayFraction(e.target.value)}
      >
        <option value="1">Full day (drop-off + pick-up)</option>
        <option value="0.5">Half day (drop-off or pick-up only)</option>
      </select>
      <label htmlFor="driven_note">Note (optional)</label>
      <input
        id="driven_note"
        type="text"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <button type="submit">{editingLog ? 'Update day' : 'Log day'}</button>
      <button type="button" onClick={onCancel}>
        Cancel
      </button>
      {status && <p>{status}</p>}
    </form>
  );
}
