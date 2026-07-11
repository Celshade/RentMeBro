import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';
import type { DrivenDayLog, Invoice, Lease } from '../api/types';
import { InvoiceStatusBadge } from '../components/InvoiceStatusBadge';
import { DrivenDayForm } from './DrivenDayForm';
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

  if (!lease) return <p>No active lease found.</p>;

  return (
    <div>
      <h1>Your rental</h1>
      <p>Monthly rent: ${lease.monthly_rent}</p>

      <DrivenDayForm
        leaseId={lease.id}
        onLogged={(log) => setLogs([...logs, log])}
      />

      <h2>Logged days</h2>
      <ul>
        {logs.map((log) => (
          <li key={log.id}>
            {log.date} — {log.day_fraction} day
            {log.note ? ` (${log.note})` : ''}
          </li>
        ))}
      </ul>

      <h2>Invoices</h2>
      <ul>
        {invoices.map((invoice) => {
          const month = String(invoice.billing_period.month).padStart(
            2,
            '0'
          );
          return (
            <li key={invoice.id}>
              {invoice.billing_period.year}-{month}
              {' — '}
              {invoice.kind} — ${invoice.total}{' '}
              <InvoiceStatusBadge status={invoice.status} />
              {invoice.status !== 'paid' && (
                <>
                  {' '}
                  <button onClick={() => setPayingInvoiceId(invoice.id)}>
                    Pay
                  </button>
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
                </>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
