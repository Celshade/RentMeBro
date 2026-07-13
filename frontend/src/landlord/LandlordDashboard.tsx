import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';
import { formatUserName } from '../api/format';
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
  const name = formatUserName(renter);
  return name === renter.email ? name : `${name} (${renter.email})`;
}


/**
 * Landlord's home screen: manage lease config, review logged days,
 * generate invoices.
 * @param props.gasBillingEnabled - Whether the gas-billing section
 *   (mileage profile, gas prices, logged days) is expanded.
 * @param props.onGasBillingEnabledChange - Called to expand/collapse the
 *   gas-billing section; the caller renders the matching "back to
 *   dashboard" control in the shared header.
 */
export function LandlordDashboard({
  gasBillingEnabled,
  onGasBillingEnabledChange,
}: {
  gasBillingEnabled: boolean;
  onGasBillingEnabledChange: (enabled: boolean) => void;
}) {
  const [lease, setLease] = useState<Lease | null>(null);
  const [logs, setLogs] = useState<DrivenDayLog[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [showGenerateInvoice, setShowGenerateInvoice] = useState(false);

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
      (profiles) => onGasBillingEnabledChange(profiles.length > 0)
    );
  }, [lease, onGasBillingEnabledChange]);

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
        </>
      ) : (
        <button
          type="button"
          onClick={() => onGasBillingEnabledChange(true)}
        >
          Set up gas billing
        </button>
      )}

      {showGenerateInvoice ? (
        <GenerateInvoice
          leaseId={lease.id}
          onGenerated={(invoice) => {
            setInvoices([invoice, ...invoices]);
            setShowGenerateInvoice(false);
          }}
        />
      ) : (
        <button type="button" onClick={() => setShowGenerateInvoice(true)}>
          Generate invoice
        </button>
      )}

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
