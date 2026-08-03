const ENTRIES: { swatchClass: string; label: string }[] = [
  { swatchClass: 'driven-days-calendar__cell--full', label: 'Full day' },
  { swatchClass: 'driven-days-calendar__cell--half', label: 'Half day' },
  {
    swatchClass: 'driven-days-calendar__cell--other-ride',
    label: 'Other ride',
  },
  { swatchClass: 'driven-days-calendar__cell--day-off', label: 'Day off' },
];


/** A color legend explaining what each DrivenDaysCalendar cell color means. */
export function DrivenDaysCalendarKey() {
  return (
    <ul className="calendar-key">
      {ENTRIES.map((entry) => (
        <li key={entry.label} className="calendar-key__entry">
          <span className={`calendar-key__swatch ${entry.swatchClass}`} />
          {entry.label}
        </li>
      ))}
    </ul>
  );
}
