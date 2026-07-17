import { Fragment, useState } from 'react';
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
 * distinct color for half vs. full days. When `onToggleDate` is
 * given, clicking a day toggles it in/out of `selectedDates` instead
 * of opening it directly, for logging several days at once.
 * Otherwise, when `onDayClick` is given, clicking a day logs it (or
 * edits the existing entry, if any). With neither, the grid is
 * read-only.
 * @param props.logs - All driven-day logs for the renter.
 * @param props.onDayClick - Called with a date (YYYY-MM-DD) and its
 *   existing log, if any, when a day cell is clicked. Omit to render
 *   a read-only calendar.
 * @param props.selectedDates - Dates currently selected for a bulk
 *   log action, when `onToggleDate` is in use.
 * @param props.onToggleDate - Called with a date (YYYY-MM-DD) when a
 *   day cell is clicked, to add/remove it from `selectedDates`.
 *   Takes priority over `onDayClick` when both are given.
 * @param props.onSetWeekPrice - Called with a calendar week's start
 *   and end dates (YYYY-MM-DD, Sunday through Saturday) when its
 *   per-week price button is clicked. Omit to hide that button.
 */
export function DrivenDaysCalendar({
  logs,
  onDayClick,
  selectedDates,
  onToggleDate,
  onSetWeekPrice,
}: {
  logs: DrivenDayLog[];
  onDayClick?: (date: string, log: DrivenDayLog | null) => void;
  selectedDates?: Set<string>;
  onToggleDate?: (date: string) => void;
  onSetWeekPrice?: (weekStart: string, weekEnd: string) => void;
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
  const weeks: (number | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) {
    weeks.push(cells.slice(i, i + 7));
  }

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
      <div
        className={
          'driven-days-calendar__grid' +
          (onSetWeekPrice ? ' driven-days-calendar__grid--with-price' : '')
        }
      >
        {WEEKDAY_LABELS.map((label) => (
          <div key={label} className="driven-days-calendar__weekday">
            {label}
          </div>
        ))}
        {onSetWeekPrice && <div className="driven-days-calendar__weekday" />}
        {weeks.map((week, weekIndex) => (
          <Fragment key={weekIndex}>
            {week.map((day, dayIndex) => {
              const index = weekIndex * 7 + dayIndex;
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
              const isSelected = selectedDates?.has(dateKey) ?? false;
              const cellClass = [
                'driven-days-calendar__cell',
                log &&
                  (isFullDay
                    ? 'driven-days-calendar__cell--full'
                    : 'driven-days-calendar__cell--half'),
                isSelected && 'driven-days-calendar__cell--selected',
              ]
                .filter(Boolean)
                .join(' ');
              const dayNumber = (
                <span className="driven-days-calendar__day-number">
                  {day}
                </span>
              );
              const fractionBar = log && (
                <span
                  className="driven-days-calendar__fraction-bar"
                  style={{ width: `${Number(log.day_fraction) * 100}%` }}
                />
              );
              if (onToggleDate) {
                return (
                  <button
                    key={dateKey}
                    type="button"
                    className={cellClass}
                    title={title}
                    onClick={() => onToggleDate(dateKey)}
                  >
                    {dayNumber}
                    {fractionBar}
                  </button>
                );
              }
              if (!onDayClick) {
                return (
                  <div key={dateKey} className={cellClass} title={title}>
                    {dayNumber}
                    {fractionBar}
                  </div>
                );
              }
              return (
                <button
                  key={dateKey}
                  type="button"
                  className={cellClass}
                  title={title}
                  onClick={() => onDayClick(dateKey, log)}
                >
                  {dayNumber}
                  {fractionBar}
                </button>
              );
            })}
            {onSetWeekPrice &&
              (() => {
                const weekStart = new Date(
                  viewYear,
                  viewMonth,
                  1 - leadingBlanks + weekIndex * 7
                );
                const weekEnd = new Date(
                  viewYear,
                  viewMonth,
                  1 - leadingBlanks + weekIndex * 7 + 6
                );
                return (
                  <button
                    type="button"
                    className="driven-days-calendar__week-price-btn"
                    title={
                      `Set gas price for ${toDateKey(weekStart)} through ` +
                      toDateKey(weekEnd)
                    }
                    onClick={() =>
                      onSetWeekPrice(toDateKey(weekStart), toDateKey(weekEnd))
                    }
                  >
                    $
                  </button>
                );
              })()}
          </Fragment>
        ))}
      </div>
    </div>
  );
}
