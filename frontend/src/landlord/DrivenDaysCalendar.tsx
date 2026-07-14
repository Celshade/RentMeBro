import { useState } from 'react';
import type { DrivenDayLog } from '../api/types';

const MONTH_NAMES = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];
const WEEKDAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/** Formats a Date as a local (not UTC) YYYY-MM-DD key. */
function toDateKey(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/**
 * Month-grid calendar highlighting driven days, with a small bar
 * under the date proportional to the fraction of the day logged and a
 * distinct color for half vs. full days. Clicking a day logs it (or
 * edits the existing entry, if any).
 * @param props.logs - All driven-day logs for the renter.
 * @param props.onDayClick - Called with a date (YYYY-MM-DD) and its
 *   existing log, if any, when a day cell is clicked.
 */
export function DrivenDaysCalendar({
  logs,
  onDayClick,
}: {
  logs: DrivenDayLog[];
  onDayClick: (date: string, log: DrivenDayLog | null) => void;
}) {
  const today = new Date();
  const [viewYear, setViewYear] = useState(today.getFullYear());
  const [viewMonth, setViewMonth] = useState(today.getMonth());

  const logsByDate = new Map(logs.map((log) => [log.date, log]));

  function changeMonth(delta: number) {
    const next = new Date(viewYear, viewMonth + delta, 1);
    setViewYear(next.getFullYear());
    setViewMonth(next.getMonth());
  }

  const firstOfMonth = new Date(viewYear, viewMonth, 1);
  const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
  const leadingBlanks = firstOfMonth.getDay();
  const cells: (number | null)[] = [
    ...Array(leadingBlanks).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];

  return (
    <div className="driven-days-calendar">
      <div className="driven-days-calendar__header">
        <button type="button" onClick={() => changeMonth(-1)}>
          ‹
        </button>
        <span>
          {MONTH_NAMES[viewMonth]} {viewYear}
        </span>
        <button type="button" onClick={() => changeMonth(1)}>
          ›
        </button>
      </div>
      <div className="driven-days-calendar__grid">
        {WEEKDAY_LABELS.map((label) => (
          <div key={label} className="driven-days-calendar__weekday">
            {label}
          </div>
        ))}
        {cells.map((day, index) => {
          if (day === null) {
            return (
              <div
                key={`blank-${index}`}
                className={
                  'driven-days-calendar__cell ' +
                  'driven-days-calendar__cell--blank'
                }
              />
            );
          }
          const dateKey = toDateKey(new Date(viewYear, viewMonth, day));
          const log = logsByDate.get(dateKey) ?? null;
          const isFullDay = log !== null && Number(log.day_fraction) >= 1;
          const title = log
            ? `${log.day_fraction} day${log.note ? ` — ${log.note}` : ''}`
            : `Log ${dateKey}`;
          const cellClass = [
            'driven-days-calendar__cell',
            log &&
              (isFullDay
                ? 'driven-days-calendar__cell--full'
                : 'driven-days-calendar__cell--half'),
          ]
            .filter(Boolean)
            .join(' ');
          return (
            <button
              key={dateKey}
              type="button"
              className={cellClass}
              title={title}
              onClick={() => onDayClick(dateKey, log)}
            >
              <span className="driven-days-calendar__day-number">{day}</span>
              {log && (
                <span
                  className="driven-days-calendar__fraction-bar"
                  style={{ width: `${Number(log.day_fraction) * 100}%` }}
                />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
