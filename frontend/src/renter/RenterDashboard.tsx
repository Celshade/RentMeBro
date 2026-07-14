import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';
import type { DrivenDayLog, Invoice, Lease } from '../api/types';
import { InvoiceStatusBadge } from '../components/InvoiceStatusBadge';
import { PayInvoice } from './PayInvoice';


/** Renter's home screen: log driven days, view and pay invoices. */
export function RenterDashboard() {
  const [lease, setLease] = useState<Lease | null>(null);
  const [logs, setLogs] = useState<DrivenDayLog[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [payingInvoiceId, setPayingInvoiceId] = useState<number | null>(null);

  useEffect(() => {
    apiFetch<Lease[]>('/api/leases/').then(
      (leases) => setLease(leases[0] ?? null)
    );
    apiFetch<DrivenDayLog[]>('/api/driven-days/').then(setLogs);
    apiFetch<Invoice[]>('/api/invoices/').then(setInvoices);
  }, []);

  if (!lease) return <p className="empty-state">No active lease found.</p>;

  return (
    <div className="renter-dashboard">
      <h1>Your rental</h1>

      <div className="stat-grid">
        <div className="stat-tile">
          <span className="stat-tile__label">Monthly rent</span>
          <span className="stat-tile__value">
            ${lease.current_monthly_rent}
          </span>
        </div>
      </div>

      <section className="card">
        <div className="card__header">
          <h2>Logged days</h2>
        </div>
        {logs.length === 0 ? (
          <p className="empty-state">No days logged yet.</p>
        ) : (
          <ul className="list">
            {logs.map((log) => (
              <li key={log.id} className="list-row">
                <span>
                  {log.date} — {log.day_fraction} day
                  {log.note ? ` (${log.note})` : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <div className="card__header">
          <h2>Invoices</h2>
        </div>
        {invoices.length === 0 ? (
          <p className="empty-state">No invoices yet.</p>
        ) : (
          <ul className="list">
            {invoices.map((invoice) => {
              const month = String(invoice.billing_period.month).padStart(
                2,
                '0'
              );
              return (
                <li key={invoice.id} className="list-row">
                  <span>
                    {invoice.billing_period.year}-{month} — {invoice.kind} —
                    ${invoice.total}
                  </span>
                  <span className="renter-dashboard__invoice-actions">
                    <InvoiceStatusBadge status={invoice.status} />
                    {invoice.status !== 'paid' && (
                      <button
                        type="button"
                        onClick={() => setPayingInvoiceId(invoice.id)}
                      >
                        Pay
                      </button>
                    )}
                  </span>
                  {payingInvoiceId === invoice.id && (
                    <PayInvoice
                      invoiceId={invoice.id}
                      onPaid={() => {
                        setPayingInvoiceId(null);
                        apiFetch<Invoice[]>('/api/invoices/').then(
                          setInvoices
                        );
                      }}
                    />
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
