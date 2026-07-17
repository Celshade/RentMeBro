import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { apiFetch } from '../api/client';
import { formatInvoiceKind, formatMoney } from '../api/format';
import type { DrivenDayLog, Invoice, InvoiceWeek } from '../api/types';
import { InvoiceStatusBadge } from '../components/InvoiceStatusBadge';
import { DrivenDaysCalendar } from '../landlord/DrivenDaysCalendar';

/** Describes a day_fraction the way the mileage log form does, not as a raw number. */
function formatDayFraction(dayFraction: string): string {
  return Number(dayFraction) >= 0.75
    ? 'Full day (drop-off + pick-up)'
    : 'Half day (drop-off or pick-up only)';
}


/** Turns a week's per-day breakdown into calendar-shaped log entries. */
function weeksToLogs(weeks: InvoiceWeek[]): DrivenDayLog[] {
  const days = weeks.flatMap((week) => week.days);
  return days.map((day, index) => ({
    id: -(index + 1),
    landlord: 0,
    renter: 0,
    date: day.date,
    kind: 'driven',
    day_fraction: day.day_fraction,
    note: '',
  }));
}


/**
 * Full-page invoice detail: the mileage calendar for the billed month
 * alongside a week-by-week breakdown of miles driven and gas cost, for
 * both the renter and the landlord side of an invoice.
 */
export function InvoiceDetail() {
  const { invoiceId } = useParams<{ invoiceId: string }>();
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [weeks, setWeeks] = useState<InvoiceWeek[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      apiFetch<Invoice>(`/api/invoices/${invoiceId}/`),
      apiFetch<InvoiceWeek[]>(`/api/invoices/${invoiceId}/weeks/`),
    ])
      .then(([fetchedInvoice, fetchedWeeks]) => {
        setInvoice(fetchedInvoice);
        setWeeks(fetchedWeeks);
      })
      .catch(() => setError('Could not load this invoice.'))
      .finally(() => setLoading(false));
  }, [invoiceId]);

  if (loading) return <p className="empty-state">Loading invoice…</p>;
  if (error) return <p className="empty-state">{error}</p>;
  if (!invoice) return <p className="empty-state">Invoice not found.</p>;

  const month = String(invoice.billing_period.month).padStart(2, '0');
  const hasGasBreakdown = invoice.kind !== 'rent_only';

  return (
    <div className="invoice-detail">
      <div className="dashboard-toolbar">
        <h1>
          Invoice for {invoice.billing_period.year}-{month}
        </h1>
        <Link to="/">← Back to dashboard</Link>
      </div>

      <div className="stat-grid">
        <div className="stat-tile">
          <span className="stat-tile__label">Status</span>
          <span className="stat-tile__value">
            <InvoiceStatusBadge
              status={invoice.status}
              isLate={invoice.is_late}
            />
          </span>
        </div>
        <div className="stat-tile">
          <span className="stat-tile__label">Kind</span>
          <span className="stat-tile__value">
            {formatInvoiceKind(invoice.kind)}
          </span>
        </div>
        <div className="stat-tile">
          <span className="stat-tile__label">Due date</span>
          <span className="stat-tile__value">{invoice.due_date}</span>
        </div>
        <div className="stat-tile">
          <span className="stat-tile__label">Total</span>
          <span className="stat-tile__value">${invoice.total}</span>
        </div>
      </div>

      <section className="card">
        <div className="card__header">
          <h2>Line items</h2>
        </div>
        <ul className="list">
          {invoice.line_items.map((item) => (
            <li key={item.id} className="list-row">
              <span>{item.description}</span>
              <span>${item.amount}</span>
            </li>
          ))}
        </ul>
      </section>

      {hasGasBreakdown && (
        <div className="dashboard-columns">
          <section className="card">
            <div className="card__header">
              <h2>Mileage log</h2>
            </div>
            <DrivenDaysCalendar
              logs={weeksToLogs(weeks)}
              initialYear={invoice.billing_period.year}
              initialMonth={invoice.billing_period.month - 1}
            />
          </section>

          <section className="card">
            <div className="card__header">
              <h2>Weekly breakdown</h2>
            </div>
            {weeks.length === 0 ? (
              <p className="empty-state">No driven days logged.</p>
            ) : (
              <ul className="list">
                {weeks.map((week) => (
                  <li key={week.week_start} className="invoice-detail__week">
                    <div className="list-row">
                      <span>
                        {week.week_start} – {week.week_end}
                        {' — '}${formatMoney(week.price_per_gallon)}/gal
                      </span>
                      <span>
                        {week.total_miles} mi — ${week.total_gas_cost}
                      </span>
                    </div>
                    <ul className="invoice-detail__week-days">
                      {week.days.map((day) => (
                        <li key={day.date} className="list-row">
                          <span>
                            {day.date} — {formatDayFraction(day.day_fraction)}
                          </span>
                          <span>
                            {day.miles} mi — ${day.gas_cost}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
