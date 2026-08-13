const SWATCH_ENTRIES: { swatchClass: string; label: string }[] = [
  { swatchClass: 'driven-days-calendar__cell--full', label: 'Full day' },
  { swatchClass: 'driven-days-calendar__cell--half', label: 'Half day' },
  {
    swatchClass: 'driven-days-calendar__cell--other-ride',
    label: 'Other ride',
  },
  { swatchClass: 'driven-days-calendar__cell--day-off', label: 'Day off' },
];

const GLYPH_ENTRIES: { glyph: string; glyphClass: string; label: string }[] = [
  {
    glyph: '↓',
    glyphClass: 'driven-days-calendar__half-leg-glyph--drop_off',
    label: 'Drop-off leg',
  },
  {
    glyph: '↑',
    glyphClass: 'driven-days-calendar__half-leg-glyph--pick_up',
    label: 'Pick-up leg',
  },
];


/** A legend explaining what each DrivenDaysCalendar cell color and
 * glyph means. */
export function DrivenDaysCalendarKey() {
  return (
    <ul className="calendar-key">
      {SWATCH_ENTRIES.map((entry) => (
        <li key={entry.label} className="calendar-key__entry">
          <span className={`calendar-key__swatch ${entry.swatchClass}`} />
          {entry.label}
        </li>
      ))}
      {GLYPH_ENTRIES.map((entry) => (
        <li key={entry.label} className="calendar-key__entry">
          <span
            className={
              `calendar-key__glyph driven-days-calendar__half-leg-glyph ` +
              entry.glyphClass
            }
          >
            {entry.glyph}
          </span>
          {entry.label}
        </li>
      ))}
    </ul>
  );
}
