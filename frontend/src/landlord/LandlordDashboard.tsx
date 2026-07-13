import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';
import type {
  DrivenDayLog,
  Invoice,
  Lease,
  MileageProfile,
  User,
} from '../api/types';
import { InvoiceStatusBadge } from '../components/InvoiceStatusBadge';
import { CreateLease } from './CreateLease';
import { GenerateInvoice } from './GenerateInvoice';
import { LeaseSettings } from './LeaseSettings';

/** Formats a renter's name (if set) and email for display. */
function formatRenter(renter: User): string {
  const name = [renter.first_name, renter.last_name]
    .filter(Boolean)
    .join(' ');
  return name ? `${name} (${renter.email})` : renter.email;
}


/**
 * Landlord's home screen: manage lease config, review logged days,
 * generate invoices.
 */
export function LandlordDashboard() {
  const [lease, setLease] = useState<Lease | null>(null);
  const [logs, setLogs] = useState<DrivenDayLog[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [gasBillingEnabled, setGasBillingEnabled] = useState(false);

  useEffect(() => {
    apiFetch<Lease[]>('/api/leases/').then(
      (leases) => setLease(leases[0] ?? null)
    );
    apiFetch<DrivenDayLog[]>('/api/driven-days/').then(setLogs);
    apiFetch<Invoice[]>('/api/invoices/').then(setInvoices);
  }, []);

  useEffect(() => {
    if (!lease) return;
    apiFetch<MileageProfile[]>('/api/mileage-profiles/').then(
      (profiles) => setGasBillingEnabled(profiles.length > 0)
    );
  }, [lease]);

  if (!lease) return <CreateLease onCreated={setLease} />;

  return (
    <div>
      <h1>Landlord dashboard</h1>
      <p>
        Monthly rent: ${lease.monthly_rent} — Renter:{' '}
        {formatRenter(lease.renter_detail)}
      </p>

      {gasBillingEnabled ? (
        <>
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

          <button type="button" onClick={() => setGasBillingEnabled(false)}>
            Back to dashboard
          </button>
        </>
      ) : (
        <button type="button" onClick={() => setGasBillingEnabled(true)}>
          Set up gas billing
        </button>
      )}

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
              {invoice.kind} — ${invoice.total}{' '}
              <InvoiceStatusBadge status={invoice.status} />
            </li>
          );
        })}
      </ul>
    </div>
  );
}
