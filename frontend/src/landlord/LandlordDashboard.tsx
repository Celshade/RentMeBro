import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';
import type { DrivenDayLog, Invoice, Lease } from '../api/types';
import { GenerateInvoice } from './GenerateInvoice';
import { LeaseSettings } from './LeaseSettings';


/**
 * Landlord's home screen: manage lease config, review logged days,
 * generate invoices.
 */
export function LandlordDashboard() {
  const [lease, setLease] = useState<Lease | null>(null);
  const [logs, setLogs] = useState<DrivenDayLog[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);

  useEffect(() => {
    apiFetch<Lease[]>('/api/leases/').then(
      (leases) => setLease(leases[0] ?? null)
    );
    apiFetch<DrivenDayLog[]>('/api/driven-days/').then(setLogs);
    apiFetch<Invoice[]>('/api/invoices/').then(setInvoices);
  }, []);

  if (!lease) return <p>No lease yet — create one via the admin.</p>;

  return (
    <div>
      <h1>Landlord dashboard</h1>
      <p>Monthly rent: ${lease.monthly_rent}</p>

      <LeaseSettings leaseId={lease.id} />

      <h2>Renter's logged days</h2>
      <ul>
        {logs.map((log) => (
          <li key={log.id}>
            {log.date} — {log.day_fraction} day
            {log.note ? ` (${log.note})` : ''}
          </li>
        ))}
      </ul>

      <GenerateInvoice
        leaseId={lease.id}
        onGenerated={(invoice) => setInvoices([invoice, ...invoices])}
      />

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
              {invoice.kind} — ${invoice.total} — {invoice.status}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
