import { useState, type FormEvent } from 'react';
import { apiFetch } from '../api/client';
import type {
  DrivenDayHalfLeg,
  DrivenDayLog,
  DrivenDayLogKind,
} from '../api/types';

/** The six choices the "Trip" dropdown offers, each mapping to a
 * kind + day_fraction + half_leg triple. `half` is the neutral
 * "leg unknown" option, kept for editing older rows without forcing
 * a choice.
 */
type TripOption =
  | 'full'
  | 'half'
  | 'half_drop_off'
  | 'half_pick_up'
  | 'day_off'
  | 'other_ride';

/** Picks the trip option matching an existing log, for editing. */
function tripOptionForLog(log: DrivenDayLog): TripOption {
  if (log.kind === 'day_off') return 'day_off';
  if (log.kind === 'other_ride') return 'other_ride';
  if (Number(log.day_fraction) >= 0.75) return 'full';
  if (log.half_leg === 'drop_off') return 'half_drop_off';
  if (log.half_leg === 'pick_up') return 'half_pick_up';
  return 'half';
}

/** Maps a trip option to the kind/day_fraction/half_leg triple it
 * saves as. */
function tripOptionToFields(option: TripOption): {
  kind: DrivenDayLogKind;
  day_fraction: string;
  half_leg: DrivenDayHalfLeg;
} {
  switch (option) {
    case 'full':
      return { kind: 'driven', day_fraction: '1', half_leg: '' };
    case 'half':
      return { kind: 'driven', day_fraction: '0.5', half_leg: '' };
    case 'half_drop_off':
      return { kind: 'driven', day_fraction: '0.5', half_leg: 'drop_off' };
    case 'half_pick_up':
      return { kind: 'driven', day_fraction: '0.5', half_leg: 'pick_up' };
    case 'day_off':
      return { kind: 'day_off', day_fraction: '0', half_leg: '' };
    case 'other_ride':
      return { kind: 'other_ride', day_fraction: '0', half_leg: '' };
  }
}


/**
 * Landlord form to log a (partial) day, or several days at once, that
 * a renter was driven, applying the same trip type/note to each
 * date. Also used to edit a single existing entry.
 * @param props.renterId - The renter who was driven.
 * @param props.dates - The date(s) (YYYY-MM-DD) to log. A single date
 *   may be edited before saving; with more than one, the dates are
 *   fixed (chosen via the calendar) and only shown as a summary.
 * @param props.existingLogs - The existing log for each entry in
 *   `dates` (same order), or null where none exists yet.
 * @param props.onSaved - Called with the created/updated log entries
 *   on success.
 * @param props.onDeleted - Called with the deleted log's id after a
 *   single existing entry is removed.
 * @param props.onCancel - Called if the landlord backs out without
 *   saving.
 */
export function LogDrivenDay({
  renterId,
  dates,
  existingLogs,
  onSaved,
  onDeleted,
  onCancel,
}: {
  renterId: number;
  dates: string[];
  existingLogs: (DrivenDayLog | null)[];
  onSaved: (logs: DrivenDayLog[]) => void;
  onDeleted: (logId: number) => void;
  onCancel: () => void;
}) {
  const isSingle = dates.length === 1;
  const singleExistingLog = isSingle ? existingLogs[0] : null;
  const [date, setDate] = useState(dates[0] ?? '');
  const [tripOption, setTripOption] = useState<TripOption>(
    singleExistingLog ? tripOptionForLog(singleExistingLog) : 'full'
  );
  const [note, setNote] = useState(singleExistingLog?.note ?? '');
  const [status, setStatus] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setStatus(null);
    try {
      const { kind, day_fraction, half_leg } = tripOptionToFields(tripOption);
      const targets = isSingle
        ? [{ date, log: singleExistingLog }]
        : dates.map((d, i) => ({ date: d, log: existingLogs[i] }));
      const logs = await Promise.all(
        targets.map(({ date, log }) => {
          const path = log
            ? `/api/driven-days/${log.id}/`
            : '/api/driven-days/';
          return apiFetch<DrivenDayLog>(path, {
            method: log ? 'PATCH' : 'POST',
            body: {
              renter: renterId,
              date,
              kind,
              day_fraction,
              half_leg,
              note,
            },
          });
        })
      );
      onSaved(logs);
    } catch (err) {
      setStatus((err as Error).message);
    }
  }

  async function handleDelete() {
    if (!singleExistingLog) return;
    const confirmed = window.confirm(
      `Delete the logged day for ${singleExistingLog.date}?`
    );
    if (!confirmed) return;
    setStatus(null);
    try {
      await apiFetch(`/api/driven-days/${singleExistingLog.id}/`, {
        method: 'DELETE',
      });
      onDeleted(singleExistingLog.id);
    } catch (err) {
      setStatus((err as Error).message);
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      {isSingle ? (
        <>
          <label htmlFor="driven_date">Date</label>
          <input
            id="driven_date"
            type="date"
            required
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </>
      ) : (
        <p>Logging {dates.length} days: {dates.join(', ')}</p>
      )}
      <label htmlFor="trip_option">Trip</label>
      <select
        id="trip_option"
        required
        value={tripOption}
        onChange={(e) => setTripOption(e.target.value as TripOption)}
      >
        <option value="full">Full day (drop-off + pick-up)</option>
        <option value="half_drop_off">Half day — drop-off only</option>
        <option value="half_pick_up">Half day — pick-up only</option>
        <option value="half">Half day — leg unknown</option>
        <option value="day_off">Day off (no work)</option>
        <option value="other_ride">
          Other ride (someone else drove — unpaid to you)
        </option>
      </select>
      <label htmlFor="driven_note">Note (optional)</label>
      <input
        id="driven_note"
        type="text"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <button type="submit">
        {isSingle
          ? singleExistingLog
            ? 'Update day'
            : 'Log day'
          : `Log ${dates.length} days`}
      </button>
      <button type="button" onClick={onCancel}>
        Cancel
      </button>
      {singleExistingLog && (
        <button type="button" onClick={handleDelete}>
          Delete day
        </button>
      )}
      {status && <p>{status}</p>}
    </form>
  );
}
