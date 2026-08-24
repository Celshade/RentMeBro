import { Fragment, useState } from 'react';
import { MONTH_NAMES } from '../api/format';
import type { DrivenDayLog } from '../api/types';

const WEEKDAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/** Formats a Date as a local (not UTC) YYYY-MM-DD key. */
function toDateKey(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/** Human-readable label for a driven day's fraction and leg. */
function fractionLabel(
  dayFraction: string,
  halfLeg: DrivenDayLog['half_leg']
): string {
  if (Number(dayFraction) >= 1) return 'Full day';
  return halfLeg === 'drop_off'
    ? 'Half day (drop-off)'
    : halfLeg === 'pick_up'
      ? 'Half day (pick-up)'
      : 'Half day';
}

/**
 * The gas price in effect for a date, from `pricedWeekRanges`.
 * @param dateKey - The date to look up (YYYY-MM-DD).
 * @param ranges - Effective date ranges and prices, as passed to
 *   `DrivenDaysCalendar`.
 * @returns The matching price per gallon, or undefined if none covers
 *   the date.
 */
function priceForDate(
  dateKey: string,
  ranges: { from: string; to: string | null; price_per_gallon: string }[]
): string | undefined {
  return ranges.find(
    (range) =>
      range.from <= dateKey && (range.to === null || range.to >= dateKey)
  )?.price_per_gallon;
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
 * @param props.pricedWeekRanges - Effective date ranges (and prices) of
 *   existing gas price entries, used to color the per-week price
 *   button when a week is already priced and to show that week's
 *   price in day-cell hover text.
 * @param props.initialYear - Calendar year to open on. Defaults to the
 *   current year.
 * @param props.initialMonth - Calendar month to open on (0-11).
 *   Defaults to the current month.
 * @param props.lockedMonths - Months with a drafted invoice ("YYYY-MM"),
 *   which become read-only.
 */
export function DrivenDaysCalendar({
  logs,
  onDayClick,
  selectedDates,
  onToggleDate,
  onSetWeekPrice,
  pricedWeekRanges,
  initialYear,
  initialMonth,
  lockedMonths,
}: {
  logs: DrivenDayLog[];
  onDayClick?: (date: string, log: DrivenDayLog | null) => void;
  selectedDates?: Set<string>;
  onToggleDate?: (date: string) => void;
  onSetWeekPrice?: (weekStart: string, weekEnd: string) => void;
  pricedWeekRanges?: {
    from: string;
    to: string | null;
    price_per_gallon: string;
  }[];
  initialYear?: number;
  initialMonth?: number;
  lockedMonths?: Set<string>;
}) {
  const today = new Date();
  const [viewYear, setViewYear] = useState(initialYear ?? today.getFullYear());
  const [viewMonth, setViewMonth] = useState(
    initialMonth ?? today.getMonth()
  );

  const viewMonthKey = `${viewYear}-${String(viewMonth + 1).padStart(2, '0')}`;
  const isMonthLocked = lockedMonths?.has(viewMonthKey) ?? false;
  const activeOnDayClick = isMonthLocked ? undefined : onDayClick;
  const activeOnToggleDate = isMonthLocked ? undefined : onToggleDate;
  const activeOnSetWeekPrice = isMonthLocked ? undefined : onSetWeekPrice;

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
          {isMonthLocked && ' 🔒'}
        </span>
        <button type="button" onClick={() => changeMonth(1)}>
          ›
        </button>
      </div>
      <div
        className={
          'driven-days-calendar__grid' +
          (activeOnSetWeekPrice
            ? ' driven-days-calendar__grid--with-price'
            : '')
        }
      >
        {WEEKDAY_LABELS.map((label) => (
          <div key={label} className="driven-days-calendar__weekday">
            {label}
          </div>
        ))}
        {activeOnSetWeekPrice && (
          <div className="driven-days-calendar__weekday" />
        )}
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
              const cellDate = new Date(viewYear, viewMonth, day);
              const dateKey = toDateKey(cellDate);
              const log = logsByDate.get(dateKey) ?? null;
              const isFullDay = log !== null && Number(log.day_fraction) >= 1;
              const price = priceForDate(dateKey, pricedWeekRanges ?? []);
              const priceSuffix = price ? ` — $${price}/gal` : '';
              const title = log
                ? log.kind === 'day_off'
                  ? `Day off${log.note ? ` — ${log.note}` : ''}`
                  : log.kind === 'other_ride'
                    ? `Other ride${log.note ? ` — ${log.note}` : ''}`
                    : `${fractionLabel(log.day_fraction, log.half_leg)}` +
                      `${priceSuffix}${log.note ? ` — ${log.note}` : ''}`
                : `Log ${dateKey}${priceSuffix}`;
              const isSelected = selectedDates?.has(dateKey) ?? false;
              const cellClass = [
                'driven-days-calendar__cell',
                log?.kind === 'day_off' && 'driven-days-calendar__cell--day-off',
                log?.kind === 'other_ride' &&
                  'driven-days-calendar__cell--other-ride',
                log?.kind === 'driven' &&
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
              const fractionBar = log?.kind === 'driven' && (
                <span
                  className="driven-days-calendar__fraction-bar"
                  style={{ width: `${Number(log.day_fraction) * 100}%` }}
                />
              );
              const halfLegGlyph = log?.kind === 'driven' &&
                !isFullDay &&
                log.half_leg !== '' && (
                  <span
                    className={
                      'driven-days-calendar__half-leg-glyph ' +
                      `driven-days-calendar__half-leg-glyph--${log.half_leg}`
                    }
                  >
                    {log.half_leg === 'drop_off' ? '↓' : '↑'}
                  </span>
                );
              const otherRideBar = log?.kind === 'other_ride' && (
                <span className="driven-days-calendar__fraction-bar" />
              );
              if (activeOnToggleDate) {
                return (
                  <button
                    key={dateKey}
                    type="button"
                    className={cellClass}
                    title={title}
                    onClick={() => activeOnToggleDate(dateKey)}
                  >
                    {dayNumber}
                    {fractionBar}
                    {halfLegGlyph}
                    {otherRideBar}
                  </button>
                );
              }
              if (!activeOnDayClick) {
                return (
                  <div key={dateKey} className={cellClass} title={title}>
                    {dayNumber}
                    {fractionBar}
                    {halfLegGlyph}
                    {otherRideBar}
                  </div>
                );
              }
              return (
                <button
                  key={dateKey}
                  type="button"
                  className={cellClass}
                  title={title}
                  onClick={() => activeOnDayClick(dateKey, log)}
                >
                  {dayNumber}
                  {fractionBar}
                  {halfLegGlyph}
                  {otherRideBar}
                </button>
              );
            })}
            {activeOnSetWeekPrice &&
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
                const weekStartKey = toDateKey(weekStart);
                const weekEndKey = toDateKey(weekEnd);
                const isPriced = (pricedWeekRanges ?? []).some(
                  (range) =>
                    range.from <= weekEndKey &&
                    (range.to === null || range.to >= weekStartKey)
                );
                const weekPrice = priceForDate(
                  weekStartKey,
                  pricedWeekRanges ?? []
                );
                const weekPriceSuffix = weekPrice
                  ? `$${weekPrice}/gal — `
                  : '';
                return (
                  <button
                    type="button"
                    className={
                      'driven-days-calendar__week-price-btn' +
                      (isPriced
                        ? ' driven-days-calendar__week-price-btn--priced'
                        : '')
                    }
                    title={
                      (isPriced
                        ? `Gas price set — ${weekPriceSuffix}`
                        : 'Set gas price for ') +
                      `${weekStartKey} through ${weekEndKey}`
                    }
                    onClick={() =>
                      activeOnSetWeekPrice(weekStartKey, weekEndKey)
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
